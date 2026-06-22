from __future__ import annotations

import sys
import time
import datetime
import logging
import asyncio
import signal

from typing import Any

import flora_claude
from flora_claude.core.bus.commands import PongResult
from flora_claude.core.config import get_config
from flora_claude.core.logging_setup import setup_logging
from flora_claude.core.transport.socket_server import SocketServer

logger = logging.getLogger(__name__)

class CoreApp:
    def __init__(self):
        self._start_time = time.monotonic()
    
    async def _ping_handler(self, params: dict[str, Any]) -> PongResult:
        client = params.get("client", "unknown")
        logger.debug("ping from %s",client)
        return PongResult(
            server_version=flora_claude.__version__,
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def run(self) -> None:
        self._start_time = time.monotonic()
        config = get_config()
        setup_logging(config)

        server = SocketServer(config.host, config.port)
        server.register("core.ping", self._ping_handler)

        addr = await server.start()
        logger.info("flora-core %s listening addr=%s", flora_claude.__version__, addr)
        logger.info("config: %s", config)

        shutdown = asyncio.Event()

        if sys.platform == "win32":
            # Windows 不支持 asyncio add_signal_handler，改用 signal 模块
            signal.signal(signal.SIGINT, lambda *_args: shutdown.set())
            signal.signal(signal.SIGTERM, lambda *_args: shutdown.set())
        else:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()

        logger.info("shutting down")
        await server.stop()


def run() -> None:
    asyncio.run(CoreApp().run())




