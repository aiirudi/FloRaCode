from __future__ import annotations

import asyncio
import sys
from typing import Any

from flora_claude.core.config import FloRaConfig
from flora_claude.core.transport.socket_client import IpcError, SocketClient

class ChatPrinter:
    # 初始化 chat 模式的流式输出状态
    def __init__(self) -> None:
        self._inline = False