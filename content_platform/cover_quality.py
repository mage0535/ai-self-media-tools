"""Topic-specific narrative cover validation shared by all delivery paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


ALLOWED_LAYOUTS = {
    "character_showdown", "evidence_interface", "hero_conflict", "diagonal_split",
    "before_after", "checklist_poster", "magazine_story", "result_reveal",
}
VERTICAL = {"douyin", "douyin_ai", "douyin_pet", "tiktok", "kuaishou", "xiaohongshu", "shipinhao"}


def validate_cover(cover: str | Path, evidence: dict[str, Any] | str | Path | None, platform: str = "") -> dict[str, Any]:
    path = Path(cover)
    failures: list[str] = []
    if not path.is_file():
        return {"passed": False, "failures": ["cover_missing"]}
    if isinstance(evidence, (str, Path)):
        try:
            evidence = json.loads(Path(evidence).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evidence = {}
    evidence = evidence if isinstance(evidence, dict) else {}
    try:
        width, height = Image.open(path).size
    except (OSError, UnidentifiedImageError):
        return {"passed": False, "failures": ["cover_probe_failed"]}
    normalized = str(platform or evidence.get("platform") or "").casefold()
    if min(width, height) < 1000:
        failures.append("cover_resolution_too_low")
    if normalized in VERTICAL and abs(width / height - 9 / 16) > 0.02:
        failures.append("vertical_cover_aspect_invalid")
    if evidence.get("layout_key") not in ALLOWED_LAYOUTS:
        failures.append("viral_layout_missing")
    for field in ("hook", "conflict_or_payoff", "content_match_reason"):
        if not str(evidence.get(field) or "").strip():
            failures.append(f"{field}_missing")
    if not evidence.get("focal_subjects"):
        failures.append("focal_subjects_missing")
    if evidence.get("safe_zone_verified") is not True:
        failures.append("safe_zone_not_verified")
    if evidence.get("degraded") is True:
        failures.append("degraded_cover_forbidden")
    return {
        "passed": not failures,
        "cover": str(path),
        "dimensions": [width, height],
        "layout_key": evidence.get("layout_key"),
        "failures": failures,
    }


def normalize_cover_resolution(cover: str | Path, minimum: int = 1200) -> dict[str, Any]:
    path = Path(cover)
    try:
        with Image.open(path) as image:
            width, height = image.size
            if min(width, height) >= minimum:
                return {"passed": True, "dimensions": [width, height], "resized": False}
            scale = minimum / min(width, height)
            size = (max(minimum, round(width * scale)), max(minimum, round(height * scale)))
            resized = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
            temp = path.with_suffix(path.suffix + ".normalized")
            resized.save(temp, format="PNG" if path.suffix.casefold() == ".png" else None)
        temp.replace(path)
        return {"passed": True, "dimensions": list(size), "resized": True}
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return {"passed": False, "dimensions": [], "resized": False, "error": str(exc)[:200]}
