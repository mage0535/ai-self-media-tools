"""Compile selected Hermes/project skill rules into bounded model context."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def compile_skill_rules(paths: list[str | Path], *, root: str | Path) -> dict[str, Any]:
    root = Path(root).resolve()
    sources = []
    rules = []
    for raw_path in paths:
        path = Path(raw_path)
        relative = _relative(path, root)
        if any(part.casefold() in {".archive", "_archive", "archive"} for part in relative.split("/")):
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rule_path = relative.removeprefix("skills/").removesuffix("/SKILL.md")
        source_id = f"skill:{rule_path}"
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        sources.append({"id": source_id, "path": relative, "sha256": source_hash})
        section = "root"
        index = 0
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                section = stripped.lstrip("#").strip()[:100] or "root"
                continue
            match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", stripped)
            if not match or len(match.group(1)) < 8:
                continue
            index += 1
            rules.append({
                "id": f"{source_id}:{index}",
                "source": source_id,
                "section": section,
                "text": match.group(1)[:500],
            })
    return {
        "version": "compiled_skill_rules_v1",
        "passed": True,
        "sources": sources,
        "rules": rules[:120],
        "rule_count": min(len(rules), 120),
    }


def default_skill_paths(platform: str, *, root: str | Path) -> list[Path]:
    root = Path(root)
    names = ["channel-operations-workflow", "visual-quality-standards"]
    platform_name = {
        "wechat": "wechat-full-workflow",
        "douyin_ai": "douyin-daily-analysis-workflow",
        "douyin_pet": "douyin-repost-workflow",
        "xiaohongshu": "xiaohongshu-content-enhancer",
        "zhihu": "zhihu-publishing-workflow",
        "juejin": "juejin-publishing-workflow",
        "kuaishou": "kuaishou-publishing-workflow",
        "tiktok": "intl-short-video-pipeline",
        "youtube": "intl-short-video-pipeline",
    }.get(str(platform).casefold())
    if platform_name:
        names.append(platform_name)
    return [root / "skills" / "content" / name / "SKILL.md" for name in names]
