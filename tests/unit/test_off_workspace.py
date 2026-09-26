from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

from flora_claude.core.config import FloRaConfig
from flora_claude.core.events.bus import EventBus
from flora_claude.core.llm.types import LlmResponse
from flora_claude.core.runner import AgentRunner
from flora_claude.core.session.model import Session
from flora_claude.core.subagent.registry import BackgroundTaskRegistry
from flora_claude.core.subagent.tool import SpawnAgentTool
from flora_claude.core.task.manager import TaskManager
from flora_claude.core.tools.builtin.bash import BashTool
from flora_claude.core.tools.builtin.list_dir import ListDirTool
from flora_claude.core.tools.builtin.read_file import ReadFileTool
from flora_claude.core.tools.builtin.write_file import WriteFileTool


async def test_off_tools_use_selected_workspace_for_relative_paths(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "chosen"
    workspace.mkdir()
    daemon_cwd = tmp_path / "daemon"
    daemon_cwd.mkdir()
    monkeypatch.chdir(daemon_cwd)
    (workspace / "input.txt").write_text("chosen content", encoding="utf-8")
    (daemon_cwd / "input.txt").write_text("wrong content", encoding="utf-8")

    assert (await ReadFileTool(workspace_root=workspace).invoke({"path": "input.txt"})).content == "chosen content"
    write = await WriteFileTool(workspace_root=workspace).invoke({
        "path": "nested/out.txt", "content": "new content"
    })
    assert not write.is_error
    assert (workspace / "nested" / "out.txt").read_text(encoding="utf-8") == "new content"
    assert not (daemon_cwd / "nested" / "out.txt").exists()
    listed = await ListDirTool(workspace_root=workspace).invoke({"path": "."})
    assert "input.txt" in listed.content
    assert "nested" in listed.content

    outside = tmp_path / "outside.txt"
    outside.write_text("host access", encoding="utf-8")
    assert (await ReadFileTool(workspace_root=workspace).invoke({"path": str(outside)})).content == "host access"

    command = f'"{sys.executable}" -c "import os; print(os.getcwd())"'
    bash = await BashTool(workspace_root=workspace).invoke({"command": command})
    assert not bash.is_error
    assert str(workspace).lower() in bash.content.lower()


async def test_off_session_and_child_registries_inherit_workspace(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "chosen"
    workspace.mkdir()
    (workspace / "input.txt").write_text("child content", encoding="utf-8")
    daemon_cwd = tmp_path / "daemon"
    daemon_cwd.mkdir()
    monkeypatch.chdir(daemon_cwd)
    session = Session(
        id="sess-off", mode="chat", status="active", title="",
        created_at="t", updated_at="t", workspace_root=str(workspace),
        sandbox_mode="off",
    )
    runner = AgentRunner(FloRaConfig(), runs_dir=tmp_path / "runs")
    registry = runner._build_registry(
        TaskManager(tmp_path / "tasks"), session=session,
        provider=cast(Any, object()), bus=EventBus(), run_id="parent",
        child_runs_dir=tmp_path / "runs", session_id=session.id,
    )
    parent_read = registry.get("read_file")
    assert parent_read is not None
    assert (await parent_read.invoke({"path": "input.txt"})).content == "child content"

    spawn = registry.get("spawn_agent")
    assert isinstance(spawn, SpawnAgentTool)
    child = spawn._build_child_registry(EventBus(), "child", None)
    child_read = child.get("read_file")
    assert child_read is not None
    assert (await child_read.invoke({"path": "input.txt"})).content == "child content"
    nested_spawn = child.get("spawn_agent")
    assert isinstance(nested_spawn, SpawnAgentTool)
    nested = nested_spawn._build_child_registry(EventBus(), "grandchild", None)
    nested_read = nested.get("read_file")
    assert nested_read is not None
    assert (await nested_read.invoke({"path": "input.txt"})).content == "child content"


async def test_sessionless_off_tool_keeps_process_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "local.txt").write_text("process cwd", encoding="utf-8")
    assert (await ReadFileTool().invoke({"path": "local.txt"})).content == "process cwd"


async def test_off_child_profile_uses_selected_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "chosen"
    profile_dir = workspace / ".flora" / "agents"
    profile_dir.mkdir(parents=True)
    (profile_dir / "custom.toml").write_text(
        '[agent]\nsystem_prompt = "selected profile"\n', encoding="utf-8"
    )
    daemon_cwd = tmp_path / "daemon"
    other_profile = daemon_cwd / ".flora" / "agents"
    other_profile.mkdir(parents=True)
    (other_profile / "custom.toml").write_text(
        '[agent]\nsystem_prompt = "wrong profile"\n', encoding="utf-8"
    )
    monkeypatch.chdir(daemon_cwd)

    class Provider:
        def __init__(self) -> None:
            self.system: str | None = None

        async def chat(
            self, messages, tool_schemas, bus, run_id, *, step=0, system=None,
        ) -> LlmResponse:
            self.system = system
            return LlmResponse(stop_reason="end_turn", text="done")

    provider = Provider()
    spawn = SpawnAgentTool(
        provider=cast(Any, provider), parent_bus=EventBus(), parent_run_id="parent",
        permission_manager=None, max_steps=2,
        task_registry=BackgroundTaskRegistry(),
        runs_dir=tmp_path / "runs", session_id="sess-off",
        host_workspace_root=workspace,
    )
    result = await spawn.invoke({
        "description": "profile lookup", "prompt": "hello", "subagent_type": "custom"
    })
    assert not result.is_error
    assert provider.system is not None
    assert "selected profile" in provider.system
    assert "wrong profile" not in provider.system
