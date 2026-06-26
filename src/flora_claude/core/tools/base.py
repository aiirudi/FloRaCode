from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    error_type: str | None = None  # "runtime_error" | "timeout" | "schema_error"


"""
工具抽象基类:定义了所有工具必须满足的契约，任何具体工具
"""
class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict[str, object]

    @abstractmethod
    async def invoke(self, params: dict[str, object]) -> ToolResult: ...
