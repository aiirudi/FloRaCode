from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel

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

    # params_model 属于类变量, 归这个 BaseTool 类享有
    # 在具体工具类中会像这样 params_model = WriteFileParams, 来替换每个工具类的参数模型类
    # 这里用 type[BaseModel] 是因为在 params_model 中保存的是模型类,后面根据每次工具调用的参数动态创建模型实例, 参数定义形式是ClassVar[type[BaseModel] | None]
    # 如果参数定义形式是ClassVar[BaseModel | None], 这里存储的就是一个实例了
    # 这里其实和之前的代码实现一样, 就比如 FloRaConfig 里面用到了子Config 的配置，所以参数定义就是 TraceConfig, 这样的名字
    # 但是这里是要动态变化的所有就用了 type[BaseModel] 表示只是一个类
    params_model: ClassVar[type[BaseModel] | None] = None  

    @abstractmethod
    async def invoke(self, params: dict[str, object]) -> ToolResult: ...
