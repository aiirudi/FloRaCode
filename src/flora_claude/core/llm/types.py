# 定义 LLM Provider 返回给 AgentLoop 的标准数据结构

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    context_pct: float = 0.0

# 表示模型请求一个工具调用
@dataclass
class ToolCallBlock:
    id: str
    name: str
    input: dict[str, object]

# Provider 给 AgentLoop 的统一响应
@dataclass
class LlmResponse:
    stop_reason: str # "end_turn" | "tool_use"
    tool_calls: list[ToolCallBlock] = field(default_factory=list)
    text: str = ""
    usage: UsageStats | None = None
    # thinking blocks from extended thinking — must be preserved verbatim in conversation history
    thinking_blocks: list[dict[str, object]] = field(default_factory=list)