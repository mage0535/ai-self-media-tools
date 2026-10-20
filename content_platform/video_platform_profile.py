"""Canonical, data-driven profiles for generated video platforms."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownVideoPlatform(ValueError):
    """Raised when a platform has no generated-video profile."""


class AmbiguousVideoPlatform(UnknownVideoPlatform):
    """Raised when a coarse platform id loses lane or format identity."""


@dataclass(frozen=True, slots=True)
class VideoPlatformProfile:
    id: str
    format_profile: str
    language: str
    aspect_ratio: str
    width: int
    height: int
    beat_count_min: int
    beat_count_max: int
    lane: str

    @property
    def beat_count_range(self) -> tuple[int, int]:
        return self.beat_count_min, self.beat_count_max


_PROFILES = {
    "douyin_ai": VideoPlatformProfile("douyin_ai", "vertical_short", "zh-CN", "9:16", 720, 1280, 8, 8, "real_world_ai_implementation"),
    "douyin_pet": VideoPlatformProfile("douyin_pet", "vertical_short", "zh-CN", "9:16", 720, 1280, 8, 8, "pet"),
    "kuaishou": VideoPlatformProfile("kuaishou", "vertical_short", "zh-CN", "9:16", 1080, 1920, 8, 8, "real_world_ai_implementation"),
    "shipinhao": VideoPlatformProfile("shipinhao", "vertical_trust", "zh-CN", "9:16", 720, 1280, 8, 8, "real_world_ai_implementation"),
    "tiktok": VideoPlatformProfile("tiktok", "vertical_short", "en", "9:16", 1080, 1920, 8, 8, "real_world_ai_implementation"),
    "youtube_shorts": VideoPlatformProfile("youtube_shorts", "vertical_short", "en", "9:16", 1080, 1920, 8, 8, "real_world_ai_implementation"),
    "youtube_long_form": VideoPlatformProfile("youtube_long_form", "landscape_long", "en", "16:9", 1280, 720, 8, 24, "real_world_ai_implementation"),
    "bilibili": VideoPlatformProfile("bilibili", "landscape_long", "zh-CN", "16:9", 1280, 720, 8, 24, "real_world_ai_implementation"),
}

_AMBIGUOUS = {
    "douyin": "douyin is ambiguous; choose douyin_ai or douyin_pet",
    "youtube": "youtube is ambiguous; choose youtube_shorts or youtube_long_form",
}


def resolve_video_platform_profile(platform_id: str) -> VideoPlatformProfile:
    key = str(platform_id or "").strip().casefold().replace("-", "_")
    if key in _AMBIGUOUS:
        raise AmbiguousVideoPlatform(_AMBIGUOUS[key])
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise UnknownVideoPlatform(f"video platform profile not found: {key or '<empty>'}") from exc


def canonical_video_platform_ids() -> tuple[str, ...]:
    return tuple(_PROFILES)
