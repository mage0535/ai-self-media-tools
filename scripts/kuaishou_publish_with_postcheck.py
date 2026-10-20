#!/usr/bin/env python3
"""Run the guarded Kuaishou upload path and management-page postcheck.

This wrapper exists to keep Hermes from calling ad-hoc upload scripts. It does
not treat uploader stdout as completion; success requires management-page
postcheck evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAU_DIR = Path(os.environ.get("SOCIAL_AUTO_UPLOAD_DIR", str(Path.home() / "social-auto-upload")))
DEFAULT_SAU_PYTHON = DEFAULT_SAU_DIR / "venv" / "bin" / "python"


def _strip_hashtags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"#[^\s#]+", "", text or "")).strip()


def _dedupe_tags(raw: Any) -> list[str]:
    values: list[str]
    if isinstance(raw, str):
        values = raw.split(",")
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    else:
        values = []
    result: list[str] = []
    for value in values:
        tag = value.strip().lstrip("#")
        if tag and tag not in result:
            result.append(tag)
    return result[:3]


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return data


def _thumbnail_path(manifest: dict[str, Any]) -> str:
    raw = manifest.get("cover_path") or manifest.get("thumbnail_path") or manifest.get("cover") or ""
    if isinstance(raw, dict):
        raw = raw.get("path") or raw.get("local_path") or raw.get("file") or ""
    return str(raw or "").strip()


def _run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _postcheck_passed(report: dict[str, Any], manifest: dict[str, Any]) -> bool:
    """Require one evidenced work; only the scheduled state satisfies scheduling."""
    matched_work = report.get("matched_work")
    if report.get("passed") is not True or not isinstance(matched_work, dict):
        return False
    if (matched_work.get("title") != manifest["title"]
            or matched_work.get("description") != manifest["description"]
            or report.get("title_found") is not True
            or report.get("description_found") is not True
            or not Path(str(report.get("evidence_path") or "")).is_file()):
        return False
    if report.get("status") == "success_under_review":
        return report.get("delivery_state") == matched_work.get("state") == "under_review"
    return bool(
        report.get("status") == "management_postcheck_found"
        and report.get("delivery_state") == matched_work.get("state") == "scheduled"
        and report.get("schedule_found") is True
        and matched_work.get("schedule_time") == manifest["schedule_time"]
    )


def _require_ops_runner_context() -> bool:
    required = ["CONTENT_PLATFORM_OPS_RUNNER", "WORKFLOW_ID", "RUN_ID", "JOB_ID"]
    missing = [name for name in required if not str(os.environ.get(name, "")).strip()]
    runner_enabled = str(os.environ.get("CONTENT_PLATFORM_OPS_RUNNER", "")).casefold() in {"1", "true", "yes", "on"}
    if missing or not runner_enabled:
        print(json.dumps({
            "ok": False,
            "stage": "ops_runner_required",
            "error": "ops_runner_required",
            "missing": missing,
        }, ensure_ascii=False, indent=2))
        return False
    return True


def _skip_preflight_authorized(manifest: dict[str, Any]) -> bool:
    """Current Kuaishou policy requires preflight for every publishing run."""
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Kuaishou upload plus required management-page postcheck.")
    parser.add_argument("manifest", help="Kuaishou manifest/packet JSON.")
    parser.add_argument("--account", default="main")
    parser.add_argument("--out-dir", default="", help="Evidence output directory. Defaults to data/local_ops_kuaishou/publish_<timestamp>.")
    parser.add_argument("--sau-dir", default=str(DEFAULT_SAU_DIR))
    parser.add_argument("--sau-python", default=str(DEFAULT_SAU_PYTHON))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--skip-preflight", action="store_true", help="Disabled. Current Kuaishou work must pass preflight.")
    args = parser.parse_args()

    if not _require_ops_runner_context():
        return 2

    manifest_path = Path(args.manifest)
    manifest = _load_manifest(manifest_path)
    video_file = Path(str(manifest.get("video_file") or manifest.get("file") or manifest.get("path") or ""))
    title = str(manifest.get("title") or manifest.get("short_title") or "").strip()
    description = _strip_hashtags(str(manifest.get("description") or manifest.get("caption") or ""))
    tags = _dedupe_tags(manifest.get("tags") or manifest.get("topics") or [])
    schedule = str(manifest.get("schedule_time") or manifest.get("scheduled_at") or "").strip()
    thumbnail = _thumbnail_path(manifest)

    errors = []
    if not video_file.is_file():
        errors.append(f"video_file_missing:{video_file}")
    if not title:
        errors.append("title_missing")
    if not schedule:
        errors.append("schedule_time_missing")
    if errors:
        print(json.dumps({"ok": False, "stage": "input_validation", "errors": errors}, ensure_ascii=False, indent=2))
        return 2

    if args.skip_preflight:
        if not _skip_preflight_authorized(manifest):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "stage": "skip_preflight_disabled",
                        "error": "skip_preflight_disabled",
                        "required": ["remove --skip-preflight", "fix the packet until validate_kuaishou_auto_packet.py passes"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data" / "local_ops_kuaishou" / f"publish_{int(time.time())}"
    out_dir.mkdir(parents=True, exist_ok=True)

    clean_manifest = dict(manifest)
    clean_manifest.update(
        {
            "account": args.account,
            "video_file": str(video_file),
            "title": title,
            "description": description,
            "tags": tags,
            "schedule_time": schedule,
        }
    )
    clean_manifest_path = out_dir / "kuaishou_publish_manifest.json"
    _write_json(clean_manifest_path, clean_manifest)

    env = os.environ.copy()

    env.setdefault("SOCIAL_AUTO_UPLOAD_DIR", str(Path(args.sau_dir)))
    env["KUAISHOU_STANDARD_RUNNER_APPROVED"] = "1"

    if not args.skip_preflight:
        preflight = _run(
            [sys.executable, str(ROOT / "scripts" / "validate_kuaishou_auto_packet.py"), str(manifest_path), "--phase", "preflight"],
            cwd=ROOT,
            env=env,
            timeout=120,
        )
        (out_dir / "preflight_stdout.log").write_text(preflight.stdout, encoding="utf-8")
        (out_dir / "preflight_stderr.log").write_text(preflight.stderr, encoding="utf-8")
        if preflight.returncode != 0:
            print(json.dumps({"ok": False, "stage": "preflight", "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
            return 2

    upload_cmd = [
        str(Path(args.sau_python)),
        "sau_cli.py",
        "kuaishou",
        "upload-video",
        "--account",
        args.account,
        "--file",
        str(video_file),
        "--title",
        title,
        "--desc",
        description,
        "--tags",
        ",".join(tags),
        "--schedule",
        schedule,
        "--headless",
    ]
    if thumbnail and Path(thumbnail).is_file():
        upload_cmd += ["--thumbnail", str(Path(thumbnail).resolve())]
    upload = _run(upload_cmd, cwd=Path(args.sau_dir), env=env, timeout=args.timeout)
    (out_dir / "upload_stdout.log").write_text(upload.stdout, encoding="utf-8")
    (out_dir / "upload_stderr.log").write_text(upload.stderr, encoding="utf-8")
    if upload.returncode != 0:
        print(json.dumps({"ok": False, "stage": "upload", "out_dir": str(out_dir), "returncode": upload.returncode}, ensure_ascii=False, indent=2))
        return upload.returncode

    postcheck = _run(
        [str(Path(args.sau_python)), str(ROOT / "scripts" / "kuaishou_postcheck_manifest.py"), str(clean_manifest_path), str(out_dir / "postcheck")],
        cwd=ROOT,
        env=env,
        timeout=180,
    )
    (out_dir / "postcheck_stdout.log").write_text(postcheck.stdout, encoding="utf-8")
    (out_dir / "postcheck_stderr.log").write_text(postcheck.stderr, encoding="utf-8")
    report_path = out_dir / "postcheck" / "postcheck.json"
    passed = False
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        passed = postcheck.returncode == 0 and _postcheck_passed(report, clean_manifest)
    print(
        json.dumps(
            {
                "ok": passed,
                "stage": "complete" if passed else "postcheck",
                "out_dir": str(out_dir),
                "manifest": str(clean_manifest_path),
                "postcheck_report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
