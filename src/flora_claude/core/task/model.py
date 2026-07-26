from __future__ import annotations

from typing import Literal, Any
from dataclasses import dataclass

TaskStatus = Literal["pending", "in_progress", "completed"]

@dataclass
class Task:
    id: int
    subject: str
    description: str
    status: TaskStatus
    blocked_by: list[int]
    created_at: str
    updated_at: str

    # 序列化为 dict，字段名与 JSON 文件格式一致
    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # 从 dict 生成构造 cls
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls(
            id=int(data.get("id")),
            subject=str(data.get("subject")),
            description=str(data.get("description")),
            status=data.get("status", "pending"),
            blocked_by=[int(x) for x in data.get("blocked_by", [])],
            created_at=str(data.get("created_at")),
            updated_at=str(data.get("updated_at"))
        )