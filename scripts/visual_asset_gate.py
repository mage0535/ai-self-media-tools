#!/usr/bin/env python3
"""Fail-closed gate for scene footage relevance and cross-platform reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


MIN_MATCH_SCORE = 0.72
MAX_DHASH_DISTANCE = 6


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_dhash(path: Path) -> str:
    from PIL import Image

    with tempfile.TemporaryDirectory() as temp_dir:
        frame = Path(temp_dir) / "frame.png"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(path),
                "-frames:v", "1", "-vf", "scale=9:8", str(frame),
            ],
            check=True,
            timeout=45,
        )
        image = Image.open(frame).convert("L")
        pixels = list(image.get_flattened_data())
        bits = []
        for row in range(8):
            offset = row * 9
            bits.extend(pixels[offset + col] > pixels[offset + col + 1] for col in range(8))
        return f"{sum(1 << index for index, bit in enumerate(bits) if bit):016x}"


def _distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def validate_assets(video_dir: Path, platform: str, scan_root: Path | None = None) -> dict:
    video_dir = video_dir.resolve()
    scan_root = (scan_root or video_dir.parent).resolve()
    manifest_path = video_dir / "scene_manifest.json"
    provenance_path = video_dir / "footage_provenance.json"
    failures: list[str] = []

    if not manifest_path.is_file() or not provenance_path.is_file():
        return {"passed": False, "failures": ["scene_manifest_or_footage_provenance_missing"]}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes") or []
    records = provenance.get("scenes") if isinstance(provenance, dict) else provenance
    records = records or []
    if len(scenes) != len(records) or len(scenes) < 6:
        failures.append("scene_provenance_count_mismatch")

    current: list[dict] = []
    for index, (scene, record) in enumerate(zip(scenes, records), 1):
        scene_id = str(scene.get("scene_id") or f"s{index:02d}")
        asset = scene.get("asset") or {}
        source = Path(str(asset.get("source") or record.get("path") or ""))
        if not source.is_absolute():
            source = video_dir / source
        required = {str(item).casefold() for item in scene.get("asset_search_terms") or []}
        observed = {str(item).casefold() for item in record.get("observed_subjects") or []}
        score = float(record.get("semantic_match_score") or 0)
        if not source.is_file():
            failures.append(f"{scene_id}:footage_missing")
            continue
        if not required or not observed or not required.intersection(observed):
            failures.append(f"{scene_id}:semantic_terms_not_evidenced")
        if score < MIN_MATCH_SCORE or not str(record.get("match_reason") or "").strip():
            failures.append(f"{scene_id}:semantic_match_below_threshold")
        sha = _sha256(source)
        dhash = _frame_dhash(source)
        current.append({"scene_id": scene_id, "path": str(source), "sha256": sha, "dhash": dhash})

    hashes = [item["sha256"] for item in current]
    if len(hashes) != len(set(hashes)):
        failures.append("within_video_exact_asset_reuse")
    for left_index, left in enumerate(current):
        for right in current[left_index + 1 :]:
            if _distance(left["dhash"], right["dhash"]) <= MAX_DHASH_DISTANCE:
                failures.append(f"within_video_visual_reuse:{left['scene_id']}:{right['scene_id']}")

    other_assets: list[dict] = []
    for path in scan_root.glob("*/footage/scene_*.mp4"):
        if video_dir in path.parents:
            continue
        try:
            other_assets.append({"path": str(path), "sha256": _sha256(path), "dhash": _frame_dhash(path)})
        except (OSError, subprocess.SubprocessError):
            continue
    for item in current:
        for other in other_assets:
            if item["sha256"] == other["sha256"]:
                failures.append(f"cross_platform_exact_reuse:{item['scene_id']}:{other['path']}")
            elif _distance(item["dhash"], other["dhash"]) <= MAX_DHASH_DISTANCE:
                failures.append(f"cross_platform_visual_reuse:{item['scene_id']}:{other['path']}")

    result = {
        "passed": not failures,
        "platform": platform,
        "minimum_semantic_match_score": MIN_MATCH_SCORE,
        "assets": current,
        "cross_platform_assets_scanned": len(other_assets),
        "failures": sorted(set(failures)),
    }
    (video_dir / "visual_asset_gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--scan-root")
    args = parser.parse_args()
    result = validate_assets(
        Path(args.video_dir), args.platform, Path(args.scan_root) if args.scan_root else None
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
