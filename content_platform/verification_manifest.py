"""Persisted, scope-aware evidence for test and verification runs."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


class InvalidVerificationManifest(ValueError):
    pass


def new_verification_manifest(*, command: str, scope: str, selected_files: list[str], passed: int, failed: int, skipped: int = 0) -> dict:
    if scope not in {"targeted", "full"}:
        raise InvalidVerificationManifest("scope must be targeted or full")
    return {
        "version": "verification_manifest_v1",
        "created_at": time.time(),
        "command": str(command),
        "scope": scope,
        "selected_files": [str(item) for item in selected_files],
        "counts": {"passed": int(passed), "failed": int(failed), "skipped": int(skipped)},
        "status": "passed" if int(failed) == 0 else "failed",
    }


def validate_verification_manifest(manifest: dict) -> dict:
    required = ("version", "created_at", "command", "scope", "selected_files", "counts", "status")
    missing = [field for field in required if field not in manifest]
    if missing:
        raise InvalidVerificationManifest(f"missing verification fields: {','.join(missing)}")
    if manifest["version"] != "verification_manifest_v1" or manifest["scope"] not in {"targeted", "full"}:
        raise InvalidVerificationManifest("verification identity or scope is invalid")
    if not str(manifest["command"]).strip() or not isinstance(manifest["selected_files"], list):
        raise InvalidVerificationManifest("verification command and selected files are required")
    counts = manifest["counts"]
    if not isinstance(counts, dict) or any(int(counts.get(key, -1)) < 0 for key in ("passed", "failed", "skipped")):
        raise InvalidVerificationManifest("verification counts are invalid")
    expected = "passed" if int(counts["failed"]) == 0 else "failed"
    if manifest["status"] != expected:
        raise InvalidVerificationManifest("verification status does not match failure count")
    return {"passed": True, "manifest": manifest}


def write_verification_manifest(path: Path, manifest: dict) -> None:
    validate_verification_manifest(manifest)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)