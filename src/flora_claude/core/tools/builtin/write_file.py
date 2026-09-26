from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from flora_claude.core.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from flora_claude.core.sandbox.runtime import SandboxExecutor


_MAX_BYTES = 1 * 1024 * 1024  # 1 MB

class WriteFileParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str

class WriteFileTool(BaseTool):
    params_model = WriteFileParams
    name = "write_file"
    description=(
        "Write text content to a file, creating it (and any parent directories) if it "
        "does not exist, or overwriting it if it does. "
        "Path must be relative to the current working directory. "
        "Content size is limited to 1 MB."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file (relative to current working directory).",
            },
            "content": {
                "type": "string",
                "description": "Text content to write.",
            }
        },
        "required": ["path", "content"]
    }

    def __init__(
        self,
        sandbox_executor: SandboxExecutor | None = None,
        *,
        workspace_root: Path | None = None,
    ) -> None:
        self._sandbox_executor = sandbox_executor
        self._workspace_root = workspace_root

    # 写入文件内容；超 1MB 拒绝；禁止 .. 路径遍历；自动创建父目录
    async def invoke(self, params: dict[str, object]) -> ToolResult:
        p = WriteFileParams.model_validate(params)
        path_str = p.path
        content = p.content

        if self._sandbox_executor is not None:
            return await self._sandbox_executor.write_file(path_str, content)

        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")

        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_BYTES:
            return ToolResult(
                content=f"content too large: {len(encoded)} bytes (limit 1 MB)",
                is_error=True,
                error_type="runtime_error"
            )

        path = Path(path_str)
        if self._workspace_root is not None and not path.is_absolute():
            path = self._workspace_root / path
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(content, encoding="utf-8")

        return ToolResult(content=f"wrote {len(encoded)} bytes to {path_str}")
