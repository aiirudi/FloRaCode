from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from flora_claude.core.agents.loader import AgentProfile, AgentProfileLoader
from flora_claude.core.bus.events import SubagentFinishedEvent, SubagentStartedEvent
from flora_claude.core.context import ExecutionContext
from flora_claude.core.events.bus import EventBus
from flora_claude.core.events.writer import EventWriter
from flora_claude.core.loop import AgentLoop
from flora_claude.core.runs import new_run_id
from flora_claude.core.subagent.registry import BackgroundTaskRegistry
from flora_claude.core.tools.base import BaseTool, ToolResult
from flora_claude.core.tools.builtin.bash import BashTool
from flora_claude.core.tools.builtin.list_dir import ListDirTool
from flora_claude.core.tools.builtin.read_file import ReadFileTool
from flora_claude.core.tools.builtin.task_create import TaskCreateTool
from flora_claude.core.tools.builtin.task_get import TaskGetTool
from flora_claude.core.tools.builtin.task_list import TaskListTool
from flora_claude.core.tools.builtin.task_update import TaskUpdateTool
from flora_claude.core.tools.builtin.write_file import WriteFileTool
from flora_claude.core.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from flora_claude.core.llm.base import LLMProvider
    from flora_claude.core.permissions.manager import PermissionManager

_profile_loader = AgentProfileLoader()


def _now():
    return datetime.now(UTC).isoformat()

class SpawnAgentParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    description: str
    prompt: str
    run_id_background: bool = False
    subagent_type: str = ""

# 在隔离的冷启动上下文中派生子 agent，支持前台阻塞和后台并行两种模式
class SpawnAgentTool(BaseTool):
    name = "spawn_agent"
    description = (
        "Spawn an isolated sub-agent to handle a self-contained sub-task. "
        "The sub-agent starts with a clean context containing only the provided prompt — "
        "it does not inherit the current conversation history. "
        "Use run_in_background=true to run in parallel; retrieve result later with agent_result."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "3-5 word task description shown in progress display",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Complete task description including all context the sub-agent needs. "
                    "The sub-agent cannot see the parent conversation, so be explicit."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": "When true, returns immediately with a run_id; use agent_result to poll.",  # noqa: E501
            },
            "subagent_type": {
                "type": "string",
                "description": "Agent role profile (planner/executor/reviewer). Leave empty for default.",  # noqa: E501
            },
        },
        "required": ["description", "prompt"],
    }
    params_model = SpawnAgentParams

    # 构造 SpawnAgentTool；depth=0 表示根 agent，最大允许嵌套深度为 2，也就是允许 子Agent 创建孙子 Agent
    def __init__(
        self,
        provider: LLMProvider,
        parent_bus: EventBus,
        parent_run_id: str,
        permission_manager: PermissionManager | None,
        max_steps: int,
        task_registry: BackgroundTaskRegistry,
        runs_dir: Path,
        session_id: str,
        depth: int = 0
    ):
        self._provider = provider
        self._parent_bus = parent_bus
        self._parent_run_id = parent_run_id
        self._permission_manager = permission_manager
        self._max_steps = max_steps
        self._task_registry = task_registry
        self._runs_dir = runs_dir
        self._session_id = session_id
        self._depth = depth


    # 派生子 agent，前台时阻塞直到完成并返回结果，后台时立即返回 run_id
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        p = SpawnAgentParams.model_validate(params)

        if self._depth >= 2:
            return ToolResult(
                content="Subagent nesting limit (2) reached; cannot spawn further subagents.",
                is_error=True,
                error_type="runtime_error",
            )

        profile: AgentProfile | None = None
        if p.subagent_type:
            profile = _profile_loader.load(p.subagent_type)
        
        child_run_id = new_run_id()
        child_context = ExecutionContext(
            run_id=child_run_id,
            goal=p.prompt,
            max_steps=self._max_steps,
            system_prompt_override=profile.system_prompt if profile else None
        )

        child_bus = EventBus()

        async def _bridge(event: BaseModel):
            await self._parent_bus.publish(event)

        child_bus.subscribe(_bridge)
        
        
        
