from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from flora_claude.core.config import FloRaConfig
from flora_claude.core.events.bus import EventBus
from flora_claude.core.llm.types import LlmResponse
from flora_claude.core.runner import AgentRunner
from flora_claude.core.sandbox.runtime import SandboxExecutor, SandboxPool
from flora_claude.core.session.model import Session
from flora_claude.core.session.store import SessionStore
from flora_claude.core.task.manager import TaskManager
from flora_claude.core.tools.base import BaseTool, ToolResult


def _session(root: Path, mode: str = "workspace_write") -> Session:
    return Session(
        id="sess-sandbox", mode="chat", status="active", title="",
        created_at="t", updated_at="t", workspace_root=str(root),
        sandbox_mode=mode,  # type: ignore[arg-type]
    )


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def read_file(self, path: str) -> ToolResult:
        self.calls.append(("read_file", path))
        return ToolResult("sandbox read")

    async def write_file(self, path: str, content: str) -> ToolResult:
        self.calls.append(("write_file", (path, content)))
        return ToolResult("sandbox write")

    async def list_dir(self, path: str, max_depth: int) -> ToolResult:
        self.calls.append(("list_dir", (path, max_depth)))
        return ToolResult("sandbox list")

    async def bash(self, command: str, timeout: int) -> ToolResult:
        self.calls.append(("bash", (command, timeout)))
        return ToolResult("sandbox bash")


class _McpTool(BaseTool):
    name = "host_mcp__read_secret"
    description = "host tool"
    input_schema: dict[str, object] = {"type": "object"}

    async def invoke(self, params: dict[str, object]) -> ToolResult:
        return ToolResult("host")


class _McpManager:
    def get_tools(self) -> list[BaseTool]:
        return [_McpTool()]


async def test_sandbox_registry_routes_all_filesystem_tools_and_hides_mcp(
    tmp_path: Path,
) -> None:
    runner = AgentRunner(FloRaConfig(), mcp_manager=cast(Any, _McpManager()))
    fake = _FakeExecutor()
    registry = runner._build_registry(
        TaskManager(tmp_path / "tasks"),
        session=_session(tmp_path),
        sandbox_executor=cast(SandboxExecutor, fake),
    )

    assert registry.get("host_mcp__read_secret") is None
    assert (await registry.get("read_file").invoke({"path": "a.txt"})).content == "sandbox read"  # type: ignore[union-attr]
    assert (await registry.get("write_file").invoke({"path": "a.txt", "content": "x"})).content == "sandbox write"  # type: ignore[union-attr]
    assert (await registry.get("list_dir").invoke({"path": ".", "max_depth": 2})).content == "sandbox list"  # type: ignore[union-attr]
    assert (await registry.get("bash").invoke({"command": "pwd"})).content == "sandbox bash"  # type: ignore[union-attr]
    assert [call[0] for call in fake.calls] == [
        "read_file", "write_file", "list_dir", "bash"
    ]


async def test_off_registry_keeps_mcp_tools(tmp_path: Path) -> None:
    runner = AgentRunner(FloRaConfig(), mcp_manager=cast(Any, _McpManager()))
    registry = runner._build_registry(
        TaskManager(tmp_path / "tasks"), session=_session(tmp_path, "off")
    )
    assert registry.get("host_mcp__read_secret") is not None


class _CaptureProvider:
    def __init__(self) -> None:
        self.system: str | None = None

    async def chat(
        self,
        messages: list[dict[str, object]],
        tool_schemas: list[dict[str, object]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        self.system = system
        return LlmResponse(stop_reason="end_turn", text="done")


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []
        self.executor = _FakeExecutor()

    def get(self, session_id: str, workspace_root: Path, mode: str) -> SandboxExecutor:
        self.calls.append((session_id, workspace_root, mode))
        return cast(SandboxExecutor, self.executor)


async def test_session_workspace_drives_project_context_and_pool(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    (workspace / ".flora").mkdir(parents=True)
    (workspace / ".flora" / "context.md").write_text(
        "Unique sandbox project context", encoding="utf-8"
    )
    session = _session(workspace)
    store = SessionStore(tmp_path / "sessions")
    store.append_message(session.id, "user", "hello")
    provider = _CaptureProvider()
    pool = _FakePool()
    runner = AgentRunner(
        FloRaConfig(), provider=provider, sandbox_pool=cast(SandboxPool, pool)
    )

    outcome = await runner.run_and_capture(
        "hello", run_id="run-1", session=session, store=store
    )

    assert outcome.status == "success"
    assert provider.system is not None
    assert "Unique sandbox project context" in provider.system
    assert pool.calls == [(session.id, workspace, "workspace_write")]


async def test_sandbox_ignores_project_context_symlink_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    (workspace / ".flora").mkdir(parents=True)
    outside = tmp_path / "outside-context.md"
    outside.write_text("Do not load this outside file", encoding="utf-8")
    try:
        (workspace / ".flora" / "context.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    session = _session(workspace)
    store = SessionStore(tmp_path / "sessions")
    store.append_message(session.id, "user", "hello")
    provider = _CaptureProvider()
    runner = AgentRunner(
        FloRaConfig(), provider=provider,
        sandbox_pool=cast(SandboxPool, _FakePool()),
    )
    await runner.run_and_capture("hello", run_id="run-2", session=session, store=store)

    assert provider.system is not None
    assert "Do not load this outside file" not in provider.system
