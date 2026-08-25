"""Compile selected Hermes/project skill rules into bounded model context."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .preflight_manifest import REQUIRED_SKILLS_BY_CHANNEL, required_workflow_skills


_BLOCKED_SKILL_TOKENS = frozenset({
    ".archive", "_archive", "archive", "duplicate", "duplicates", "finance", "financial",
    "trading", "trade", "stock", "stocks", "forex", "crypto", "investment", "investing",
})
_PLATFORMS = frozenset({
    "douyin", "xiaohongshu", "rednote", "zhihu", "juejin", "wechat", "kuaishou",
    "tiktok", "youtube", "bilibili", "shipinhao", "x", "twitter",
})


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
    allowed_sources = {f"skill:{name}" for name in required_workflow_skills(active)}
    selected_by_source: dict[str, list[dict[str, Any]]] = {}
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
        if named_platforms and source not in allowed_sources and not named_platforms.intersection(active_names):
            continue
        normalized_text = " ".join(str(rule.get("text") or "").split()).casefold()
        if not normalized_text:
            continue
        text_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        if text_hash in seen_text_hashes:
            continue
        seen_text_hashes.add(text_hash)
        selected_by_source.setdefault(source, []).append(rule)
    ordered_sources = sorted(
        selected_by_source,
        key=lambda source: (
            0 if source in allowed_sources else
            1 if _source_platforms(source).intersection(active_names) else
            2 if "project" in source else 3,
            source,
        ),
    )
    # Interleave sources so a verbose shared skill cannot consume the bounded
    # model-input budget before every required platform skill contributes.
    selected: list[dict[str, Any]] = []
    offset = 0
    while True:
        added = False
        for source in ordered_sources:
            rows = selected_by_source[source]
            if offset < len(rows):
                selected.append(rows[offset])
                added = True
        if not added:
            break
        offset += 1
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
        declared_sources = {f"skills/{name}/skill.md" for channel in REQUIRED_SKILLS_BY_CHANNEL for name in required_workflow_skills(channel)}
        normalized_relative = relative.casefold().removeprefix("hermes/")
        if _blocked_skill(relative) or (
            "skills/content/" not in normalized_relative
            and normalized_relative not in declared_sources
        ):
            continue
        if not path.is_file():
            continue
        records.append((relative, path))
    for relative, path in sorted(records, key=lambda item: item[0].casefold()):
        text = path.read_text(encoding="utf-8", errors="replace")
        rule_path = relative.removeprefix("hermes/").removeprefix("skills/").removesuffix("/SKILL.md")
        source_id = f"skill:{rule_path}"
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        sources.append({"id": source_id, "path": relative, "sha256": source_hash})
        section = "root"
        index = 0
        paragraph: list[str] = []
        in_frontmatter = False

        def add_rule(rule_text: str) -> None:
            nonlocal index
            normalized = " ".join(rule_text.split())
            if len(normalized) < 8:
                return
            index += 1
            rules.append({
                "id": f"{source_id}:{index}",
                "source": source_id,
                "section": section,
                "text": normalized[:500],
            })

        def flush_paragraph() -> None:
            if paragraph:
                add_rule(" ".join(paragraph))
                paragraph.clear()

        for line_number, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if stripped == "---" and (line_number == 0 or in_frontmatter):
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter:
                continue
            if stripped.startswith("#"):
                flush_paragraph()
                section = stripped.lstrip("#").strip()[:100] or "root"
                continue
            match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", stripped)
            if match:
                flush_paragraph()
                add_rule(match.group(1))
                continue
            if stripped:
                paragraph.append(stripped)
            else:
                flush_paragraph()
        flush_paragraph()
    result = {
        "version": "compiled_skill_rules_v1",
        "passed": True,
        "sources": sources,
        # Do not truncate before platform selection. A large shared skill can
        # otherwise consume the whole budget and silently erase the active
        # platform's rules. generation_context_compiler applies the bounded
        # per-request limit after select_platform_rules().
        "rules": sorted(rules, key=lambda item: str(item.get("id") or "")),
        "rule_count": len(rules),
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
    names = required_workflow_skills(platform)
    paths = [root / "skills" / name / "SKILL.md" for name in names]
    hermes_root = _hermes_root(root)
    paths.extend(hermes_root / "skills" / name / "SKILL.md" for name in names)
    paths.extend(
        hermes_root / "skills" / name.removeprefix("content/") / "SKILL.md"
        for name in names
        if name.startswith("content/")
    )
    return list(dict.fromkeys(path for path in paths if path.is_file()))
