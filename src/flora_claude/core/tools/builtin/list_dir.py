from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from flora_claude.core.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from flora_claude.core.sandbox.runtime import SandboxExecutor


_MAX_DEPTH = 4
_MAX_ENTRIES = 200

class ListDirParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = "."
    max_depth: int = Field(default=2, ge=1, le=_MAX_DEPTH)

class ListDirTool(BaseTool):
    params_model = ListDirParams
    name = "list_dir"
    description = (
        "List the contents of a directory as a tree. "
        "Path must be relative to the current working directory. "
        "Hidden entries (starting with .) are included. "
        f"Maximum depth is {_MAX_DEPTH}, maximum total entries is {_MAX_ENTRIES}."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the directory (default '.').",
            },
            "max_depth": {
                "type": "integer",
                "description": f"How many levels deep to recurse (default 2, max {_MAX_DEPTH}).",
            }
        },
        "required": [],
    }

    def __init__(
        self,
        sandbox_executor: SandboxExecutor | None = None,
        *,
        workspace_root: Path | None = None,
    ) -> None:
        self._sandbox_executor = sandbox_executor
        self._workspace_root = workspace_root

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        p = ListDirParams.model_validate(params)
        path_str = p.path
        max_depth = p.max_depth

        if self._sandbox_executor is not None:
            return await self._sandbox_executor.list_dir(path_str, max_depth)

        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")

        root = Path(path_str)
        if self._workspace_root is not None and not root.is_absolute():
            root = self._workspace_root / root
        if not root.exists():
            raise FileNotFoundError(f"no such directory: {path_str}")
        if not root.is_dir():
            raise NotADirectoryError(f"not a directory: {path_str}")

        lines: list[str] = [str(root) + "/"]
        count = 0

        def _walk(directory: Path, depth: int, prefix: str) -> None:
            nonlocal count
            if depth > max_depth or count >= _MAX_ENTRIES:
                return

            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name))
            for i, entry in enumerate(entries):
                if count >= _MAX_ENTRIES:
                    lines.append(f"{prefix}... (truncated)")
                    return

                connector = "└── " if i == len(entries) - 1 else "├── "
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                count += 1
                if entry.is_dir() and depth < max_depth:
                    extention = "    " if i == len(entries) - 1 else "│   "
                    _walk(entry, depth + 1, prefix + extention)

        _walk(root, 1, "")
        return ToolResult(content="\n".join(lines))
