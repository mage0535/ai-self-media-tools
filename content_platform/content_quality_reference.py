"""Load compact, executable content-quality reference rules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PACK = ROOT / "config" / "content_quality_reference_pack.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("content quality reference pack must be a JSON object")
    return value


def load_content_quality_reference_pack(
    platform: str = "",
    *,
    content_form: str = "",
    path: str | Path = DEFAULT_REFERENCE_PACK,
) -> dict[str, Any]:
    """Return a bounded reference pack suitable for provider input.

    The full config may grow over time.  Runtime generation receives only the
    sections relevant to the current platform plus compact provenance metadata.
    """
    source_path = Path(path).resolve()
    raw = _load_json(source_path)
    normalized = str(platform or "").casefold().strip()
    content_form = str(content_form or "").casefold().strip()
    sections = list((raw.get("platform_applicability") or {}).get(normalized) or [])
    if not sections:
        sections = ["hook_title_gate", "content_structure_gate", "cover_design_gate", "compliance_gate"]
        if "video" in content_form:
            sections.extend(["video_director_gate", "motion_discipline_gate"])
        elif content_form in {"manual_carousel", "long_article", "evidence_answer", "technical_article", "article"}:
            sections.append("image_text_card_gate")
    sections = list(dict.fromkeys(sections))
    pack: dict[str, Any] = {
        "version": str(raw.get("version") or ""),
        "loaded": True,
        "platform": normalized,
        "content_form": content_form,
        "path": "config/content_quality_reference_pack.json",
        "sha256": _sha256(source_path),
        "derived_only": bool((raw.get("source_summary") or {}).get("derived_only")),
        "sections": sections,
    }
    for section in sections:
        value = raw.get(section)
        if isinstance(value, dict):
            pack[section] = value
    return pack


def validate_content_quality_reference_pack(pack: dict[str, Any] | None) -> dict[str, Any]:
    failures: list[str] = []
    if not isinstance(pack, dict):
        return {"passed": False, "failures": ["content_quality_reference_pack_missing"]}
    if pack.get("version") != "content_quality_reference_pack_v1":
        failures.append("content_quality_reference_pack_version_mismatch")
    if pack.get("loaded") is not True:
        failures.append("content_quality_reference_pack_not_loaded")
    if not pack.get("sha256"):
        failures.append("content_quality_reference_pack_sha256_missing")
    sections = pack.get("sections")
    if not isinstance(sections, list) or not sections:
        failures.append("content_quality_reference_pack_sections_missing")
    else:
        for section in sections:
            if not isinstance(pack.get(str(section)), dict):
                failures.append(f"{section}_missing")
    if pack.get("derived_only") is not True:
        failures.append("content_quality_reference_pack_must_be_derived_only")
    return {"passed": not failures, "failures": sorted(set(failures))}
