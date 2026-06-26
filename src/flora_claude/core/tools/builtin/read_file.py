from __future__ import annotations

from pathlib import Path

from flora_claude.core.tools.base import BaseTool, ToolResult

_MAX_BYTES = 512 * 1024

class ReadFileTool(BaseTool):
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

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        path_str = str(params["path"])

        # 避免用户穿越到敏感路径下读取文件
        if ".." in Path(path_str).parts:
            raise PermissionError(f"path traversal not allowed: {path_str}")
    
        path = Path(path_str)
        raw = path.read_bytes() # raises FileNotFoundError if absent
        truncated = len(raw) > _MAX_BYTES
        text = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += "\n[truncated]"
        return ToolResult(content=text)
        