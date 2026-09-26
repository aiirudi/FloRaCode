from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from flora_claude.core.sandbox.runtime import SandboxExecutor


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        engine = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5, check=False
        )
        image = subprocess.run(
            ["docker", "image", "inspect", "python:3.12-alpine"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return engine.returncode == 0 and image.returncode == 0


@pytest.mark.integration
async def test_real_docker_workspace_boundary(tmp_path: Path) -> None:
    if not _docker_ready():
        pytest.skip("Docker engine or python:3.12-alpine image is unavailable")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("hello", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    writable = SandboxExecutor(workspace, "workspace_write")
    readonly = SandboxExecutor(workspace, "read_only")
    try:
        assert (await writable.read_file("input.txt")).content == "hello"
        assert not (await writable.write_file("nested/output.txt", "written")).is_error
        assert (workspace / "nested/output.txt").read_text(encoding="utf-8") == "written"
        assert "output.txt" in (await writable.list_dir("nested", 2)).content
        assert (await writable.read_file("../outside.txt")).error_type == "sandbox_denied"
        assert (await writable.read_file(str(outside))).error_type == "sandbox_denied"
        assert not (await writable.bash("ln -s /etc/passwd /workspace/escape.txt", 5)).is_error
        assert (await writable.read_file("escape.txt")).error_type == "sandbox_denied"
        network = await writable.bash(
            "python -c \"import socket; socket.create_connection(('1.1.1.1', 80), 1)\"",
            5,
        )
        assert network.error_type == "command_failed"
        assert (await readonly.read_file("input.txt")).content == "hello"
        assert (await readonly.write_file("blocked.txt", "x")).error_type == "sandbox_denied"
    finally:
        name = writable._name
        readonly_name = readonly._name
        await writable.close()
        await readonly.close()

    for container_name in (name, readonly_name):
        result = subprocess.run(
            ["docker", "inspect", container_name], capture_output=True, timeout=5, check=False
        )
        assert result.returncode != 0
