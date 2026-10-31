"""Versioned, read-only platform profile registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "prompt_registry_v1"
# Lanes that share another platform's prompt profile (the compiler already mapped this one).
PROFILE_ALIASES = {"douyin_pet": "douyin_ai"}
_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "prompt_registry.json"


class PromptRegistry:
    """Load and validate a platform profile snapshot."""

    def __init__(self, payload: dict[str, Any], source: Path | None = None) -> None:
        self._payload = payload
        self.source = source
        self.version = str(payload.get("version", ""))
        self.policy_profile = str(payload.get("policy_profile", ""))
        self.policy_revision = str(payload.get("policy_revision", ""))
        platforms = payload.get("platforms")
        if self.version != REGISTRY_VERSION or not isinstance(platforms, dict) or not platforms:
            raise ValueError("invalid prompt registry snapshot")
        self._platforms = platforms
        for platform_id, profile in self._platforms.items():
            if not isinstance(profile, dict) or not str(profile.get("prompt_profile") or "").strip():
                raise ValueError(f"invalid platform profile: {platform_id}")
            if platform_id not in {"generic_image", "youtube_long_form", "youtube_shorts"}:
                if profile.get("policy_profile") != self.policy_profile or profile.get("policy_revision") != self.policy_revision:
                    raise ValueError(f"canonical policy mismatch for platform profile: {platform_id}")

    @classmethod
    def from_file(cls, path: str | Path) -> "PromptRegistry":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("prompt registry root must be an object")
        return cls(payload, source=source)

    @classmethod
    def from_default(cls) -> "PromptRegistry":
        return cls.from_file(_DEFAULT_PATH)

    def platform(self, platform_id: str) -> dict[str, Any]:
        try:
            profile = self._platforms[PROFILE_ALIASES.get(platform_id, platform_id)]
        except KeyError:
            raise KeyError(f"unknown platform profile: {platform_id}") from None
        if not isinstance(profile, dict):
            raise ValueError(f"invalid platform profile: {platform_id}")
        return dict(profile)

    def platform_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._platforms))
