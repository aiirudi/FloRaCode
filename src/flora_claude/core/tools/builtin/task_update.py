from __future__ import annotations

import json

from flora_claude.core.task.manager import TaskManager
from flora_claude.core.task.model import TaskStatus
from flora_claude.core.tools.base import ToolResult, BaseTool



class TaskUpdateTool(BaseTool):
    name = "task_update"
    description = (
        "Update a task's status or dependency list. "
        "Set status to 'in_progress' when starting work on a task, "
        "'completed' when finished (automatically clears it from other tasks' blocked_by). "
        "Returns the updated task as JSON."
    )
    input_schema = {
        "type": "object",
        "properties" : {
            "task_id": {
                "type": "integer",
                "description": "ID of the task to update.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "New status for the task.",
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs to add to blocked_by."
            },
            "remove_blocked_by": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Task IDs to remove from blocked_by"
            }
        },
        "required": ["task_id"],
    }

    def __init__(self, task_manager: TaskManager):
        self._manager = task_manager
    
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        task_id = int(str(params["task_id"]))
        status: TaskStatus | None = params.get("status")
        raw_add: list[object] = list(params.get("add_blocked_by") or [])
        raw_remove: list[object] = list(params.get("remove_blocked_by") or [])

        add_blocked_by = [int(str(x)) for x in raw_add]
        remove_blocked_by = [int(str(x)) for x in raw_remove]
        try:
            task = self._manager.update(
                task_id, 
                status=status, 
                add_blocked_by=add_blocked_by or None, remove_blocked_by=remove_blocked_by or None)

            return ToolResult(content=json.dumps(task.to_dict(), ensure_ascii=False))
        except ValueError as exc:
            return ToolResult(str(exc), is_error=True, error_type="runtime_error")

