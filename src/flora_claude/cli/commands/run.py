from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from pydantic import BaseModel

from flora_claude.core.config import FloRaConfig
from flora_claude.core.transport.socket_client import IpcError, SocketClient

from flora_claude.core.bus.events import (
    RunStartedEvent,
    RunFinishedEvent,
    StepStartedEvent,
    StepFinishedEvent,
    ToolCallStartedEvent,
    ToolCallFailedEvent,
    ToolCallFinishedEvent,
    LlmTokenEvent,
)


class StdoutPrinter:

    # 将运行进度格式化打印到
    def __init__(self) -> None:
        # 当 LLM 正在输出时为真，避免要 agent 要进行工具调用的时候在中间输出
        self._inline = False
        self._run_start: float = 0.0

    def _ensure_newline(self) -> None:
        if self._inline:
            print()
            self._inline = False
        
    async def handle(self, event: dict[str, Any]) -> None:
        type = event.get("type", "")
        
        if type == "run.started":
            self._run_start = time.monotonic()
            print(f"[run] {event.get("run_id", "")}")
        
        elif type == "step.started":
            self._ensure_newline()
            print(f"[step {event.get("step")}] planning ...")

        elif type == "llm.token":
            print(event.get("token", ""), end="", flush=True)
            self._inline = True
        
        elif type == "tool.call_started":
            self._ensure_newline()
            params_str = json.dumps(event.get("params"), ensure_ascii=False)
            print(f"[tool] {event.get("tool_name", "")} {params_str}")
        
        elif type == "tool.call_finished":
            print(f"[tool] {event.get("tool_name", "")} ✓  {event.get("elapsed_ms")}ms")
    
        elif type == "tool.call_failed":
            print(
                f"[tool] {event.get("tool_name", "")}✗  {event.get("error_message", "")}",
                file=sys.stderr
            )
        
        elif type == "step.finished":
            self._ensure_newline()
            print(f"[step {event.get("step")}] done")
        
        elif type == "run.finished":
            self._ensure_newline()
            elapsed = time.monotonic() - self._run_start            
            print(f"[run] {event.get("status", "")}  {event.get("steps", "")} steps  {elapsed:.1f}s")

# 异步核心：连接 daemon, 订阅事件，触发run，等待 run.finished
async def _run_async(goal: str, config: FloRaConfig) -> int:
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionRefusedError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file=sys.stderr)
        return 1

    printer = StdoutPrinter()
    finished = asyncio.Event()
    exit_code = 0

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal exit_code
        await printer.handle(event)
        if event.get("type") == "run.finished":
            if event.get("status") != "success":
                exit_code = 1
            finished.set()
    
    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        await client.send_command(
            "event.subscribe",
            {
                "topics": ["run.*", "step.*", "tool.*", "llm.token", "llm.usage"],
                "scope": "global",
            }
        )
        await client.send_command(
            "agent.run",
            {
                "goal": goal
            }
        )
        

    except IpcError as e:
        print(f"error: {e}", file=sys.stderr)
        loop_task.cancel()
        await client.close()
        return 1
    
    await finished.wait()

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    await client.close()
    return exit_code


def cmd_run(goal: str, config: FloRaConfig) -> None:
    try:
        exit_code = asyncio.run(_run_async(goal, config))
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(exit_code)