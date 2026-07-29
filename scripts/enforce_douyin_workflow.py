#!/usr/bin/env python3
"""Strict Douyin workflow gate.

This script is intentionally deterministic. It prevents the Douyin TikTok
repost lane from silently degrading into generic cat knowledge content.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from content_platform.media_quality import validate_douyin_tiktok_repost_packet as _validate_douyin_tiktok_repost_packet


STEPS = [
    "ops_strategy",
    "trend_analysis",
    "content_decision",
    "content_generation",
    "quality_gate",
    "publish_package",
]
STATUS_FILE = Path(os.environ.get("DOUYIN_WORKFLOW_STATUS", "/tmp/.douyin_workflow_status.json"))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULEBOOK = PROJECT_ROOT / "config" / "channel_content_rulebook.json"

TIKTOK_LINE = "tiktok_hot_localized_repost"
ALLOWED_VISUAL_REVIEWS = {"passed", "approved", "verified", "manual_passed"}
GENERIC_TITLES = {"猫咪日常", "猫咪治愈", "可爱猫咪", "猫咪知识", "这只小猫在想什么呢？"}
KNOWLEDGE_PATTERNS = [
    r"你有没有发现.*信号",
    r"这说明.*",
    r"科学.*猫",
    r"猫咪.*行为",
    r"猫.*知识",
    r"不是.*而是.*信号",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_status() -> dict[str, Any]:
    if STATUS_FILE.exists():
        return _read_json(STATUS_FILE)
    return {"current_step": 0, "completed": [], "artifacts": {}}


def save_status(status: dict[str, Any]) -> None:
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rulebook() -> dict[str, Any]:
    data = _read_json(RULEBOOK)
    return data["channel_rules"]["douyin"]


def require_previous_step(step_name: str) -> None:
    status = load_status()
    idx = STEPS.index(step_name)
    if idx > 0:
        previous = STEPS[idx - 1]
        if previous not in status["completed"]:
            raise SystemExit(f"blocked: complete {previous} before {step_name}")


def complete_step(step_name: str, artifacts: dict[str, Any] | None = None) -> None:
    require_previous_step(step_name)
    status = load_status()
    if step_name not in status["completed"]:
        status["completed"].append(step_name)
    if artifacts:
        status.setdefault("artifacts", {})[step_name] = artifacts
    status["current_step"] = STEPS.index(step_name) + 1
    save_status(status)
    print(f"ok: {step_name}")


def reset() -> None:
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()
    print("ok: reset")


def _value(packet: dict[str, Any], *names: str) -> Any:
    for name in names:
        cur: Any = packet
        for part in name.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur not in (None, "", [], {}):
            return cur
    return None


def validate_tiktok_repost_packet(packet: dict[str, Any], *, require_visual_review: bool = False) -> list[str]:
    return _validate_douyin_tiktok_repost_packet(packet, require_visual_review=require_visual_review)


def validate_video_quality(video_path: Path) -> list[str]:
    failures: list[str] = []
    if not video_path.exists():
        return [f"video file does not exist: {video_path}"]

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if probe.returncode != 0:
        return ["ffprobe failed"]
    data = json.loads(probe.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not video:
        failures.append("missing video stream")
    else:
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if width >= height:
            failures.append(f"video must be vertical, got {width}x{height}")
        elif width and height / width < 1.5:
            failures.append(f"video must be 9:16-ish vertical, got {width}x{height}")
    if not has_audio:
        failures.append("missing audio stream")

    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0
    if duration < 5 or duration > 120:
        failures.append(f"duration out of safe range: {duration:.1f}s")

    return failures


def command_validate_packet(args: argparse.Namespace) -> int:
    packet = _read_json(Path(args.packet))
    failures = validate_tiktok_repost_packet(packet, require_visual_review=args.require_visual_review)
    if args.require_final_video:
        video_path = packet.get("rendered_video") or packet.get("final_video") or packet.get("publish_video")
        if not video_path:
            failures.append("final publish video is required; source_candidate path is not enough")
        else:
            failures.extend(validate_video_quality(Path(str(video_path))))
    if failures:
        print(json.dumps({"passed": False, "failures": failures}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"passed": True, "failures": []}, ensure_ascii=False, indent=2))
    return 0


def command_step(args: argparse.Namespace) -> int:
    artifacts = json.loads(args.artifacts or "{}")
    if args.name == "quality_gate":
        video_path = artifacts.get("video_path")
        packet_path = artifacts.get("packet_path")
        failures: list[str] = []
        if video_path:
            failures.extend(validate_video_quality(Path(video_path)))
        if packet_path:
            packet = _read_json(Path(packet_path))
            failures.extend(validate_tiktok_repost_packet(packet, require_visual_review=True))
        if failures:
            print(json.dumps({"passed": False, "failures": failures}, ensure_ascii=False, indent=2))
            return 1
    complete_step(args.name, artifacts)
    return 0


def command_status(_: argparse.Namespace) -> int:
    status = load_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset")
    sub.add_parser("status")

    step = sub.add_parser("step")
    step.add_argument("name", choices=STEPS)
    step.add_argument("artifacts", nargs="?")

    validate = sub.add_parser("validate-packet")
    validate.add_argument("packet")
    validate.add_argument("--require-visual-review", action="store_true")
    validate.add_argument("--require-final-video", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "reset":
        reset()
        return 0
    if args.command == "status":
        return command_status(args)
    if args.command == "step":
        return command_step(args)
    if args.command == "validate-packet":
        return command_validate_packet(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
