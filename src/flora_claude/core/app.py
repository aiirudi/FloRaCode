from __future__ import annotations

import sys
import time
import json
import datetime
import fnmatch
import logging
import asyncio
import signal

from typing import Any

import flora_claude
from flora_claude.core.bus.commands import (
    AgentRunCommand,
    AgentRunResult,
    EventSubscribeCommand,
    EventSubscribeResult,
    PongResult,
)

from flora_claude.core.bus.envelope import EventPushEnvelope
from flora_claude.core.logging_setup import setup_logging
from flora_claude.core.runs import events_file, new_run_id
from flora_claude.core.runner import AgentRunner
from flora_claude.core.transport.socket_server import SocketServer, get_connection_writer
from flora_claude.core.events.bus import EventBus
from flora_claude.core.transport.ipc_broadcaster import IpcEventBroadcaster
from flora_claude.core.config import FloRaConfig,get_config

logger = logging.getLogger(__name__)

class CoreApp:
    def __init__(self):
        self._start_time = time.monotonic()
        self._bus = EventBus()
        self._broadcaster = IpcEventBroadcaster()
        self._bus.subscribe(self._broadcaster.handle)
        self._current_run_task: asyncio.Task[None] | None = None #asyncio.Task[None] 中的 None 表示任务的返回类型
        self._config: FloRaConfig | None = None
    
    async def _ping_handler(self, params: dict[str, Any]) -> PongResult:
        client = params.get("client", "unknown")
        logger.debug("ping from %s",client)
        return PongResult(
            server_version=flora_claude.__version__,
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )
    
    #启动一次 agent run：立即返回 run_id， 后台 task 执行 runner.run()
    async def _agent_run_handler(self, params: dict[str, Any]) -> AgentRunResult:
        assert self._config is not None
        cmd=AgentRunCommand.model_validate(params)

        if self._current_run_task is not None and not self._current_run_task.done():
            raise RuntimeError("a run is already in progress")
        
        run_id = new_run_id()
        runner = AgentRunner(self._config, bus=self._bus)

        self._current_run_task = asyncio.create_task(
            runner.run(cmd.goal, run_id=run_id)
        )
        return AgentRunResult(run_id=run_id)

    # 注册客户端事件订阅，可选先回放 events.jsonl 历史再接收实时流
    async def _subscribe_handler(self, params: dict[str, Any]) -> EventSubscribeResult:
        cmd = EventSubscribeCommand.model_validate(params)
        writer = get_connection_writer()

        replayed_count = 0
        if cmd.replay_from_run is not None:
            replayed_count = await self._replay_events(cmd.replay_from_run, writer, cmd.topics)
        
        sub_id = self._broadcaster.subscribe(writer, cmd.topics, scope=cmd.scope)
        return EventSubscribeResult(subscription_id=sub_id, replayed_count=replayed_count)

    # 从 events.jsonl 向 writer 回放匹配 topic 的历史事件，返回已回放条数
    async def _replay_events(
        self, run_id: str,
        writer: asyncio.StreamWriter,
        topics: list[str],
    ) -> int:
        path = events_file(run_id)
        if not path.exists():
            return 0
        
        count = 0
        for line in path.read_text().splitlines():
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type: str = event.get("type", "")
            if not any(fnmatch.fnmatch(event_type, pattern) for pattern in topics):
                continue
            envelope = EventPushEnvelope(event=event)
            writer.write(envelope.model_dump_json().encode() + b"\n")
            count += 1
        
        if count:
            await writer.drain()
        return count

    # 启动守护进程：加载配置、初始化日志、启动 TCP 服务器，并等待退出信号
    async def run(self) -> None:
        self._start_time = time.monotonic()
        self._config = get_config()
        setup_logging(self._config)

        server = SocketServer(self._config.host, self._config.port, self._broadcaster)
        server.register("core.ping", self._ping_handler)
        server.register("agent.run", self._agent_run_handler)
        server.register("event.subscribe", self._subscribe_handler)

        addr = await server.start()
        logger.info("flora-core %s listening addr=%s", flora_claude.__version__, addr)
        logger.info("config: %s", self._config)

        shutdown = asyncio.Event()

        if sys.platform == "win32":
            # Windows 不支持 asyncio add_signal_handler，改用 signal 模块
            signal.signal(signal.SIGINT, lambda *_args: shutdown.set())
            signal.signal(signal.SIGTERM, lambda *_args: shutdown.set())
        else:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()

        logger.info("shutting down")
        await server.stop()


def run() -> None:
    asyncio.run(CoreApp().run())




