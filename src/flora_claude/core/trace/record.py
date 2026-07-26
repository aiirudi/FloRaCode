from __future__ import annotations

from typing import Literal, Any

from pydantic import BaseModel

class TraceRecord(BaseModel):
    ts: str
    direction:Literal[
        "CLIENT->CORE",
        "CORE->CLIENT",
        "CORE",
        "CORE->LLM",
        "LLM->CORE"
    ]
    layer: Literal["ipc", "event", "llm"]
    kind: str
    client_id: str | None = None
    run_id: str | None = None
    step: int | None = None
    data: dict[str, Any]

