"""Metadata-only BGM candidate catalog.

The catalog stores discovery evidence to avoid repeating slow searches. It never
stores or serves an audio file, and selection always excludes prior fingerprints.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_FIELDS = ("source", "source_url", "license", "fingerprint", "mood")


def _safe_metadata(candidate: dict[str, Any]) -> dict[str, str]:
    return {field: str(candidate.get(field) or "").strip() for field in _FIELDS}


def _read(catalog_path: Path) -> dict[str, Any]:
    if not catalog_path.is_file():
        return {"version": "bgm_candidate_catalog_v1", "tracks": []}
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "bgm_candidate_catalog_v1", "tracks": []}
    return payload if isinstance(payload, dict) else {"version": "bgm_candidate_catalog_v1", "tracks": []}


def write_catalog_entry(catalog_path: str | Path, candidate: dict[str, Any]) -> dict[str, Any]:
    """Record candidate metadata only; raw files and local paths are discarded."""
    path = Path(catalog_path)
    payload = _read(path)
    tracks = payload.get("tracks") if isinstance(payload.get("tracks"), list) else []
    item = _safe_metadata(candidate)
    if not item["fingerprint"] or not item["source_url"]:
        raise ValueError("candidate requires fingerprint and source_url")
    if not any(isinstance(row, dict) and row.get("fingerprint") == item["fingerprint"] for row in tracks):
        tracks.append(item)
    payload = {"version": "bgm_candidate_catalog_v1", "tracks": tracks}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def select_unused_candidate(catalog_path: str | Path, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose a fresh source URL while preserving the no-audio-reuse rule."""
    existing = _read(Path(catalog_path)).get("tracks") or []
    used = {str(row.get("fingerprint") or "") for row in existing if isinstance(row, dict)}
    for candidate in candidates:
        item = _safe_metadata(candidate)
        if all(item.values()) and item["fingerprint"] not in used:
            return {"selected": item, "rejected_fingerprints": sorted(used)}
    return {"selected": {}, "rejected_fingerprints": sorted(used)}
