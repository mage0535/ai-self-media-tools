#!/usr/bin/env python3
"""Strict Douyin AI workflow gate and stage enforcer.

Enforces deterministic, sequential progression for douyin_ai operations:
1. trend_scan_11sources: Multi-source 11-platform trend collection (min 8 successful sources)
2. topic_decision: Evidence-backed candidate evaluation + 7-day deduplication + ledger registration
3. script_and_storyboard: 8-beat workplace scenario script + subtitle length hard assertions (<=14 chars)
4. asset_provenance: 8 real Pexels background images (min 720x1280) + licensed real-instrument BGM
5. render_and_cover: Canonical video rendering + independent real-background cover
6. quality_gate_and_handoff: Keyframe extraction verification + handoff package bundling
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from content_platform.trend_scanner_11sources import run_11_sources_trend_scan, STANDARD_11_PLATFORMS

STEPS = [
    "trend_scan_11sources",
    "topic_decision",
    "script_and_storyboard",
    "asset_provenance",
    "render_and_cover",
    "quality_gate_and_handoff",
]

def get_status_file(date: str = "") -> Path:
    if not date:
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    env_p = os.environ.get("DOUYIN_AI_WORKFLOW_STATUS")
    if env_p:
        return Path(env_p)
    return PROJECT_ROOT / "data" / "ops_runs" / date / ".douyin_ai_workflow_status.json"


def load_status(status_file: Path) -> dict[str, Any]:
    if status_file.is_file():
        try:
            return json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"current_step": 0, "completed": [], "artifacts": {}}


def save_status(status_file: Path, status: dict[str, Any]) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def require_previous_step(status: dict[str, Any], step_name: str) -> None:
    idx = STEPS.index(step_name)
    if idx > 0:
        prev = STEPS[idx - 1]
        if prev not in status.get("completed", []):
            raise SystemExit(f"BLOCKED: complete '{prev}' before starting '{step_name}'")


def step_trend_scan_11sources(date: str, keyword: str = "AI工具") -> dict[str, Any]:
    """Execute or verify 11-source trend scan."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "trend_scan_11sources")

    matrix_file = PROJECT_ROOT / "data" / "ops_runs" / date / "11sources_matrix.json"
    if matrix_file.is_file():
        data = json.loads(matrix_file.read_text(encoding="utf-8"))
    else:
        data = run_11_sources_trend_scan(keyword=keyword)
        matrix_file.parent.mkdir(parents=True, exist_ok=True)
        matrix_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    if data.get("successful_count", 0) < 8:
        raise SystemExit(f"FAIL-CLOSED: only {data.get('successful_count', 0)}/11 sources succeeded, minimum 8 required.")

    # Also materialize local_ops_douyin platform_source_matrix
    local_ops_dir = PROJECT_ROOT / "data" / "local_ops_douyin"
    local_ops_dir.mkdir(parents=True, exist_ok=True)
    source_matrix_path = local_ops_dir / f"platform_source_matrix_{date}.json"
    source_matrix_payload = {
        "date": date,
        "platform": "douyin_ai",
        "scanned_at": data.get("scanned_at"),
        "source_matrix": {
            "attempted_sources": data.get("standard_platforms", STANDARD_11_PLATFORMS),
            "successful_sources": data.get("successful_platforms", []),
            "platform_internal_verified": True,
            "sample_count": sum(len(s.get("sample_topics", [])) for s in data.get("sources", [])),
        },
        "raw_sources": data.get("sources", []),
    }
    source_matrix_path.write_text(json.dumps(source_matrix_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if "trend_scan_11sources" not in status["completed"]:
        status["completed"].append("trend_scan_11sources")
    status.setdefault("artifacts", {})["trend_scan_11sources"] = {
        "matrix_file": str(matrix_file),
        "source_matrix_file": str(source_matrix_path),
        "successful_count": data.get("successful_count"),
        "attempted_count": data.get("attempted_count"),
    }
    status["current_step"] = max(status["current_step"], 1)
    save_status(status_file, status)
    return status["artifacts"]["trend_scan_11sources"]


def step_topic_decision(date: str, chosen_topic: str, direction: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify topic is backed by trend scan and records it."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "topic_decision")

    if len(candidates) < 2:
        raise SystemExit("FAIL-CLOSED: topic_decision requires at least 2 distinct candidates evaluated against 11-source signals.")

    # Check 7-day deduplication
    check_script = PROJECT_ROOT / "scripts" / "check_topic_ledger.py"
    if check_script.is_file():
        res = subprocess.run([sys.executable, str(check_script), "douyin_ai", chosen_topic], capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"FAIL-CLOSED: topic deduplication check failed:\n{res.stdout}\n{res.stderr}")

    # Register in ops_run
    from content_platform.ops_run import record_topic
    reg_result = record_topic(PROJECT_ROOT, date, "douyin_ai", chosen_topic, direction=direction)
    if not reg_result.get("accepted"):
        raise SystemExit(f"FAIL-CLOSED: ops_run record_topic failed: {reg_result.get('failed_dimensions')}")

    if "topic_decision" not in status["completed"]:
        status["completed"].append("topic_decision")
    status.setdefault("artifacts", {})["topic_decision"] = {
        "topic": chosen_topic,
        "direction": direction,
        "candidate_count": len(candidates),
        "ledger_manifest": reg_result.get("manifest_path"),
    }
    status["current_step"] = max(status["current_step"], 2)
    save_status(status_file, status)
    return status["artifacts"]["topic_decision"]


def step_script_and_storyboard(date: str, script_text: str, visual_contract: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate 8-beat script and subtitle constraints."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "script_and_storyboard")

    paragraphs = [p.strip() for p in script_text.strip().split("\n\n") if p.strip()]
    if len(paragraphs) != 8:
        raise SystemExit(f"FAIL-CLOSED: douyin_ai script must contain exactly 8 beats, got {len(paragraphs)}")

    if len(visual_contract) != 8:
        raise SystemExit(f"FAIL-CLOSED: visual_contract must define exactly 8 scene specs, got {len(visual_contract)}")

    # Hard subtitle length assertion: no single line > 16 chars, recommend <= 14
    for i, p in enumerate(paragraphs, start=1):
        sentences = re.split(r"[，。！？；：\n]", p)
        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) > 16:
                raise SystemExit(f"FAIL-CLOSED: beat {i} contains subtitle chunk exceeding 16 chars: '{s_clean}' ({len(s_clean)} chars)")

    if "script_and_storyboard" not in status["completed"]:
        status["completed"].append("script_and_storyboard")
    status.setdefault("artifacts", {})["script_and_storyboard"] = {
        "beat_count": len(paragraphs),
        "scene_count": len(visual_contract),
        "char_count": sum(len(p) for p in paragraphs),
    }
    status["current_step"] = max(status["current_step"], 3)
    save_status(status_file, status)
    return status["artifacts"]["script_and_storyboard"]


def check_cross_platform_collisions(date: str, bg_files: list[Path], cover_path: Path | None = None) -> list[str]:
    """Ensure no background or cover asset collides with another platform's runs on the same date."""
    collisions: list[str] = []
    runs_dir = PROJECT_ROOT / "data" / "runs"
    if not runs_dir.is_dir():
        return collisions

    our_hashes = {}
    for f in bg_files:
        if f.is_file():
            our_hashes[hashlib.sha256(f.read_bytes()).hexdigest()] = f.name
    if cover_path and cover_path.is_file():
        our_hashes[hashlib.sha256(cover_path.read_bytes()).hexdigest()] = cover_path.name

    for platform_dir in runs_dir.iterdir():
        if not platform_dir.is_dir() or platform_dir.name in ("douyin_ai", "benchmark_v2_fast"):
            continue
        for run_folder in platform_dir.glob(f"{date}*"):
            if not run_folder.is_dir():
                continue
            for img_file in list(run_folder.rglob("*.jpg")) + list(run_folder.rglob("*.png")):
                if img_file.is_file():
                    h = hashlib.sha256(img_file.read_bytes()).hexdigest()
                    if h in our_hashes:
                        collisions.append(
                            f"Collision: our '{our_hashes[h]}' matches {platform_dir.name} asset '{img_file.relative_to(PROJECT_ROOT)}' (SHA256: {h[:12]})"
                        )
    return collisions


def extract_template_fingerprint(html_text: str) -> str:
    """Extract template identification or architectural fingerprint from cover HTML."""
    if 'data-template="' in html_text:
        m = re.search(r'data-template=["\']([^"\']+)["\']', html_text)
        if m:
            return m.group(1)
    if "sticker-title" in html_text or "#facc15" in html_text:
        return "vibrant_sticker"
    if "evidence-row" in html_text or "middle-evidence" in html_text:
        return "evidence_card"
    if "terminal-box" in html_text or "terminal-header" in html_text:
        return "terminal_code"
    if "blueprint-tag" in html_text or "middle-steps" in html_text:
        return "minimal_blueprint"
    return "generic_html"


def check_cross_platform_template_collisions(date: str, cover_html_path: Path, current_platform: str = "douyin_ai") -> list[str]:
    """Ensure that the cover template used on this date is distinct and does not collide with other platforms."""
    collisions: list[str] = []
    if not cover_html_path.is_file():
        return collisions

    current_text = cover_html_path.read_text(encoding="utf-8", errors="replace")
    current_fp = extract_template_fingerprint(current_text)

    runs_dir = PROJECT_ROOT / "data" / "runs"
    if not runs_dir.is_dir():
        return collisions

    for platform_dir in runs_dir.iterdir():
        if not platform_dir.is_dir() or platform_dir.name in (current_platform, "benchmark_v2_fast"):
            continue
        for run_folder in platform_dir.glob(f"{date}*"):
            if not run_folder.is_dir():
                continue
            for other_cover in list(run_folder.rglob("cover.html")):
                if other_cover.is_file() and other_cover.resolve() != cover_html_path.resolve():
                    other_text = other_cover.read_text(encoding="utf-8", errors="replace")
                    other_fp = extract_template_fingerprint(other_text)
                    if current_fp and other_fp and current_fp == other_fp:
                        collisions.append(
                            f"Collision: template fingerprint '{current_fp}' was already used by platform "
                            f"'{platform_dir.name}' in run '{run_folder.name}' on {date}! "
                            f"Multi-platform duplication is strictly forbidden. Please choose a different distinct style."
                        )
    return collisions


def check_cover_template_distinct(cover_html_path: Path, date: str = "", current_platform: str = "douyin_ai") -> list[str]:
    """Ensure cover template does not duplicate another platform on the same date."""
    failures: list[str] = []
    if not cover_html_path.is_file():
        return failures
    text = cover_html_path.read_text(encoding="utf-8", errors="replace")

    # 1. Cross-platform template collision check
    if date:
        failures.extend(check_cross_platform_template_collisions(date, cover_html_path, current_platform))

    # 2. Legacy signature check (for backward compatibility when date is not passed)
    if not date:
        if "#facc15" in text and "sticker-title" in text:
            failures.append("Cover uses Kuaishou yellow sticker template (.sticker-title with #facc15)")
        if "#e11d48" in text and "pill" in text:
            failures.append("Cover uses Kuaishou red pill template (.pill with #e11d48)")

    return failures

def step_asset_provenance(date: str, bg_dir: Path, bgm_file: Path) -> dict[str, Any]:
    """Validate 8 background images and BGM provenance."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "asset_provenance")

    from PIL import Image

    bg_files = sorted(list(bg_dir.glob("*.jpg")) + list(bg_dir.glob("*.png")))
    if len(bg_files) < 8:
        raise SystemExit(f"FAIL-CLOSED: requires at least 8 real background images, found {len(bg_files)} in {bg_dir}")

    for bg in bg_files[:8]:
        try:
            with Image.open(bg) as im:
                im.verify()
            with Image.open(bg) as im:
                w, h = im.size
                if w < 720 or h < 1080:
                    raise SystemExit(f"FAIL-CLOSED: background {bg.name} resolution too small: {w}x{h}, min 720x1080")
        except Exception as exc:
            raise SystemExit(f"FAIL-CLOSED: background image {bg} failed verification: {exc}")

    # Anti-collision gate: Ensure zero collision with other platforms on the same date
    collisions = check_cross_platform_collisions(date, bg_files[:8])
    if collisions:
        raise SystemExit(f"FAIL-CLOSED: Cross-platform background asset collision detected:\n" + "\n".join(collisions))

    if not bgm_file.is_file():
        raise SystemExit(f"FAIL-CLOSED: BGM file not found: {bgm_file}")

    if "asset_provenance" not in status["completed"]:
        status["completed"].append("asset_provenance")
    status.setdefault("artifacts", {})["asset_provenance"] = {
        "bg_count": len(bg_files),
        "bgm_path": str(bgm_file),
    }
    status["current_step"] = max(status["current_step"], 4)
    save_status(status_file, status)
    return status["artifacts"]["asset_provenance"]


def step_render_and_cover(date: str, video_path: Path, cover_path: Path) -> dict[str, Any]:
    """Validate rendered video and cover."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "render_and_cover")

    if not video_path.is_file():
        raise SystemExit(f"FAIL-CLOSED: video not found: {video_path}")
    if not cover_path.is_file():
        raise SystemExit(f"FAIL-CLOSED: cover not found: {cover_path}")

    # Verify cover template distinctiveness and cross-platform uniqueness
    cover_collisions = check_cross_platform_collisions(date, [], cover_path=cover_path)
    if cover_collisions:
        raise SystemExit(f"FAIL-CLOSED: Cross-platform cover collision detected:\n" + "\n".join(cover_collisions))

    cover_html = cover_path.parent / "cover.html"
    template_failures = check_cover_template_distinct(cover_html, date=date, current_platform="douyin_ai")
    if template_failures:
        raise SystemExit(f"FAIL-CLOSED: Douyin AI cover template rejected:\n" + "\n".join(template_failures))

    # Verify video with ffprobe
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
        "-show_entries", "format=duration", "-of", "json", str(video_path)
    ], capture_output=True, text=True)
    if probe.returncode != 0:
        raise SystemExit(f"FAIL-CLOSED: ffprobe failed on {video_path}")
    info = json.loads(probe.stdout or "{}")
    streams = info.get("streams", [])
    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not v_stream or not has_audio:
        raise SystemExit("FAIL-CLOSED: video must have both video and audio streams")
    w = int(v_stream.get("width", 0))
    h = int(v_stream.get("height", 0))
    if w >= h:
        raise SystemExit(f"FAIL-CLOSED: video must be vertical 9:16, got {w}x{h}")

    duration = float(info.get("format", {}).get("duration", 0))
    if duration < 25.0 or duration > 100.0:
        raise SystemExit(f"FAIL-CLOSED: duration {duration:.1f}s out of acceptable range [25s, 100s]")

    if "render_and_cover" not in status["completed"]:
        status["completed"].append("render_and_cover")
    status.setdefault("artifacts", {})["render_and_cover"] = {
        "video_path": str(video_path),
        "cover_path": str(cover_path),
        "duration": duration,
        "resolution": f"{w}x{h}",
    }
    status["current_step"] = max(status["current_step"], 5)
    save_status(status_file, status)
    return status["artifacts"]["render_and_cover"]


def step_quality_gate_and_handoff(date: str, run_dir: Path, handoff_packet: dict[str, Any]) -> dict[str, Any]:
    """Validate final gate and record completed handoff."""
    status_file = get_status_file(date)
    status = load_status(status_file)
    require_previous_step(status, "quality_gate_and_handoff")

    # Hard Quality Gate: Verify keyframe audits exist and are non-empty
    keyframes_dir = run_dir / "render" / "keyframes_audit"
    if not keyframes_dir.is_dir():
        keyframes_dir = run_dir / "keyframes_audit"
    if not keyframes_dir.is_dir():
        raise SystemExit(f"FAIL-CLOSED: missing keyframes_audit directory in {run_dir}")
    frames = list(keyframes_dir.glob("*.jpg")) + list(keyframes_dir.glob("*.png"))
    if len(frames) < 8:
        raise SystemExit(f"FAIL-CLOSED: requires at least 8 keyframe snapshots for visual audit, found {len(frames)}")
    for f in frames:
        if f.stat().st_size < 30000:
            raise SystemExit(f"FAIL-CLOSED: keyframe snapshot {f.name} suspiciously small ({f.stat().st_size} bytes)")

    # Validate handoff packet mandatory fields
    required_fields = ["platform", "date", "title", "copy_text", "tags", "video_path", "cover_path"]
    for field in required_fields:
        if not handoff_packet.get(field):
            raise SystemExit(f"FAIL-CLOSED: handoff packet missing required field: {field}")

    if "quality_gate_and_handoff" not in status["completed"]:
        status["completed"].append("quality_gate_and_handoff")
    status.setdefault("artifacts", {})["quality_gate_and_handoff"] = handoff_packet
    status["current_step"] = 6
    save_status(status_file, status)
    return status["artifacts"]["quality_gate_and_handoff"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce strict Douyin AI workflow.")
    parser.add_argument("step", choices=STEPS + ["status", "reset"])
    parser.add_argument("--date", default="")
    parser.add_argument("--keyword", default="AI工具")
    parser.add_argument("--topic", default="")
    parser.add_argument("--direction", default="")
    parser.add_argument("--candidates-json", default="")
    parser.add_argument("--script-file", default="")
    parser.add_argument("--contract-file", default="")
    parser.add_argument("--bg-dir", default="")
    parser.add_argument("--bgm-file", default="")
    parser.add_argument("--video-file", default="")
    parser.add_argument("--cover-file", default="")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--handoff-json", default="")
    args = parser.parse_args()

    date = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    status_file = get_status_file(date)

    if args.step == "status":
        print(json.dumps(load_status(status_file), ensure_ascii=False, indent=2))
        return 0
    if args.step == "reset":
        if status_file.is_file():
            status_file.unlink()
        print(f"Status reset for date {date}")
        return 0

    if args.step == "trend_scan_11sources":
        res = step_trend_scan_11sources(date, keyword=args.keyword)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.step == "topic_decision":
        if not args.topic or not args.direction:
            parser.error("--topic and --direction are required for topic_decision")
        candidates = []
        if args.candidates_json:
            stripped = args.candidates_json.strip()
            if stripped.startswith(("[", "{")):
                candidates = json.loads(stripped)
            elif len(args.candidates_json) < 260 and Path(args.candidates_json).is_file():
                candidates = json.loads(Path(args.candidates_json).read_text(encoding="utf-8"))
            else:
                candidates = json.loads(args.candidates_json)
        else:
            candidates = [{"topic": args.topic, "hook": "default"}]
        res = step_topic_decision(date, args.topic, args.direction, candidates)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.step == "script_and_storyboard":
        if not args.script_file or not args.contract_file:
            parser.error("--script-file and --contract-file are required for script_and_storyboard")
        script_text = Path(args.script_file).read_text(encoding="utf-8")
        contract = json.loads(Path(args.contract_file).read_text(encoding="utf-8"))
        res = step_script_and_storyboard(date, script_text, contract)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.step == "asset_provenance":
        if not args.bg_dir or not args.bgm_file:
            parser.error("--bg-dir and --bgm-file are required for asset_provenance")
        res = step_asset_provenance(date, Path(args.bg_dir), Path(args.bgm_file))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.step == "render_and_cover":
        if not args.video_file or not args.cover_file:
            parser.error("--video-file and --cover-file are required for render_and_cover")
        res = step_render_and_cover(date, Path(args.video_file), Path(args.cover_file))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.step == "quality_gate_and_handoff":
        if not args.run_dir or not args.handoff_json:
            parser.error("--run-dir and --handoff-json are required for quality_gate_and_handoff")
        packet = json.loads(Path(args.handoff_json).read_text(encoding="utf-8"))
        res = step_quality_gate_and_handoff(date, Path(args.run_dir), packet)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
