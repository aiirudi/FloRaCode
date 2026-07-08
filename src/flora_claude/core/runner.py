from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from flora_claude.core.bus.events import RunFinishedEvent, RunStartedEvent
from flora_claude.core.config import FloRaConfig
from flora_claude.core.context import ExecutionContext
from flora_claude.core.events.bus import EventBus, EventHandler
from flora_claude.core.events.writer import EventWriter
from flora_claude.core.llm.base import LLMProvider
from flora_claude.core.llm.provider import AnthropicProvider
from flora_claude.core.loop import AgentLoop
from flora_claude.core.runs import RUNS_DIR, new_run_id
from flora_claude.core.tools.builtin.read_file import ReadFileTool
from flora_claude.core.tools.registry import ToolRegistry

def _now() -> str:
    return datetime.now(UTC).isoformat()


class AgentRunner:
    # 组装所有运行时依赖，准备执行一次完整的 agent run
    def __init__(
        self,
        config: FloRaConfig,
        *,
        bus: EventBus | None = None,
        provider: LLMProvider | None = None,
        extra_handlers: list[EventHandler] | None = None,
        runs_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._bus = bus
        self._extra_handlers: list[EventHandler] = extra_handlers or []
        self._runs_dir = runs_dir or RUNS_DIR

    # 执行一次完整的 agent run：生成 run_id、接线事件总线、驱动 AgentLoop
    async def run(self, goal: str, * , run_id: str | None = None) -> None:
        # 接受外部传入的 id
        run_id = run_id or new_run_id()
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        bus = self._bus if self._bus is not None else EventBus()
        
        for h in self._extra_handlers:
            bus.subscribe(h)

        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent.max_steps,
        )

        async with EventWriter(run_path / "events.jsonl") as writer:
            writer.subscribe(bus)
            await bus.publish(RunStartedEvent(run_id=run_id, goal=goal, ts=_now()))
            
            provider = self._provider or AnthropicProvider(self._config.llm.default_model)
            registry = ToolRegistry()
            registry.register(ReadFileTool())
            loop = AgentLoop(provider, registry, bus)

            cancelled = False
            try:
                await loop.run(context)
            except asyncio.CancelledError:
                cancelled = True
                if not context.is_done():
                    context.mark_failed("cancelled")

            await bus.publish(
                RunFinishedEvent(
                    run_id=run_id,
                    status=context.status,
                    reason=context.reason,
                    steps=context.step,
                    ts=_now(),
                )
            )

        if cancelled:
            raise asyncio.CancelledError()
