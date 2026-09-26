from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from flora_claude.core.agents.loader import AgentProfileLoader
from flora_claude.core.events.bus import EventBus
from flora_claude.core.llm.types import ToolCallBlock
from flora_claude.core.sandbox.runtime import SandboxExecutor, SandboxPool
from flora_claude.core.tools.base import ToolResult
from flora_claude.core.tools.builtin.bash import BashTool
from flora_claude.core.tools.builtin.list_dir import ListDirTool
from flora_claude.core.tools.builtin.read_file import ReadFileTool
from flora_claude.core.tools.builtin.write_file import WriteFileTool
from flora_claude.core.tools.invocation import invoke_tool
from flora_claude.core.tools.registry import ToolRegistry


def test_pool_is_lazy_and_stable(tmp_path: Path) -> None:
    pool = SandboxPool()
    first = pool.get("session", tmp_path, "workspace_write")
    assert first is pool.get("session", tmp_path, "workspace_write")
    assert not first._started
    with pytest.raises(ValueError):
        pool.get("session", tmp_path, "read_only")


def test_profile_loader_uses_sandbox_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    daemon = tmp_path / "daemon"
    for root, description in ((workspace, "workspace"), (daemon, "daemon")):
        agents = root / ".flora" / "agents"
        agents.mkdir(parents=True)
        (agents / "custom.toml").write_text(
            f'[agent]\ndescription = "{description}"\nsystem_prompt = "prompt"\n',
            encoding="utf-8",
        )
    monkeypatch.chdir(daemon)
    profile = AgentProfileLoader().load("custom", workspace)
    assert profile is not None
    assert profile.description == "workspace"
    assert AgentProfileLoader().load("../custom", workspace) is None
    assert AgentProfileLoader().load("../custom") is None


def test_profile_loader_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    agents = workspace / ".flora" / "agents"
    agents.mkdir(parents=True)
    outside = tmp_path / "outside.toml"
    outside.write_text('[agent]\nsystem_prompt = "outside"\n', encoding="utf-8")
    try:
        (agents / "custom.toml").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    assert AgentProfileLoader().load("custom", workspace) is None


async def test_start_uses_restricted_container(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "read_only")
    executor._docker = AsyncMock(return_value=(0, b"container-id\n"))  # type: ignore[method-assign]
    result = await executor.bash("echo hello", 5)
    assert not result.is_error
    run_args = executor._docker.call_args_list[0].args
    assert run_args[0] == "run"
    for flag in (
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=64",
        "--memory=512m", "--cpus=1", "--pull=never",
    ):
        assert flag in run_args
    assert "readonly" in run_args[run_args.index("--mount") + 1]
    assert all("docker.sock" not in str(arg) for arg in run_args)
    exec_args = executor._docker.call_args_list[1].args
    assert exec_args[-3:] == ("/bin/sh", "-c", "echo hello")


async def test_read_only_and_traversal_fail_before_docker(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "read_only")
    executor._docker = AsyncMock()  # type: ignore[method-assign]
    assert (await executor.write_file("safe.txt", "x")).error_type == "sandbox_denied"
    assert (await executor.read_file("../secret")).error_type == "sandbox_denied"
    assert (await executor.list_dir("C:\\secret", 2)).error_type == "sandbox_denied"
    executor._docker.assert_not_called()


async def test_missing_docker_fails_closed(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(side_effect=FileNotFoundError("docker"))  # type: ignore[method-assign]
    result = await executor.bash("echo hello", 5)
    assert result.is_error
    assert result.error_type == "sandbox_unavailable"


async def test_missing_image_has_pull_instruction(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(125, b"No such image: python:3.12-alpine"), (1, b"No such container")]
    )
    result = await executor.bash("echo hello", 5)
    assert result.error_type == "sandbox_unavailable"
    assert "docker pull python:3.12-alpine" in result.content


async def test_timeout_removes_container(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, b"container-id"), TimeoutError(), (0, b"")]
    )
    result = await executor.bash("sleep 100", 1)
    assert result.error_type == "timeout"
    assert not executor._started
    assert executor._docker.call_args_list[-1].args[:2] == ("rm", "--force")


async def test_failed_cleanup_is_retried_on_close(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(  # type: ignore[method-assign]
        side_effect=[TimeoutError(), OSError("daemon stopped"), (0, b"removed")]
    )
    result = await executor.bash("echo hi", 1)
    assert result.error_type == "sandbox_unavailable"
    assert executor._may_exist
    await executor.close()
    assert not executor._may_exist
    assert executor._docker.call_args_list[-1].args[:2] == ("rm", "--force")


async def test_close_seals_executor_against_late_child_calls(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, b"container-id"), (0, b"hello"), (0, b"removed")]
    )
    assert not (await executor.bash("echo hello", 5)).is_error
    await executor.close()
    calls_after_close = executor._docker.await_count
    for result in (
        await executor.bash("echo late", 5),
        await executor.read_file("input.txt"),
        await executor.write_file("output.txt", "late"),
        await executor.list_dir(".", 1),
    ):
        assert result.error_type == "sandbox_unavailable"
        assert "closed" in result.content
    assert executor._docker.await_count == calls_after_close


async def test_bash_exit_77_is_command_failure(tmp_path: Path) -> None:
    executor = SandboxExecutor(tmp_path, "workspace_write")
    executor._docker = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(0, b"container-id"), (77, b"ordinary exit")]
    )
    result = await executor.bash("exit 77", 5)
    assert result.error_type == "command_failed"


async def test_tools_delegate_to_executor() -> None:
    executor = AsyncMock()
    executor.bash.return_value = ToolResult("bash")
    executor.read_file.return_value = ToolResult("read")
    executor.write_file.return_value = ToolResult("write")
    executor.list_dir.return_value = ToolResult("list")
    assert (await BashTool(executor).invoke({"command": "echo hi"})).content == "bash"
    assert (await ReadFileTool(executor).invoke({"path": "a.txt"})).content == "read"
    assert (await WriteFileTool(executor).invoke({"path": "a.txt", "content": "x"})).content == "write"
    assert (await ListDirTool(executor).invoke({"path": "."})).content == "list"
    executor.bash.assert_awaited_once_with("echo hi", 60)
    executor.read_file.assert_awaited_once_with("a.txt")
    executor.write_file.assert_awaited_once_with("a.txt", "x")
    executor.list_dir.assert_awaited_once_with(".", 2)


async def test_legacy_bash_nonzero_is_nonretryable() -> None:
    result = await BashTool().invoke({"command": "exit 2"})
    assert result.error_type == "command_failed"


@pytest.mark.parametrize(
    "error_type", ["sandbox_unavailable", "sandbox_denied", "command_failed", "timeout"]
)
async def test_sandbox_errors_are_not_retried(error_type: str) -> None:
    executor = AsyncMock()
    executor.bash.return_value = ToolResult("failed", is_error=True, error_type=error_type)
    registry = ToolRegistry()
    registry.register(BashTool(executor))
    result = await invoke_tool(
        registry,
        ToolCallBlock(id="call", name="bash", input={"command": "echo hi"}),
        EventBus(),
        run_id="run",
    )
    assert result.error_type == error_type
    executor.bash.assert_awaited_once()
