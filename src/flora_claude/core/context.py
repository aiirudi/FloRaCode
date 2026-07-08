from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


"""
保存 agent run 运行一次的上下文
"""

@dataclass
class ExecutionContext:
    run_id: str
    goal: str
    max_steps: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0
    status: str = "running"
    reason: str | None = None

    # 初始化时将 goal 作为第一条用户消息写入消息历史
    def __post_init__(self) -> None:
        if not self.messages:
            self.messages.append({"role": "user", "content": self.goal})
        
    # 将 LLM 响应的content blocks 追加为 assistant 消息
    def add_assistant_message(self, content: list[Any]) -> None:
        self.messages.append({"role": "assistant", "content": content})
    
    # 将工具调用结果追加为 user 消息；同一步的多个结果共享一条消息
    def add_tool_result(
        self, tool_use_id: str, content: str, is_error: bool = False
    ) -> None:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content
        }

        if is_error:
            block["is_error"] = True
        
        """
        如果一次性调用了多个 tool, 就将 tool 调用的返回信息全部放入同一个 message 中
        """
        last = self.messages[-1] if self.messages else None
        if (
            last is not None 
            and last["role"] == "user"
            and isinstance(last["content"], list)
            and last["content"]
            and all(b.get("type") == "tool_result" for b in last["content"])
        ):
            last["content"].append(block)
        else:
            self.messages.append({"role": "user", "content": [block]})
    
    # 当状态不为 running 的时候返回 True, 表示 Agent Loop 应该停止
    def is_done(self) -> bool:
        return self.status != "running"
    
    # 将 run 标记为成功
    def mark_success(self) -> None:
        self.status = "success"
    
    # 将 run 标记为失败，并记录原因
    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.reason = reason

