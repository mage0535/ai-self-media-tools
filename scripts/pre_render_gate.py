#!/usr/bin/env python3
"""Cheap, fail-closed checks that run before expensive video rendering."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

# 2026-08-15 修复：直接运行缺 PYTHONPATH 时自动注入项目根（self-contained）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from content_platform.scene_manifest import validate_scene_manifest


_PLACEHOLDER = re.compile(r"(?:\bstep\s+\d+\b|\bscene\s+\d+\b|keep the visual rhythm|match visual to narration)", re.IGNORECASE)
_PATH_LIKE = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:tmp|root|home|data)/|\.\.?[\\/])")


def _background_files(video_dir: Path) -> list[Path]:
    directory = video_dir / "backgrounds"
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("bg_*.*") if path.is_file())


def _card_values(card: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for key in ("t", "txt", "tts", "sub", "hook", "f"):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            values.append((key, value.strip()))
    for index, value in enumerate(card.get("items") or []):
        if isinstance(value, str) and value.strip():
            values.append((f"items[{index}]", value.strip()))
    return values


def validate_render_inputs(
    video_dir: Path,
    cards: list[dict[str, Any]],
    *,
    platform: str = "kuaishou",
    bgm_mean_volume_db: float | None = None,
    require_backgrounds: bool = True,
    require_cover_contract: bool = True,
    require_scene_manifest: bool = False,
    require_functional_mascots: bool = False,
    audio_plan: dict[str, Any] | None = None,
    require_materialized_audio: bool = True,
) -> dict[str, Any]:
    """Validate cheap input contracts without rendering or downloading assets."""
    video_dir = Path(video_dir)
    failures: list[str] = []
    warnings: list[str] = []

    if not cards:
        failures.append("cards_missing")
    for card_index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            failures.append(f"card_{card_index}_invalid")
            continue
        for field, value in _card_values(card):
            if _PLACEHOLDER.search(value):
                failures.append(f"card_{card_index}_{field}_placeholder")
            if _PATH_LIKE.search(value):
                failures.append(f"card_{card_index}_{field}_path_like_value")

    if require_cover_contract:
        first = cards[0] if cards else {}
        if not isinstance(first, dict) or str(first.get("layout") or "").strip() != "cover":
            failures.append("cover_card_missing")
        elif not str(first.get("t") or "").strip():
            failures.append("cover_title_missing")

    backgrounds = _background_files(video_dir)
    if require_backgrounds and len(backgrounds) < len(cards):
        failures.append(f"background_assets_incomplete:{len(backgrounds)}/{len(cards)}")
    for background in backgrounds:
        try:
            with Image.open(background) as image:
                image.verify()
            with Image.open(background) as image:
                width, height = image.size
            if min(width, height) < 320:
                failures.append(f"background_dimensions_too_small:{background.name}")
        except (OSError, UnidentifiedImageError):
            failures.append(f"background_decode_failed:{background.name}")

    if require_scene_manifest:
        scene_manifest = video_dir / "scene_manifest.json"
        if not scene_manifest.is_file():
            failures.append("scene_manifest_missing")
        else:
            try:
                manifest = json.loads(scene_manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None
            scene_gate = validate_scene_manifest(manifest)
            if not scene_gate.get("passed"):
                failures.append("scene_manifest_invalid")
            if require_functional_mascots:
                roles = manifest.get("mascot_roles") if isinstance(manifest, dict) else {}
                scenes = manifest.get("scenes") if isinstance(manifest, dict) else []
                role_text = json.dumps(roles, ensure_ascii=False).casefold()
                scene_text = json.dumps(scenes, ensure_ascii=False).casefold()
                functional = any(token in role_text or token in scene_text for token in ("cat", "dog", "猫", "狗", "猫咪", "小猫", "小狗"))
                if not functional:
                    failures.append("functional_mascot_role_missing")

    if audio_plan is None:
        configured_plan = Path(os.environ.get("VIDEO_TOOLCHAIN_PLAN_PATH") or "")
        if configured_plan.is_file():
            try:
                configured = json.loads(configured_plan.read_text(encoding="utf-8"))
                audio_plan = configured.get("audio_plan") if isinstance(configured, dict) else None
            except (OSError, json.JSONDecodeError):
                audio_plan = None
    audio_route = str((audio_plan or {}).get("route") or "")
    bgm = video_dir / "bgm.mp3"
    bgm_source = video_dir / "bgm_source.json"
    if (
        audio_route == "embedded_licensed_bgm"
        and not require_materialized_audio
        and not bgm.exists()
        and not bgm_source.exists()
    ):
        # Contract-only dry runs validate the route but intentionally do not
        # download/materialize media. Real renders keep the fail-closed path.
        warnings.append("bgm_pending_materialization")
    elif audio_route == "embedded_licensed_bgm" or bgm.exists() or bgm_source.exists():
        if not bgm.exists() or not bgm_source.exists():
            failures.append("bgm_asset_or_source_missing")
        else:
            try:
                source = json.loads(bgm_source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                source = {}
            if not str(source.get("license") or "").strip():
                failures.append("bgm_license_missing")
            declared_hash = str(source.get("sha256") or (source.get("manifest") or {}).get("fingerprint") or "").removeprefix("sha256:").strip()
            if not declared_hash:
                failures.append("bgm_fingerprint_missing")
            elif declared_hash != hashlib.sha256(bgm.read_bytes()).hexdigest():
                failures.append("bgm_fingerprint_mismatch")
            if not str(source.get("source") or source.get("source_url") or "").strip():
                failures.append("bgm_provenance_missing")
            if str(source.get("source") or "").casefold() in {"local", "bundled", "asset_library", "historical_local"} or str(source.get("source_url") or "").startswith("file:"):
                failures.append("bgm_local_historical_forbidden")
            if source.get("new_for_run") is False:
                failures.append("bgm_not_new_for_run")
    else:
        warnings.append("bgm_pending_resolution")

    if bgm_mean_volume_db is not None and bgm_mean_volume_db < -25:
        warnings.append("bgm_requires_auto_gain")

    return {
        "passed": not failures,
        "platform": platform,
        "video_dir": str(video_dir),
        "checks": {
            "cards": len(cards),
            "backgrounds": len(backgrounds),
            "cover_contract_required": require_cover_contract,
            "backgrounds_required": require_backgrounds,
            "bgm_mean_volume_db": bgm_mean_volume_db,
            "audio_route": audio_route,
            "materialized_audio_required": require_materialized_audio,
        },
        "failures": failures,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run cheap video checks before expensive rendering.")
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--cards", default="")
    parser.add_argument("--platform", default="kuaishou")
    parser.add_argument("--bgm-mean-volume-db", type=float, default=None)
    parser.add_argument("--require-scene-manifest", action="store_true")
    parser.add_argument("--require-functional-mascots", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    video_dir = Path(args.video_dir)
    cards_path = Path(args.cards) if args.cards else video_dir / "cards.json"
    try:
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = {"passed": False, "platform": args.platform, "failures": [f"cards_read_failed:{type(exc).__name__}"], "warnings": []}
    else:
        result = validate_render_inputs(video_dir, cards, platform=args.platform, bgm_mean_volume_db=args.bgm_mean_volume_db, require_scene_manifest=args.require_scene_manifest, require_functional_mascots=args.require_functional_mascots)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
