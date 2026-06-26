from __future__ import annotations

from typing import Protocol

from flora_claude.core.events.bus import EventBus
from flora_claude.core.llm.types import LlmResponse

"""
其实就是类似Jave 中的接口或者抽象类中的抽象方法
要求所有继承 LLMProvider，都必须实现 chat 函数

按照 Java 的思维的化就一定要继承 LLMProvider， 但是在 Python 中， 使用 Protocaol时不必须继承。
在 Python 中只要有一个对象有  async chat(...) -> LlmResponse 方法，它就符合 LLMProvider， 也就是默认就实现了 LLMProvider 类。
"""
class LLMProvider(Protocol):
    # 流式调用 LLM 并发布进度事件, 返回完整响应

    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str,
    ) -> LlmResponse: ...