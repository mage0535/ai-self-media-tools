"""Single auditable scene contract for rendered videos.

The manifest joins the existing recipe, cards and Shotcraft evidence so an
external renderer cannot claim a visual plan without declaring how every beat
will be shown.
"""

from __future__ import annotations

from typing import Any


SHORT_DURATION_LIMITS = {"tiktok": 60, "youtube": 60}
LAYER_KEYS = ("background", "subject", "text", "transition")


def build_scene_manifest(
    cards: list[dict[str, Any]],
    visual_recipe: dict[str, Any],
    plan: dict[str, Any] | None,
    title: str,
) -> dict[str, Any]:
    """Build a renderer-neutral contract from existing planned evidence."""
    plan = plan or {}
    platform = _platform(plan)
    matches = list(visual_recipe.get("scene_asset_match") or [])
    scenes = []
    for index, card in enumerate(cards, 1):
        match = matches[(index - 1) % len(matches)] if matches else {}
        shotcraft = card.get("shotcraft") if isinstance(card.get("shotcraft"), dict) else {}
        narration = str(card.get("tts") or card.get("txt") or "").strip()
        claim = str(card.get("txt") or narration).strip()
        source = str(card.get("visual_asset") or match.get("visual_source") or "").strip()
        reason = str(match.get("match_reason") or "").strip()
        scenes.append(
            {
                "scene_id": f"s{index:02d}",
                "narration": narration,
                "subtitle": narration,
                "visual_claim": claim,
                "asset": {"source": source, "kind": "resolved_or_planned_visual_asset"},
                "evidence": [{"source": source, "match_reason": reason}] if source and reason else [],
                "motion": {
                    "background": "content_matched_background_motion",
                    "subject": str(shotcraft.get("name") or "card_module_stagger"),
                    "text": "lower_third_subtitles",
                    "transition": "cut" if index == 1 else "content_matched_crossfade",
                },
            }
        )
    max_seconds = SHORT_DURATION_LIMITS.get(platform)
    return {
        "version": "scene_manifest_v1",
        "title": str(title or "").strip(),
        "platform": platform,
        "duration_policy": {"max_seconds": max_seconds, "enforced": max_seconds is not None},
        "visual_recipe_fingerprint": str(visual_recipe.get("fingerprint") or ""),
        "scenes": scenes,
    }


def validate_scene_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Fail closed when a renderer-ready scene contract has missing evidence."""
    if not isinstance(manifest, dict):
        return _result(["scene_manifest missing"])
    failures: list[str] = []
    if manifest.get("version") != "scene_manifest_v1":
        failures.append("scene_manifest version missing or unsupported")
    scenes = manifest.get("scenes") if isinstance(manifest.get("scenes"), list) else []
    if len(scenes) < 3:
        failures.append("scene_manifest must include at least 3 scenes")
    seen = set()
    for index, scene in enumerate(scenes, 1):
        prefix = f"scene[{index}]"
        if not isinstance(scene, dict):
            failures.append(f"{prefix} must be an object")
            continue
        scene_id = str(scene.get("scene_id") or "")
        if not scene_id:
            failures.append(f"{prefix} id missing")
        elif scene_id in seen:
            failures.append(f"{prefix} id duplicated")
        seen.add(scene_id)
        for key in ("narration", "subtitle", "visual_claim"):
            if not str(scene.get(key) or "").strip():
                failures.append(f"{prefix} {key} missing")
        asset = scene.get("asset") if isinstance(scene.get("asset"), dict) else {}
        if not str(asset.get("source") or "").strip():
            failures.append(f"{prefix} asset source missing")
        evidence = scene.get("evidence") if isinstance(scene.get("evidence"), list) else []
        if not evidence:
            failures.append(f"{prefix} evidence missing")
        elif not all(isinstance(item, dict) and item.get("source") and item.get("match_reason") for item in evidence):
            failures.append(f"{prefix} evidence incomplete")
        motion = scene.get("motion") if isinstance(scene.get("motion"), dict) else {}
        for layer in LAYER_KEYS:
            if not str(motion.get(layer) or "").strip():
                failures.append(f"{prefix} motion {layer} missing")
    return _result(failures)


def validate_rendered_duration(manifest: dict[str, Any], duration_seconds: float) -> dict[str, Any]:
    """Enforce platform duration only when the platform has a hard short limit."""
    policy = manifest.get("duration_policy") if isinstance(manifest, dict) else {}
    limit = policy.get("max_seconds") if isinstance(policy, dict) else None
    if not isinstance(limit, (int, float)):
        return {"passed": True, "duration_seconds": duration_seconds, "limit_seconds": None}
    passed = duration_seconds <= float(limit)
    return {
        "passed": passed,
        "duration_seconds": duration_seconds,
        "limit_seconds": limit,
        "failure": "duration exceeds platform limit" if not passed else "",
    }


def _platform(plan: dict[str, Any]) -> str:
    platforms = plan.get("platforms") if isinstance(plan.get("platforms"), list) else []
    return str(platforms[0] if platforms else plan.get("platform") or "unknown").strip().casefold()


def _result(failures: list[str]) -> dict[str, Any]:
    return {"passed": not failures, "failures": failures, "failed_dimensions": ["scene_manifest"] if failures else []}
