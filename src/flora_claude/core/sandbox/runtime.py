"""A session-scoped, lazily started Docker sandbox for built-in tools."""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from flora_claude.core.tools.base import ToolResult

if TYPE_CHECKING:
    from flora_claude.core.session.model import SandboxMode

_WORKDIR = "/workspace"
_MAX_OUTPUT_BYTES = 64 * 1024
_MAX_READ_BYTES = 512 * 1024
_MAX_WRITE_BYTES = 1024 * 1024
_MAX_ENTRIES = 200
_START_TIMEOUT = 30
_STOP_TIMEOUT = 10

_READ_SCRIPT = r'''
import pathlib, sys
root = pathlib.Path('/workspace')
p = (root / sys.argv[1]).resolve()
if not p.is_relative_to(root):
    print('path escapes workspace', file=sys.stderr); sys.exit(77)
with p.open('rb') as f: data = f.read(524289)
sys.stdout.buffer.write(data[:524288])
if len(data) > 524288: sys.stdout.buffer.write(b'\n[truncated]')
'''

_WRITE_SCRIPT = r'''
import pathlib, sys
root = pathlib.Path('/workspace')
p = root / sys.argv[1]
if not p.resolve().is_relative_to(root):
    print('path escapes workspace', file=sys.stderr); sys.exit(77)
p.parent.mkdir(parents=True, exist_ok=True)
if not p.parent.resolve().is_relative_to(root):
    print('path escapes workspace', file=sys.stderr); sys.exit(77)
data = sys.stdin.buffer.read(1048577)
if len(data) > 1048576:
    print('content too large', file=sys.stderr); sys.exit(77)
p.write_bytes(data)
print(f'wrote {len(data)} bytes to {sys.argv[1]}')
'''

_LIST_SCRIPT = r'''
import pathlib, sys
root = pathlib.Path('/workspace')
path = root / sys.argv[1]
if not path.resolve().is_relative_to(root):
    print('path escapes workspace', file=sys.stderr); sys.exit(77)
if not path.exists(): raise FileNotFoundError(sys.argv[1])
if not path.is_dir(): raise NotADirectoryError(sys.argv[1])
limit = int(sys.argv[2]); lines = [sys.argv[1].rstrip('/') + '/']; count = 0
def walk(directory, depth, prefix):
    global count
    if depth > limit or count >= 200: return
    entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name))
    for i, entry in enumerate(entries):
        if count >= 200:
            lines.append(prefix + '... (truncated)'); return
        last = i == len(entries) - 1
        is_dir = entry.is_dir()
        lines.append(prefix + ('└── ' if last else '├── ') + entry.name + ('/' if is_dir else ''))
        count += 1
        if is_dir and depth < limit and entry.resolve().is_relative_to(root):
            walk(entry, depth + 1, prefix + ('    ' if last else '│   '))
walk(path, 1, '')
print('\n'.join(lines))
'''


def _error(message: str, kind: str) -> ToolResult:
    return ToolResult(content=message, is_error=True, error_type=kind)


