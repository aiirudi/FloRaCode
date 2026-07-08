from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid

from dataclasses import dataclass
from pydantic import BaseModel

from flora_claude.core.bus.envelope import EventPushEnvelope

logger = logging.getLogger(__name__)

@dataclass
class _Subscription:
    sub_id: str
    writer: asyncio.StreamWriter
    topics: list[str]
    scope: str


class IpcEventBroadcaster:
    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []

    
    def subscribe(
        self,
        writer: asyncio.StreamWriter,
        topics: list[str],
        scope: str="global",
    ) -> str:
        sub_id = f"sub-{uuid.uuid4().hex[:8]}"
        sub = _Subscription(
            sub_id=sub_id,
            writer=writer,
            topics=topics,
            scope=scope
        )

        self._subscriptions.append(sub)
        return sub_id


    # 移除指定writer的所有订阅
    def unsubscribe(self, writer: asyncio.StreamWriter) -> None:
        self._subscriptions = [s for s in self._subscriptions if s.writer is not writer]

    # 将事件推送到所有匹配的订阅客户端，写入失败时延迟清理死连接
    async def handle(self, event: BaseModel) -> None:
        event_dict = event.model_dump()
        event_type: str = event_dict.get("type", "")
        run_id: str | None = event_dict.get("run_id")

        dead: list[asyncio.StreamWriter] = []

        for sub in list(self._subscriptions):
            if not self._matches_topic(event_type, sub.topics):
                continue
            if not self._matches_scope(run_id, sub.scope):
                continue

            try:
                envelope = EventPushEnvelope(event=event_dict)
                sub.writer.write(envelope.model_dump_json().encode() + b"\n")
                await sub.writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                logger.debug("dead connection for sub %s, scheduling cleanup", sub.sub_id)
                dead.append(sub.writer)

        for writer in dead:
            self.unsubscribe(writer)    


    @staticmethod
    def _matches_topic(event_type: str, topics: list[str])-> bool:
        return any(fnmatch.fnmatch(event_type, pattern) for pattern in topics)

    @staticmethod
    def _matches_scope(run_id: str | None, scope: str) -> bool:
        if scope == "global":
            return True
        if scope.startswith("run:"):
            return run_id == scope[4:]
        return False