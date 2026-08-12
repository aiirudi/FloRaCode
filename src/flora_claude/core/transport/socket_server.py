from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any
from datetime import UTC, datetime

from pydantic import  BaseModel, ValidationError


from flora_claude.core.transport.ipc_broadcaster import IpcEventBroadcaster
from flora_claude.core.trace.record import TraceRecord
from flora_claude.core.trace.writer import TraceWriter
from flora_claude.core.bus.envelope import (
    INTERNAL_ERROR,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
    INVALID_REQUEST,
    JsonRpcRequest,
    JsonRpcSuccess,
    JsonRpcError,
    HandlerError,
    make_error
)

logger = logging.getLogger(__name__)

type CommandHandler = Callable[[dict[str, Any]], Awaitable[Any]]
# 每个连接处理协程中，当前正在处理的 writer（供 handler 读取连接上下文）
_writer_var: ContextVar[asyncio.StreamWriter] = ContextVar("_writer_var")

def _now():
    return datetime.now(UTC).isoformat()

# 返回当前 handler 调用所属连接的 StreamWriter
def get_connection_writer() -> asyncio.StreamWriter:
    return _writer_var.get()

_MAX_LINE_BYTES = 1 * 1024 * 1024

class SocketServer:
    def __init__(self, host: str, port: int, broadcaster: IpcEventBroadcaster | None = None, trace: TraceWriter | None = None) -> None:
        self._host = host
        self._port = port
        self._handlers: dict[str, CommandHandler] = {}
        self._server: asyncio.AbstractServer | None = None
        self._broadcaster = broadcaster
        self._trace = trace
    
    def register(self, method: str, handler: CommandHandler) -> None:
        self._handlers[method] = handler
    
    # 启动 TCP 服务器
    async def start(self) -> str:
        try: 
            # 这里的行为其实是客户端行为，就是用来检测是否已经有一个服务端在运行了
            _r, w = await asyncio.open_connection(self._host, self._port)
            w.close()
            await w.wait_closed()
            raise SystemExit(f"core already running at {self._host}:{self._port}")
        except (ConnectionRefusedError, OSError):
            pass

        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self._host,
            port=self._port,
            limit=_MAX_LINE_BYTES
        )
        return f"{self._host}:{self._port}"
    
    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
    
    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    )-> None:
        peer = writer.get_extra_info("peername", "<unknown>")
        logger.debug("client connected: %s", peer)

        try:
            await self._read_loop(reader, writer)
        finally:
            # 断开连接前先client广播事件
            if self._broadcaster is not None:
                self._broadcaster.unsubscribe(writer)
            # 断开连接
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except (TimeoutError, ConnectionResetError, BrokenPipeError, OSError):
                pass

            logger.debug("client disconnected: %s", peer)
    
    async def  _read_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        while True:
            try:
                line = await reader.readline()
            except asyncio.LimitOverrunError:
                await self._send(writer,make_error(
                    None, INVALID_REQUEST, "Request too large"
                ))
                return
            if not line:
                return

            # 每条命令独立作为 task 执行，避免长时间运行的 handler（如 session.send_message）
            # 阻塞读循环，使 permission.respond 等并发命令能被及时处理
            asyncio.create_task(self._handle_line(line, writer))
    
    async def _handle_line(self, line: bytes, writer: asyncio.StreamWriter):
        try:
            raw:Any = json.loads(line)
        except json.JSONDecodeError as e:
            await self._send(writer, make_error(None, PARSE_ERROR, f"Parse error: {e}"))
            return

        try:
            req = JsonRpcRequest.model_validate(raw)
        except ValidationError as e:
            await self._send(writer, make_error(None, INVALID_REQUEST, "Invalid Request", str(e)))
            return

        if self._trace is not None:
            client_id = str(writer.get_extra_info("peername", "<unknown>"))

            self._trace.emit(
               TraceRecord(
                    ts=_now(),
                    client_id=client_id,
                    layer="ipc",
                    direction="CLIENT->CORE",
                    kind="command",
                    data={"method": req.method,"id":req.id, "params": req.params}
                )
            ) 
        
        handler = self._handlers.get(req.method)
        if handler is None:
            await self._send(writer, make_error(req.id, METHOD_NOT_FOUND, f"Method not found: {req.method}"),
            )
            return
        
        _writer_var.set(writer)
        try:
            result = await handler(req.params)
        except HandlerError as e:
            await self._send(writer, make_error(req.id, e.code, str(e), e.data))
            return 
        except ValidationError as e:
            await self._send(writer, make_error(req.id, INVALID_REQUEST, "Invalid params", str(e)))
            return
        except Exception as e:
            logger.exception("handler %s raised: %s", req.method, e)
            await self._send(writer, make_error(req.id, INTERNAL_ERROR, "Internal error"))
            return
        
        result_data: Any = result.model_dump() if isinstance(result, BaseModel) else result
        try:
            await self._send(writer, JsonRpcSuccess(id=req.id, result=result_data))
        except (ConnectionResetError, BrokenPipeError, OSError):
            logger.debug("client disconnected before response for %s", req.method)


    async def _send(self, writer: asyncio.StreamWriter, msg:BaseModel) -> None:
        writer.write(msg.model_dump_json().encode() + b"\n")
        await writer.drain()

        if self._trace is not None:
            kind = "error" if isinstance(msg, JsonRpcError) else "response"
            client_id = str(writer.get_extra_info("peername", "<unknown>"))

            self._trace.emit(
                TraceRecord(
                    ts=_now(),
                    direction="CORE->CLIENT",
                    layer="ipc",
                    kind=kind,
                    client_id=client_id,
                    data=msg.model_dump()
                )
            )