#!/usr/bin/env python3
"""Fail-closed BGM fingerprint gate for generated videos."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from content_platform.paths import project_home
except Exception:  # pragma: no cover - script fallback when PYTHONPATH is absent.
    def project_home() -> Path:
        import os

        configured = os.environ.get("CONTENT_PLATFORM_HOME", "").strip()
        return Path(configured) if configured else Path(__file__).resolve().parents[1]


def _default_registry() -> Path:
    import os

    configured = os.environ.get("BGM_FINGERPRINT_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    return project_home() / "data" / "bgm_fingerprint_registry.json"


def _mean_volume(path: Path) -> float | None:
    result = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=60)
    match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", result.stderr + "\n" + result.stdout)
    return float(match.group(1)) if match else None


def _load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else default
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON registry: {path}") from exc


def check(render_dir: Path, platform: str = "", registry_path: Path | None = None, register: bool = True) -> dict:
    render_dir = render_dir.resolve()
    source_path = render_dir / "bgm_source.json"
    bgm_path = render_dir / "bgm.mp3"
    registry = registry_path or _default_registry()
    failures: list[str] = []

    if not source_path.is_file():
        failures.append("bgm_source_json_missing")
        source = {}
    else:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    fingerprint = str(source.get("sha256") or (source.get("manifest") or {}).get("fingerprint") or "").strip()
    title = str(source.get("title") or "").strip()
    source_url = str(source.get("source_url") or "").strip()

    if not fingerprint:
        failures.append("bgm_fingerprint_missing")
    if not source_url:
        failures.append("bgm_source_url_missing")
    if not bgm_path.is_file() or bgm_path.stat().st_size < 50_000:
        failures.append("bgm_file_missing_or_too_small")
        volume = None
    else:
        volume = _mean_volume(bgm_path)
        if volume is None or volume <= -40:
            failures.append("bgm_silent_or_unreadable")

    data = _load_json(registry, {"tracks": []})
    tracks = data.get("tracks") if isinstance(data.get("tracks"), list) else []
    duplicate = None
    if fingerprint:
        duplicate = next((row for row in tracks if isinstance(row, dict) and str(row.get("fingerprint") or row.get("sha256") or "") == fingerprint), None)
    if duplicate:
        failures.append("bgm_fingerprint_duplicate")

    result = {
        "passed": not failures,
        "failed_dimensions": failures,
        "platform": platform,
        "render_dir": str(render_dir),
        "registry_path": str(registry),
        "fingerprint": fingerprint,
        "title": title,
        "source_url": source_url,
        "mean_volume_db": volume,
        "duplicate": duplicate or {},
    }
    if result["passed"] and register:
        tracks.append(
            {
                "fingerprint": fingerprint,
                "title": title,
                "source_url": source_url,
                "license": source.get("license", ""),
                "platform": platform,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        data["tracks"] = tracks[-500:]
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check and optionally register a generated video's BGM fingerprint.")
    parser.add_argument("render_dir")
    parser.add_argument("--platform", default="")
    parser.add_argument("--registry", default="")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()
    result = check(Path(args.render_dir), args.platform, Path(args.registry).expanduser() if args.registry else None, not args.no_register)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
