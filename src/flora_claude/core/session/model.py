from __future__ import annotations

from dataclasses import field, dataclass
from pathlib import Path
from typing import Any, Literal


SessionStatus = Literal["active", "waiting_for_input", "closed"]
SessionMode = Literal["one_shot", "chat"]
SandboxMode = Literal["off", "read_only", "workspace_write"]


@dataclass
class Session:
    id: str
    mode: SessionMode
    status: SessionStatus
    title: str
    created_at: str
    updated_at: str
    run_ids: list[str] = field(default_factory=list)
    workspace_root: str = field(default_factory=lambda: str(Path.cwd().resolve()))
    sandbox_mode: SandboxMode = "off"

    # 将 session 转化为可写入 meta.json 的普通dict
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "status": self.status,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_ids": list(self.run_ids),
            "workspace_root": self.workspace_root,
            "sandbox_mode": self.sandbox_mode,
        }

    # 从 meta.json 中还原 session 对象
    @classmethod
    def from_dict(cls,data: dict[str, Any]) -> Session:
        return cls(
            id=str(data['id']),
            mode=data["mode"],
            status=data["status"],
            title=str(data.get("title", "")),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            run_ids=[str(x) for x in data.get("run_ids", [])],
            workspace_root=str(data.get("workspace_root") or Path.cwd().resolve()),
            sandbox_mode=data.get("sandbox_mode", "off"),
        )
