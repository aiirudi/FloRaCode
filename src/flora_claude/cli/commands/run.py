from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from flora_claude.core.config import FloRaConfig
from flora_claude.core.transport.socket_client import IpcError, SocketClient

_DECISION_MAP = {"y": "allow_once", "a": "always_allow", "n": "deny_once", "d": "always_deny"}


async def _readline(prompt: str) -> str:
    """Read terminal input without blocking the socket loop or shutdown."""
    loop = asyncio.get_running_loop()
    result: asyncio.Future[str] = loop.create_future()

    def read() -> None:
        try:
            value = input(prompt)
        except (EOFError, KeyboardInterrupt):
            value = "n"
        try:
            def finish() -> None:
                if not result.done():
                    result.set_result(value)

            loop.call_soon_threadsafe(finish)
        except RuntimeError:
            pass

    threading.Thread(target=read, daemon=True).start()
    return await result


class StdoutPrinter:

    # 将运行进度格式化打印到
    def __init__(self) -> None:
        # 当 LLM 正在输出时为真，避免要 agent 要进行工具调用的时候在中间输出
        self._inline = False
        self._run_start: float = 0.0

    def _ensure_newline(self) -> None:
        if self._inline:
            print()
            self._inline = False
        
    async def handle(self, event: dict[str, Any]) -> None:
        type = event.get("type", "")
        
        if type == "run.started":
            self._run_start = time.monotonic()
            print(f"[run] {event.get("run_id", "")}")
        
        elif type == "step.started":
            self._ensure_newline()
            print(f"[step {event.get("step")}] planning ...")

        elif type == "llm.token":
            print(event.get("token", ""), end="", flush=True)
            self._inline = True
        
        elif type == "tool.call_started":
            self._ensure_newline()
            params_str = json.dumps(event.get("params"), ensure_ascii=False)
            print(f"[tool] {event.get("tool_name", "")} {params_str}")
        
        elif type == "tool.call_finished":
            print(f"[tool] {event.get("tool_name", "")} ✓  {event.get("elapsed_ms")}ms")
    
        elif type == "tool.call_failed":
            print(
                f"[tool] {event.get("tool_name", "")}✗  {event.get("error_message", "")}",
                file=sys.stderr
            )
        
        elif type == "step.finished":
            self._ensure_newline()
            print(f"[step {event.get("step")}] done")
        
        elif type == "run.finished":
            self._ensure_newline()
            elapsed = time.monotonic() - self._run_start
            print(
                f"[run] {event.get('status', '')}  {event.get('steps', '')} "
                f"steps  {elapsed:.1f}s"
            )

# 异步核心：连接 daemon, 订阅事件，触发run，等待 run.finished
async def _run_async(goal: str, config: FloRaConfig) -> int:
    workspace_root = str(Path.cwd().resolve())
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionRefusedError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file=sys.stderr)
        return 1

    printer = StdoutPrinter()
    finished = asyncio.Event()
    exit_code = 0
    run_id: str | None = None
    early_events: list[dict[str, Any]] = []
    permission_tasks: set[asyncio.Task[None]] = set()

    async def respond_to_permission(event: dict[str, Any]) -> None:
        tool_use_id = str(event.get("tool_use_id", ""))
        print(f"[permission] {event.get('tool_name', '')} {event.get('param_preview', '')}")
        print("  y=allow once  a=always allow  n=deny once  d=always deny")
        while True:
            decision = _DECISION_MAP.get((await _readline("permission> ")).strip().lower())
            if decision is not None:
                break
            print("enter y, a, n, or d")
        try:
            await client.send_command(
                "permission.respond", {"tool_use_id": tool_use_id, "decision": decision}
            )
        except IpcError as exc:
            print(f"error: {exc}", file=sys.stderr)

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal exit_code
        if run_id is None:
            early_events.append(event)
            return
        if event.get("run_id") != run_id:
            return
        if event.get("type") == "permission.requested":
            task = asyncio.create_task(respond_to_permission(event))
            permission_tasks.add(task)
            task.add_done_callback(permission_tasks.discard)
            return
        await printer.handle(event)
        if event.get("type") == "run.finished":
            if event.get("status") != "success":
                exit_code = 1
            finished.set()
    
    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    try:
        await client.send_command(
            "event.subscribe",
            {
                "topics": [
                    "run.*", "step.*", "tool.*", "llm.token", "llm.usage",
                    "permission.*",
                ],
                "scope": "global",
            }
        )
        created = await client.send_command(
            "agent.run",
            {
                "goal": goal,
                "workspace_root": workspace_root,
                "sandbox_mode": config.sandbox.default_mode,
            }
        )
        run_id = str(created["run_id"])
        active_root = created.get("workspace_root", workspace_root)
        active_mode = created.get("sandbox_mode", config.sandbox.default_mode)
        print(f"[workspace] {active_root}  sandbox={active_mode}")
        for event in early_events:
            await on_event(event)
        early_events.clear()

    except IpcError as e:
        print(f"error: {e}", file=sys.stderr)
        loop_task.cancel()
        await client.close()
        return 1
    
    await finished.wait()

    for task in permission_tasks:
        task.cancel()

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    await client.close()
    return exit_code


def cmd_run(goal: str, config: FloRaConfig) -> None:
    try:
        exit_code = asyncio.run(_run_async(goal, config))
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(exit_code)
