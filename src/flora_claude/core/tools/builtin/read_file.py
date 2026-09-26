from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from flora_claude.core.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from flora_claude.core.sandbox.runtime import SandboxExecutor

_MAX_BYTES = 512 * 1024

class ReadFileParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str

class ReadFileTool(BaseTool):
    params_model = ReadFileParams
    name="read_file"
    description = (
        "Read the text content of a file. "
        "Path must be relative to the current working directory. "
        "Files larger than 512 KB are truncated."
    )
    input_schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file (relative to current working directory).",
            }
        },
        "required": ["path"],
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
        p = ReadFileParams.model_validate(params)
        path_str = p.path

        if self._sandbox_executor is not None:
            return await self._sandbox_executor.read_file(path_str)

        # 避免用户穿越到敏感路径下读取文件
        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")
    
        path = Path(path_str)
        if self._workspace_root is not None and not path.is_absolute():
            path = self._workspace_root / path
        raw = path.read_bytes() # raises FileNotFoundError if absent
        truncated = len(raw) > _MAX_BYTES
        text = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += "\n[truncated]"
        return ToolResult(content=text)
