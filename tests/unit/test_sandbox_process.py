from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from flora_claude.core.sandbox.runtime import SandboxExecutor


async def test_docker_cli_argv_stdin_output_and_cleanup_use_real_subprocess(
    tmp_path: Path, monkeypatch,
) -> None:
    """Exercise the Docker command boundary with a separate fake CLI process."""
    script = tmp_path / "fake_docker.py"
    log = tmp_path / "docker-calls.jsonl"
    script.write_text(
        """
import json, os, sys
args = sys.argv[1:]
payload = sys.stdin.buffer.read().decode('utf-8', 'replace')
with open(os.environ['FAKE_DOCKER_LOG'], 'a', encoding='utf-8') as out:
    out.write(json.dumps({'args': args, 'stdin': payload}) + '\\n')
if args[0] == 'run':
    print('container-id')
elif args[0] == 'exec':
    if args[-1] == 'fail':
        print('expected failure')
        sys.exit(4)
    print('exec-ok')
elif args[0] == 'rm':
    print('removed')
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    real_create = asyncio.create_subprocess_exec

    async def fake_docker_process(*args: str, **kwargs):
        assert args[0] == "docker"
        return await real_create(sys.executable, str(script), *args[1:], **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_docker_process)
    executor = SandboxExecutor(tmp_path, "workspace_write")

    ok = await executor.bash("echo ok", 5)
    failed = await executor.bash("fail", 5)
    written = await executor.write_file("a.txt", "payload")
    await executor.close()

    assert ok.content.strip() == "exec-ok"
    assert failed.error_type == "command_failed"
    assert "expected failure" in failed.content
    assert not written.is_error
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [call["args"][0] for call in calls] == ["run", "exec", "exec", "exec", "rm"]
    run_args = calls[0]["args"]
    assert "--network=none" in run_args
    assert "--read-only" in run_args
    assert "--mount" in run_args
    assert str(tmp_path) in run_args[run_args.index("--mount") + 1]
    assert calls[3]["stdin"] == "payload"
    assert calls[-1]["args"][1] == "--force"
