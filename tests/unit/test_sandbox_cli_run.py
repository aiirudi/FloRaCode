from __future__ import annotations

import asyncio
import importlib
from typing import Any

from flora_claude.core.config import FloRaConfig


async def test_one_shot_run_subscribes_and_answers_permission(monkeypatch) -> None:
    run_module = importlib.import_module("flora_claude.cli.commands.run")

    class FakeClient:
        def __init__(self) -> None:
            self.handler = None
            self.subscription: dict[str, Any] | None = None
            self.decision: dict[str, Any] | None = None

        async def connect(self) -> None:
            pass

        async def close(self) -> None:
            pass

        def on_event(self, handler) -> None:
            self.handler = handler

        async def run_event_loop(self) -> None:
            await asyncio.Event().wait()

        async def send_command(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            if method == "event.subscribe":
                self.subscription = params
                return {"subscription_id": "test"}
            if method == "agent.run":
                async def request_permission() -> None:
                    await asyncio.sleep(0)
                    assert self.handler is not None
                    await self.handler({
                        "type": "permission.requested", "run_id": "run-test",
                        "tool_use_id": "tool-test", "tool_name": "bash",
                        "param_preview": "command='pwd'",
                    })

                asyncio.create_task(request_permission())
                return {
                    "run_id": "run-test", "workspace_root": params["workspace_root"],
                    "sandbox_mode": params["sandbox_mode"],
                }
            if method == "permission.respond":
                self.decision = params
                assert self.handler is not None
                await self.handler({
                    "type": "run.finished", "run_id": "run-test",
                    "status": "success", "steps": 1,
                })
                return {"ok": True}
            raise AssertionError(method)

    fake = FakeClient()
    monkeypatch.setattr(run_module, "SocketClient", lambda *_args: fake)

    async def answer(_prompt: str) -> str:
        return "y"

    monkeypatch.setattr(run_module, "_readline", answer)
    result = await asyncio.wait_for(run_module._run_async("test", FloRaConfig()), 2)

    assert result == 0
    assert fake.subscription is not None
    assert "permission.*" in fake.subscription["topics"]
    assert fake.decision == {"tool_use_id": "tool-test", "decision": "allow_once"}
