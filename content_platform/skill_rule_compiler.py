"""Compile selected Hermes/project skill rules into bounded model context."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


_BLOCKED_SKILL_TOKENS = frozenset({
    ".archive", "_archive", "archive", "duplicate", "duplicates", "finance", "financial",
    "trading", "trade", "stock", "stocks", "forex", "crypto", "investment", "investing",
})
_PLATFORMS = frozenset({"douyin", "xiaohongshu", "zhihu", "juejin", "wechat", "kuaishou", "tiktok", "youtube"})


def _blocked_skill(relative: str) -> bool:
    lowered = relative.casefold().replace("\\", "/")
    parts = set(lowered.split("/"))
    return any(part in _BLOCKED_SKILL_TOKENS or any(token in part for token in _BLOCKED_SKILL_TOKENS if token not in {".archive", "_archive"}) for part in parts)


def _source_platforms(source: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", source.casefold()))
    return tokens.intersection(_PLATFORMS)


def select_platform_rules(rules: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    """Keep shared content rules and rules named for the active platform only."""
    active = str(platform or "").casefold()
    active_names = {active.removesuffix("_ai").removesuffix("_pet")}
    if active in {"douyin_ai", "douyin_pet"}:
        active_names.add("douyin")
    selected = []
    seen_text_hashes: set[str] = set()
    candidates = sorted(
        (item for item in rules if isinstance(item, dict)),
        key=lambda item: (
            0 if _source_platforms(str(item.get("source") or item.get("id") or "").casefold()).intersection(active_names) else
            1 if "project" in str(item.get("source") or "").casefold() else 2,
            str(item.get("source") or ""),
            str(item.get("id") or ""),
        ),
    )
    for rule in candidates:
        source = str(rule.get("source") or rule.get("id") or "").casefold()
        if _blocked_skill(source):
            continue
        named_platforms = _source_platforms(source)
        if named_platforms and not named_platforms.intersection(active_names):
            continue
        normalized_text = " ".join(str(rule.get("text") or "").split()).casefold()
        if not normalized_text:
            continue
        text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if text_hash in seen_text_hashes:
            continue
        seen_text_hashes.add(text_hash)
        selected.append(rule)
    return selected


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        hermes_root = _hermes_root(root).resolve()
        try:
            return "hermes/" + path.resolve().relative_to(hermes_root).as_posix()
        except ValueError:
            return "external/" + path.name


def _hermes_root(fallback_root: Path | None = None) -> Path:
    configured = os.environ.get("HERMES_HOME") or os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if configured:
        return Path(configured) / ".hermes" if not os.environ.get("HERMES_HOME") else Path(configured)
    return (fallback_root or Path.cwd()) / ".hermes"


def compile_skill_rules(paths: list[str | Path], *, root: str | Path, platform: str = "") -> dict[str, Any]:
    root = Path(root).resolve()
    sources = []
    rules = []
    records = []
    for raw_path in paths:
        path = Path(raw_path)
        relative = _relative(path, root)
        if _blocked_skill(relative) or "skills/content/" not in relative.casefold():
            continue
        if not path.is_file():
            continue
        records.append((relative, path))
    for relative, path in sorted(records, key=lambda item: item[0].casefold()):
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
    result = {
        "version": "compiled_skill_rules_v1",
        "passed": True,
        "sources": sources,
        "rules": sorted(rules[:120], key=lambda item: str(item.get("id") or "")),
        "rule_count": min(len(rules), 120),
    }
    if platform:
        from .adapter_executor import execute_capability
        from .capability_catalog import load_capability_registry

        capability = next(
            item for item in load_capability_registry()["capabilities"] if item["id"] == "skill_reference_compiler"
        )
        result["consultation"] = execute_capability(
            capability,
            {
                "platform": platform,
                "compiled_skill_rules": result,
                "affected_outputs": ["generation_context", "provider_brief"],
            },
        )
    return result


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
    paths = [root / "skills" / "content" / name / "SKILL.md" for name in names]
    hermes_root = _hermes_root(root)
    paths.extend(hermes_root / "skills" / "content" / name / "SKILL.md" for name in names)
    return list(dict.fromkeys(path for path in paths if path.is_file()))
