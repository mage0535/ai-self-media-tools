"""Layered creative combination per task (MED12): pick one rule per layer, never one fixed recipe.

The catalog holds rules distilled from cited sources; selection is deterministic for a given
platform, topic and history, so prepare and generation-time collection agree.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "creative_catalog.json"
VERSION = "creative_combination_v1"
SHOT_COUNT = 3
RECENT_STRONG = 3  # the last N combinations on a platform weigh heavily against reuse
RECENT_WINDOW = 10
FORBIDDEN_RULE_WORDS = ("搬运", "去重", "repost", "re-upload", "刷量", "买粉")
VIDEO_FORMS = {"short_video", "landscape_video", "video"}
CAROUSEL_FORMS = {"manual_carousel", "image_text", "carousel", "image_text_card"}
POST_FORMS = {"short_post", "post", "thread"}
VIDEO_PLATFORMS = {"douyin_ai", "douyin_pet", "kuaishou", "tiktok", "shipinhao", "bilibili", "youtube"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path or CATALOG_PATH)
    raw = source.read_bytes()
    catalog = json.loads(raw.decode("utf-8"))
    checked = validate_catalog(catalog)
    if not checked["passed"]:
        raise ValueError("creative_catalog_invalid:" + ",".join(checked["failures"][:5]))
    catalog["sha256"] = _sha256(raw)
    return catalog


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    layers = list(catalog.get("layers") or [])
    sources = catalog.get("sources") or {}
    seen: set[str] = set()
    per_layer = {layer: 0 for layer in layers}
    for entry in catalog.get("entries") or []:
        identity = str(entry.get("id") or "")
        if not identity or identity in seen:
            failures.append(f"duplicate_or_missing_id:{identity}")
        seen.add(identity)
        layer = entry.get("layer")
        if layer not in per_layer or not identity.startswith(f"{layer}."):
            failures.append(f"unknown_layer:{identity}")
            continue
        per_layer[layer] += 1
        if not str(entry.get("rule") or "").strip():
            failures.append(f"rule_missing:{identity}")
        if not entry.get("sources") or any(name not in sources for name in entry["sources"]):
            failures.append(f"source_missing:{identity}")
        if any(word in str(entry.get("rule") or "") for word in FORBIDDEN_RULE_WORDS):
            failures.append(f"forbidden_rule:{identity}")
        if not entry.get("forms") or not entry.get("lanes"):
            failures.append(f"fit_missing:{identity}")
        if layer in {"narrative", "structure"} and len(entry.get("beats") or []) < 5:
            failures.append(f"beats_incomplete:{identity}")
    for layer, count in per_layer.items():
        if count < 3:
            failures.append(f"layer_too_small:{layer}")
    return {"passed": not failures, "failures": failures}


def content_form_kind(content_form: str, platform: str) -> str:
    form = str(content_form or "").casefold()
    # A slot without an explicit form takes its platform's native form (douyin_pet slots carry none).
    if form in VIDEO_FORMS or (not form and platform in VIDEO_PLATFORMS):
        return "video"
    if form in CAROUSEL_FORMS or platform == "xiaohongshu":
        return "carousel"
    if form in POST_FORMS or platform in {"twitter", "x", "mastodon"}:
        return "post"
    return "article"


def lane_for(platform: str) -> str:
    return "pet_healing" if platform == "douyin_pet" else "real_world_ai_implementation"


def _fits(entry: dict[str, Any], form: str, lane: str, capabilities: set[str]) -> bool:
    forms, lanes = entry.get("forms") or [], entry.get("lanes") or []
    return (("*" in forms or form in forms) and ("*" in lanes or lane in lanes)
            and set(entry.get("requires") or []) <= capabilities)


def _recent_penalty(identity: str, history: list[dict[str, Any]]) -> int:
    penalty = 0
    for index, previous in enumerate(history[:RECENT_WINDOW]):
        picks = previous.get("picks") or {}
        used = {value for value in picks.values() if isinstance(value, str)}
        used.update(value for value in picks.get("shot") or [] if isinstance(value, str))
        if identity in used:
            penalty += 3 if index < RECENT_STRONG else 1
    return penalty


def _ranked(entries, layer, goal, topic, evidence_text, structures, history, lane):
    scored = []
    for entry in entries:
        words = [word for word in entry.get("signals") or [] if word]
        topic_hits = sum(1 for word in words if word in topic)
        evidence_hits = sum(1 for word in words if word in evidence_text)
        strategy_hit = 1 if structures & set(entry.get("strategy_tags") or []) else 0
        score = ((2 if entry.get("goal") == goal else 0) + min(topic_hits, 2) + min(evidence_hits, 1) + strategy_hit
                 + int((entry.get("affinity") or {}).get(lane, 0)) - _recent_penalty(entry["id"], history))
        signals = topic_hits + evidence_hits
        # Deterministic per-topic variation among equal scores, so a quiet history does not always pick the same entry.
        tie = _sha256(f"{topic}|{layer}|{entry['id']}".encode())[:8]
        scored.append((-score, tie, entry, score, signals))
    scored.sort(key=lambda row: (row[0], row[1]))
    return scored


def select_combination(
    platform: str,
    topic: str,
    *,
    content_form: str = "",
    evidence_text: str = "",
    history: list[dict[str, Any]] | None = None,
    capabilities: set[str] | None = None,
    strategy: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Weigh platform goal, content form, the account's compiled strategy, current evidence and history."""
    catalog = catalog or load_catalog()
    normalized = str(platform or "").casefold()
    form = content_form_kind(content_form, normalized)
    lane = lane_for(normalized)
    goal = (catalog.get("platform_goal") or {}).get(normalized, "completion")
    strategy = strategy if isinstance(strategy, dict) else {}
    structures = {str(item) for item in strategy.get("structure_pool") or []}
    evidence = " ".join([str(evidence_text or "")] + [str(item) for item in strategy.get("hook_templates") or []])
    history = list(history or [])
    capabilities = set(capabilities or ())
    picks: dict[str, Any] = {}
    scores: dict[str, int] = {}
    for layer in catalog["layers"]:
        if layer == "shot" and form != "video":
            continue
        candidates = [entry for entry in catalog["entries"] if entry["layer"] == layer and _fits(entry, form, lane, capabilities)]
        if not candidates:
            continue
        ranked = _ranked(candidates, layer, goal, str(topic), evidence, structures, history, lane)
        if layer == "shot":
            picks[layer] = [row[2]["id"] for row in ranked[:SHOT_COUNT]]
            continue
        picks[layer] = ranked[0][2]["id"]
        scores[layer] = ranked[0][3]
    inputs = {"strategy_sha256": str(strategy.get("source_sha256") or ""), "strategy_structures": len(structures),
              "evidence_chars": len(evidence), "history": len(history)}
    return {"version": VERSION, "catalog_sha256": catalog["sha256"], "platform": normalized, "form": form,
            "lane": lane, "goal": goal, "picks": picks, "scores": scores, "inputs": inputs}


