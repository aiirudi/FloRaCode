from __future__ import annotations

import json

from flora_claude.core.task.manager import TaskManager
from flora_claude.core.tools.base import BaseTool, ToolResult


class TaskListTool(BaseTool):
    name = "task_list"
    description = (
        "List all tasks with their current status and blocking dependencies. "
        "Use this to check what work remains and what can be started next."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, task_manager: TaskManager):
        self._manager = task_manager

    async def invoke(self, params: dict[str, object]):
        return ToolResult(content=self._manager.format_list())