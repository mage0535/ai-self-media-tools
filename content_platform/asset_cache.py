"""Small, deterministic content-addressed cache key helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

CACHE_KEY_VERSION = "cache_key_v1"
_ALLOWED_KINDS = {"prompt", "asset", "render"}


def build_cache_key(kind: str, fields: Mapping[str, object]) -> str:
    """Build a typed key; all meaningful inputs must be supplied by the caller."""
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unsupported cache kind: {kind}")
    payload = {
        "version": CACHE_KEY_VERSION,
        "kind": kind,
        "fields": dict(fields),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cache_path(root: str | Path, kind: str, key: str, suffix: str = "") -> Path:
    """Return a bounded cache path without interpreting user-controlled segments."""
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unsupported cache kind: {kind}")
    if len(key) != 24 or any(char not in "0123456789abcdef" for char in key):
        raise ValueError("key must be a 24-character lowercase hex digest")
    safe_suffix = suffix if suffix.startswith(".") or suffix == "" else f".{suffix}"
    return Path(root).resolve() / kind / f"{key}{safe_suffix}"