def resolve_combination(combination: dict[str, Any], catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expand picked ids into rule text for prompts; refuses a combination from a different catalog."""
    catalog = catalog or load_catalog()
    if not isinstance(combination, dict) or combination.get("version") != VERSION:
        raise ValueError("creative_combination_invalid")
    if combination.get("catalog_sha256") != catalog["sha256"]:
        raise ValueError("creative_catalog_changed")
    by_id = {entry["id"]: entry for entry in catalog["entries"]}
    resolved: dict[str, Any] = {}
    for layer, value in (combination.get("picks") or {}).items():
        ids = value if isinstance(value, list) else [value]
        rows = [copy.deepcopy(by_id[identity]) for identity in ids if identity in by_id]
        if len(rows) != len(ids):
            raise ValueError("creative_combination_unknown_entry:" + layer)
        resolved[layer] = rows if isinstance(value, list) else rows[0]
    return resolved


def story_beats(combination: dict[str, Any], catalog: dict[str, Any] | None = None) -> list[str]:
    """Narrative beats drive the story line; the structure layer's beats are the fallback."""
    resolved = resolve_combination(combination, catalog)
    for layer in ("narrative", "structure"):
        beats = (resolved.get(layer) or {}).get("beats") or []
        if len(beats) >= 5:
            return list(beats)
    return []


def recent_combinations(store, platform: str, *, days: int = 14, limit: int = 200) -> list[dict[str, Any]]:
    """Most recent first; read from stored job briefs on the same platform."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    found: list[dict[str, Any]] = []
    for job in store.list_jobs(limit=limit):
        if platform not in (job.get("platforms") or []):
            continue
        try:
            created = datetime.fromisoformat(str(job.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            continue
        combination = ((job.get("brief") or {}).get("content_blueprint") or {}).get("creative_combination")
        if isinstance(combination, dict) and combination.get("version") == VERSION:
            found.append(combination)
    return found
