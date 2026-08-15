#!/usr/bin/env python3
"""Send generated media as separate Hermes messages.

The target must be supplied through HERMES_DELIVERY_TARGET, for example
``telegram:<chat-id>``. The script intentionally does not contain account IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def _read_env_value(path: Path, keys: tuple[str, ...]) -> str:
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = raw.strip().partition("=")
        if separator and key.strip() in keys and value.strip():
            return value.strip().strip("'\"")
    return ""


def resolve_target(target: str = "") -> str:
    if target:
        return target.strip()
    for key in ("HERMES_DELIVERY_TARGET", "AI_SELF_MEDIA_TELEGRAM_TARGET"):
        if os.environ.get(key, "").strip():
            return os.environ[key].strip()
    env_file = Path(os.environ.get("HERMES_DELIVERY_ENV_FILE", Path(__file__).resolve().parents[1] / "secrets" / "notifications.env"))
    return _read_env_value(env_file, ("HERMES_DELIVERY_TARGET", "AI_SELF_MEDIA_TELEGRAM_TARGET"))


def _stage_for_hermes(path: Path, platform: str) -> Path:
    cache_root = Path(os.environ.get("HERMES_MEDIA_CACHE_DIR", Path.home() / ".hermes" / f"{platform}_media_cache"))
    cache_root.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    staged = cache_root / f"{path.stem}-{identity}{path.suffix.lower()}"
    if not staged.is_file() or staged.stat().st_size != path.stat().st_size:
        shutil.copy2(path, staged)
    return staged


def _send(target: str, message: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(["hermes", "send", "-t", target], input=message, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)[-200:]
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output[-200:]


def deliver(text: str, paths: list[str], target: str = "", platform: str = "media") -> dict:
    target = resolve_target(target)
    if not target:
        return {"passed": False, "error": "HERMES_DELIVERY_TARGET_missing", "sent": []}
    text_sent, text_error = _send(target, text.strip())
    if not text_sent:
        return {"passed": False, "error": "operator_text_delivery_failed", "detail": text_error, "sent": []}
    sent = []
    failures = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            failures.append({"path": str(path), "error": "file_missing"})
            continue
        staged = _stage_for_hermes(path, platform)
        ok, output = _send(target, f"MEDIA:{staged}")
        if ok:
            sent.append(str(staged))
        else:
            failures.append({"path": str(path), "error": output or "delivery_failed"})
    return {"passed": not failures, "target_kind": target.split(":", 1)[0], "text_sent": text_sent, "sent": sent, "failures": failures}


def deliver_xiaohongshu_package(package_path: Path, target: str = "") -> dict:
    try:
        package = json.loads(Path(package_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"passed": False, "error": "handoff_package_invalid_json", "sent": []}
    text = "\n".join(
        [
            "【小红书待手动发布】",
            "标题：" + str(package.get("title") or ""),
            "正文：" + str(package.get("body") or ""),
            "话题：" + " ".join(str(item) for item in package.get("topics") or []),
            "操作：" + str(package.get("manual_publish_guide") or ""),
        ]
    )
    return deliver(text, [str(item) for item in package.get("images") or []], target=target, platform="xhs")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one or more generated media files as independent Hermes MEDIA messages.")
    parser.add_argument("text")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--target", default="")
    args = parser.parse_args()
    result = deliver(args.text, args.paths, args.target)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