class SandboxExecutor:
    """One persistent container per session; Docker is touched only by tool calls."""

    def __init__(
        self,
        workspace_root: Path,
        mode: SandboxMode,
        image: str = "python:3.12-alpine",
    ) -> None:
        if mode not in ("off", "read_only", "workspace_write"):
            raise ValueError(f"invalid sandbox mode: {mode}")
        if not image or image.startswith("-"):
            raise ValueError("invalid sandbox image")
        self.workspace_root = Path(workspace_root).resolve()
        self.mode = mode
        self.image = image
        self._name = f"flora-sandbox-{uuid.uuid4().hex}"
        self._started = False
        self._may_exist = False
        self._closed = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _check_path(path: str) -> ToolResult | None:
        if not path or "\x00" in path or "\\" in path or ":" in path:
            return _error("path must be relative to the workspace", "sandbox_denied")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts:
            return _error("path must stay inside the workspace", "sandbox_denied")
        return None

    async def _docker(
        self, *args: str, stdin: bytes | None = None, timeout: float = _START_TIMEOUT,
        capture_limit: int = _MAX_OUTPUT_BYTES + 1,
    ) -> tuple[int, bytes]:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async def collect() -> bytes:
            async def feed() -> None:
                if stdin is None:
                    return
                assert proc.stdin is not None
                try:
                    proc.stdin.write(stdin)
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()

            async def drain() -> bytes:
                assert proc.stdout is not None
                captured = bytearray()
                while chunk := await proc.stdout.read(65536):
                    remaining = capture_limit - len(captured)
                    if remaining > 0:
                        captured.extend(chunk[:remaining])
                return bytes(captured)

            _, output = await asyncio.gather(feed(), drain())
            await proc.wait()
            return output

        try:
            output = await asyncio.wait_for(collect(), timeout=timeout)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2)
            raise
        return proc.returncode or 0, output

    async def _remove(self) -> bool:
        try:
            code, output = await self._docker(
                "rm", "--force", self._name, timeout=_STOP_TIMEOUT,
                capture_limit=4096,
            )
        except (OSError, TimeoutError):
            self._started = False
            return False
        removed = code == 0 or b"No such container" in output
        self._started = False
        self._may_exist = not removed
        return removed

    async def _start(self) -> ToolResult | None:
        if self._started:
            return None
        if self._may_exist and not await self._remove():
            return _error("previous sandbox container could not be removed", "sandbox_unavailable")
        if self.mode == "off":
            return _error("sandbox is disabled", "sandbox_denied")
        if not self.workspace_root.is_dir() or "," in str(self.workspace_root):
            return _error("sandbox workspace is unavailable", "sandbox_unavailable")
        mount = f"type=bind,source={self.workspace_root},target={_WORKDIR}"
        if self.mode == "read_only":
            mount += ",readonly"
        user = (
            f"{getattr(os, 'getuid')()}:{getattr(os, 'getgid')()}"
            if os.name == "posix" and self.mode == "workspace_write"
            else "65534:65534"
        )
        args = (
            "run", "--detach", "--rm", "--pull=never",
            "--name", self._name,
            "--network=none", "--read-only",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--cpus=1", "--memory=512m", "--memory-swap=512m",
            "--pids-limit=64", "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--user={user}", "--workdir=/workspace",
            "--mount", mount,
            "--entrypoint=/bin/sh", self.image,
            "-c", "while :; do sleep 3600; done",
        )
        self._may_exist = True
        try:
            code, output = await self._docker(*args, capture_limit=4096)
        except asyncio.CancelledError:
            await self._remove()
            raise
        except (FileNotFoundError, OSError, TimeoutError) as exc:
            await self._remove()
            return _error(f"Docker sandbox unavailable: {exc}", "sandbox_unavailable")
        if code:
            await self._remove()
            detail = output.decode("utf-8", "replace").strip()
            if "No such image" in detail or "pull access denied" in detail:
                detail += f". Install the sandbox image with: docker pull {self.image}"
            return _error(
                f"Docker sandbox unavailable: {detail}",
                "sandbox_unavailable",
            )
        self._started = True
        return None

    async def _exec(
        self, argv: tuple[str, ...], *, stdin: bytes | None = None,
        timeout: float = 60, output_limit: int = _MAX_OUTPUT_BYTES,
        helper: bool = False,
    ) -> ToolResult:
        async with self._lock:
            if self._closed:
                return _error("sandbox executor is closed", "sandbox_unavailable")
            start_error = await self._start()
            if start_error is not None:
                return start_error
            try:
                code, raw = await self._docker(
                    "exec", "--interactive", self._name, *argv,
                    stdin=stdin or b"", timeout=timeout,
                    capture_limit=output_limit + 1,
                )
            except TimeoutError:
                await self._remove()
                return _error(f"[timeout after {timeout}s]", "timeout")
            except asyncio.CancelledError:
                await self._remove()
                raise
            except (FileNotFoundError, OSError) as exc:
                await self._remove()
                return _error(f"Docker sandbox unavailable: {exc}", "sandbox_unavailable")
            output = raw[:output_limit].decode("utf-8", "replace")
            if len(raw) > output_limit:
                output += "\n[truncated]"
            if helper and code == 77:
                return _error(output.strip(), "sandbox_denied")
            if code:
                if raw.startswith((
                    b"Error response from daemon:",
                    b"Cannot connect to the Docker daemon",
                    b"docker: Error response from daemon:",
                )):
                    await self._remove()
                    return _error(output.strip(), "sandbox_unavailable")
                return _error(f"[exit {code}]\n{output}", "command_failed")
            return ToolResult(content=output or "[no output]")

    async def bash(self, command: str, timeout: int) -> ToolResult:
        if self._closed:
            return _error("sandbox executor is closed", "sandbox_unavailable")
        return await self._exec(("/bin/sh", "-c", command), timeout=timeout)

    async def read_file(self, path: str) -> ToolResult:
        if self._closed:
            return _error("sandbox executor is closed", "sandbox_unavailable")
        if error := self._check_path(path):
            return error
        return await self._exec(
            ("python", "-I", "-B", "-c", _READ_SCRIPT, path),
            output_limit=_MAX_READ_BYTES + 32,
            helper=True,
        )

    async def write_file(self, path: str, content: str) -> ToolResult:
        if self._closed:
            return _error("sandbox executor is closed", "sandbox_unavailable")
        if self.mode != "workspace_write":
            return _error("sandbox is read-only", "sandbox_denied")
        if error := self._check_path(path):
            return error
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_WRITE_BYTES:
            return _error(
                f"content too large: {len(encoded)} bytes (limit 1 MB)",
                "sandbox_denied",
            )
        return await self._exec(
            ("python", "-I", "-B", "-c", _WRITE_SCRIPT, path),
            stdin=encoded,
            helper=True,
        )

    async def list_dir(self, path: str, max_depth: int) -> ToolResult:
        if self._closed:
            return _error("sandbox executor is closed", "sandbox_unavailable")
        if error := self._check_path(path):
            return error
        if not 1 <= max_depth <= 4:
            return _error("max_depth must be between 1 and 4", "sandbox_denied")
        return await self._exec(
            ("python", "-I", "-B", "-c", _LIST_SCRIPT, path, str(max_depth)),
            output_limit=_MAX_ENTRIES * 1024,
            helper=True,
        )

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            if self._may_exist:
                await self._remove()


class SandboxPool:
    def __init__(self, image: str = "python:3.12-alpine") -> None:
        self.image = image
        self._executors: dict[str, SandboxExecutor] = {}

    def get(
        self, session_id: str, workspace_root: Path, mode: SandboxMode
    ) -> SandboxExecutor:
        existing = self._executors.get(session_id)
        if existing is not None:
            if existing.workspace_root != Path(workspace_root).resolve() or existing.mode != mode:
                raise ValueError("sandbox configuration changed for an active session")
            return existing
        executor = SandboxExecutor(workspace_root, mode, self.image)
        self._executors[session_id] = executor
        return executor

    async def close(self, session_id: str) -> None:
        executor = self._executors.pop(session_id, None)
        if executor is not None:
            await executor.close()

    async def close_all(self) -> None:
        executors = list(self._executors.values())
        self._executors.clear()
        for executor in executors:
            await executor.close()
