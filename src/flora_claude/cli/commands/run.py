from __future__ import annotations

import asyncio
import json
import sys
import time

from pydantic import BaseModel

from flora_claude.core.config import FloRaConfig
from flora_claude.core.runner import AgentRunner

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
        
    async def handle(self, event: BaseModel) -> None:
        if isinstance(event, RunStartedEvent):
            self._run_start = time.monotonic()
            print(f"[run] {event.run_id}")
        
        elif isinstance(event, StepStartedEvent):
            self._ensure_newline()
            print(f"[step {event.step}] planning ...")

        elif isinstance(event, LlmTokenEvent):
            print(event.token, end="", flush=True)
            self._inline = True
        
        elif isinstance(event, ToolCallStartedEvent):
            self._ensure_newline()
            params_str = json.dumps(event.params, ensure_ascii=False)
            print(f"[tool] {event.tool_name} {params_str}")
        
        elif isinstance(event, ToolCallFinishedEvent):
            print(f"[tool] {event.tool_name} ✓  {event.elapsed_ms}ms")
    
        elif isinstance(event, ToolCallFailedEvent):
            print(
                f"[tool] {event.tool_name}✗  {event.error_message}",
                file=sys.stderr
            )
        
        elif isinstance(event, StepFinishedEvent):
            self._ensure_newline()
            print(f"[step {event.step}] done")
        
        elif isinstance(event, RunFinishedEvent):
            self._ensure_newline()
            elapsed = time.monotonic() - self._run_start            
            print(f"[run] {event.status}  {event.steps} steps  {elapsed:.1f}s")


def cmd_run(goal: str, config: FloRaConfig) -> None:
    printer = StdoutPrinter()
    runner = AgentRunner(config, extra_handlers=[printer.handle])
    try:
        asyncio.run(runner.run(goal))
    except KeyboardInterrupt:
        sys.exit(130)