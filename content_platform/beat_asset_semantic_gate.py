"""Fail-closed beat-to-asset semantic binding gate."""
from __future__ import annotations


class BeatAssetSemanticError(ValueError):
    pass


def _required_tag(scene: dict) -> str:
    explicit = str(scene.get("required_semantic_tag") or "").strip().casefold()
    if explicit:
        return explicit
    mode = str(scene.get("visual_mode") or "").strip().casefold()
    return {
        "sleep_pose_hook": "sleep_pose_hook",
        "curled_sleep_pose": "curled",
        "side_sleep_pose": "side_stretch",
        "back_sleep_pose": "belly_up",
        "loaf_alert_pose": "loaf",
        "hidden_sleep_pose": "hidden_safe_space",
        "observe_not_diagnose": "observation_boundary",
        "sleep_pose_checklist": "checklist_cta",
    }.get(mode, "")


def validate_beat_asset_semantics(scene_contract: list[dict], assignments: list[dict]) -> dict:
    by_beat = {}
    for item in assignments:
        if not isinstance(item, dict):
            continue
        beat = str(item.get("beat_id") or item.get("scene_id") or "").strip()
        if beat in by_beat:
            raise BeatAssetSemanticError(f"duplicate_asset_beat:{beat}")
        by_beat[beat] = item
    failures = []
    checked = []
    for scene in scene_contract:
        beat = str(scene.get("beat_id") or scene.get("scene_id") or "").strip()
        required = _required_tag(scene)
        asset = by_beat.get(beat)
        if not beat or not required:
            failures.append(f"{beat or 'unknown'}:required_semantic_tag_missing")
            continue
        if asset is None:
            failures.append(f"{beat}:asset_missing")
            continue
        tags = {str(tag).strip().casefold() for tag in (asset.get("semantic_tags") or [])}
        if required not in tags:
            failures.append(f"{beat}:required_tag_missing:{required}")
        checked.append({"beat_id": beat, "required_semantic_tag": required, "asset_tags": sorted(tags)})
    if len(by_beat) != len(scene_contract):
        failures.append("beat_asset_count_mismatch")
    result = {"passed": not failures, "checked": checked, "failures": sorted(set(failures))}
    if failures:
        raise BeatAssetSemanticError(",".join(result["failures"]))
    return result
