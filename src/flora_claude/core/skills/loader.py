from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flora_claude.core.session.model import SandboxMode

@dataclass
class Skill:
    name: str
    description: str
    system_prompt_template: str
    allowed_tools: list[str] = field(default_factory=list)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# 解析 Markdown skill 文件，提取 frontmatter 和正文 system prompt
def _parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    name = path.stem
    description = ""
    allowed_tools: list[str] = []
    body = text

    m = _FRONTMATTER_RE.match(text)
    if m:
        front = m.group(1)
        body = text[m.end():]
        lines = front.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if stripped.startswith("name:"):
                name = stripped[len("name:"):].strip().strip('"').strip("'")
            elif stripped.startswith("description:"):
                val = stripped[len("description:"):].strip().strip('"').strip("'")
                if val in (">", "|"):
                    fold = val == ">"
                    parts: list[str] = []
                    i += 1
                    while i < len(lines) and (lines[i].startswith("\t") or lines[i].startswith(" ")):
                        parts.append(lines[i].strip())
                        i += 1
                    description = (" ".join(parts) if fold else "\n".join(parts)).strip()
                    continue
                else:
                    description = val
            elif stripped.startswith("allowed_tools:"):
                pass
            elif stripped.startswith("- "):
                allowed_tools.append(stripped[2:].strip())
            i += 1
    return Skill(
        name=name,
        description=description,
        system_prompt_template=body.strip(),
        allowed_tools=allowed_tools,
    )

class SkillLoader:
    _BUILTIN_DIR = Path(__file__).parent / "builtin"
    dirs = [
        _BUILTIN_DIR,
        Path("~/.flora/skills").expanduser(),
        Path(".flora/skills"),
    ]

    # 按优先级查找 skill 文件；未找到返回 None
    def resolve(self, name: str, workspace_root: Path | None = None,
                sandbox_mode: SandboxMode = "off") -> Skill | None:
        if _SAFE_NAME_RE.fullmatch(name) is None:
            return None
        for path in self._search_paths(name, workspace_root, sandbox_mode):
            if path.exists():
                try:
                    return _parse_skill_file(path)
                except Exception:
                    return None
        return None

    # 返回候选路径列表，同时支持扁平文件（name.md）和目录式（name/SKILL.md）两种格式
    def _search_paths(self, name: str, workspace_root: Path | None = None,
                      sandbox_mode: SandboxMode = "off") -> list[Path]:
        project_root = workspace_root if workspace_root is not None else Path.cwd()
        dirs = [
            project_root / ".flora" / "skills",
            Path("~/.flora/skills").expanduser(),
            self._BUILTIN_DIR,
        ]
        paths: list[Path] = []
        for index, d in enumerate(dirs):
            for path in (d / f"{name}.md", d / name / "SKILL.md"):
                if index == 0 and sandbox_mode != "off":
                    # Project skills are untrusted files within the workspace mount.
                    # A junction or symlink must not redirect a read outside it.
                    if not self._within_workspace(path, project_root):
                        continue
                paths.append(path)
        return paths

    # 列出所有可用 skill 名称（内建 + 用户全局 + 项目本地，去重后以项目本地覆盖为准）
    def list_all(self, workspace_root: Path | None = None,
                 sandbox_mode: SandboxMode = "off") -> list[str]:
        seen: dict[str, None] = {}
        for index, d in enumerate(self._listing_dirs(workspace_root)):
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    if index == 2 and sandbox_mode != "off" and not self._within_workspace(f, workspace_root):
                        continue
                    seen[f.stem] = None
                for f in sorted(d.glob("*/SKILL.md")):
                    if index == 2 and sandbox_mode != "off" and not self._within_workspace(f, workspace_root):
                        continue
                    seen[f.parent.name] = None
        return list(seen)

    # 列出所有可用 Skill 对象（含描述），项目本地覆盖同名内建
    def list_all_skills(self, workspace_root: Path | None = None,
                        sandbox_mode: SandboxMode = "off") -> list[Skill]:
        seen: dict[str, Skill] = {}
        for index, d in enumerate(self._listing_dirs(workspace_root)):
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    if index == 2 and sandbox_mode != "off" and not self._within_workspace(f, workspace_root):
                        continue
                    try:
                        skill = _parse_skill_file(f)
                        seen[skill.name] = skill
                    except Exception:
                        pass

                for f in sorted(d.glob("*/SKILL.md")):
                    if index == 2 and sandbox_mode != "off" and not self._within_workspace(f, workspace_root):
                        continue
                    try:
                        skill = _parse_skill_file(f)
                        seen[skill.name] = skill
                    except Exception:
                        pass
        return list(seen.values())

    @staticmethod
    def _within_workspace(path: Path, workspace_root: Path | None) -> bool:
        root = workspace_root if workspace_root is not None else Path.cwd()
        try:
            return path.resolve().is_relative_to(root.resolve())
        except (OSError, RuntimeError):
            return False

    def _listing_dirs(self, workspace_root: Path | None) -> list[Path]:
        return [
            self._BUILTIN_DIR,
            Path("~/.flora/skills").expanduser(),
            (workspace_root if workspace_root is not None else Path.cwd()) / ".flora" / "skills",
        ]

    # 将 $ARGUMENTS 替换为用户传入的参数字符串
    def render_prompt(self, skill: Skill, arguments: str):
        return skill.system_prompt_template.replace("$ARGUMENTS", arguments)
