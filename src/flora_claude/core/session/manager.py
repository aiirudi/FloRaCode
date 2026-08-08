from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from flora_claude.core.session.model import Session,SessionMode, SessionStatus
from flora_claude.core.session.store import SessionStore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flora_claude.core.runner import AgentRunner
from flora_claude.core.events.bus import EventBus
from flora_claude.core.bus.events import SessionCreatedEvent, SessionResumedEvent, SessionMessageReceivedEvent, SessionClosedEvent, SessionWaitingForInputEvent
from flora_claude.core.bus.envelope import HandlerError
from flora_claude.core.runs import new_run_id

def _now():
    return datetime.now(UTC).isoformat()


SESSION_NOT_FOUND = -32010
SESSION_CLOSED = -32011
SESSION_BUSY = -32012

class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        runner_factory: Callable[[], AgentRunner],
        bus: EventBus,
    ):
        self._runner_factory = runner_factory
        self._store = store
        self._bus = bus
        self._sessions: dict[str, Session] = {}
        # session 锁，一个session 只会被同一个进程同时拥有
        self._lock: dict[str, asyncio.Lock] = {}


    # 创建新 session 并写入 meta.json
    async def create(self, mode: SessionMode, title: str = "") -> Session:
        sid = f"sess-{uuid.uuid4().hex[:12]}"
        ts = _now()
        session = Session(
            id=sid,
            mode=mode,
            status="active",
            created_at=ts,
            updated_at=ts,
            title=title,
            run_ids=[],
        )
        self._sessions[sid] = session
        self._lock[sid] = asyncio.Lock()
        self._store.write_meta(session)
        await self._bus.publish(
            SessionCreatedEvent(session_id=sid, mode=mode, ts=ts)
        )
        return session

    # 处理用户消息，追加一次 thread 并启动一次 agent run
    async def send_message(self, sid: str, content: str, *, run_id: str | None = None) -> str:
        session = self._get_session(sid)
        lock = self._lock[sid]

        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")

        async with lock:
            if session.status == "closed":
                raise HandlerError(SESSION_CLOSED, "session already closed")

            if session.status == "waiting_for_input":
                await self._bus.publish(
                    SessionResumedEvent(session_id=sid, ts=_now())
                )

            self._store.append_message(sid, "user", content)
            await self._bus.publish(
                SessionMessageReceivedEvent(
                    session_id=sid, content=content, ts=_now()
                )
            )

            if not session.title:
                session.title = content[:40]

            run_id = run_id or new_run_id()
            session.run_ids.append(run_id)
            session.updated_at = _now()
            self._store.write_meta(session)

            runner = self._runner_factory()
            await runner.run_and_capture(
                content,
                run_id=run_id,
                session=session,
                store=self._store
            )

            session.updated_at = _now()
            if session.mode == "one_shot":
                session.status = "closed"
                await self._bus.publish(
                    SessionClosedEvent(session_id=sid, ts=_now())
                )
            else:
                session.status = "waiting_for_input"
                await self._bus.publish(
                    SessionWaitingForInputEvent(
                        session_id=sid, last_run_id=run_id, ts=_now()
                    )
                )
            self._store.write_meta(session)
            return run_id

    # 关闭指定 session 并更新meta.json
    async def close(self, sid: str) -> None:
        session = self._get_session(sid)
        lock = self._lock[sid]
        if lock.locked():
            raise HandlerError(SESSION_BUSY, "session busy")

        async with lock:
            session.status = "closed"
            session.updated_at = _now()
            self._store.write_meta(session)
            await self._bus.publish(
                SessionClosedEvent(
                    session_id=sid, ts=session.updated_at
                )
            )
            

    # 读取指定session 的 thread 历史
    async def get_history(self, sid: str) -> list[dict[str, Any]]:
        # 守卫检查，用来判断是否真的存在对应sid的session
        self._get_session(sid)
        messages = self._store.read_messages(sid)
        return messages

    # 从内存索引
    def _get_session(self, sid: str) -> Session:
        session =  self._sessions.get(sid)
        if session is None:
            raise HandlerError(SESSION_NOT_FOUND, "session not found")
        return session