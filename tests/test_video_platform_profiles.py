from __future__ import annotations

import pytest


CANONICAL_VIDEO_PROFILES = (
    "douyin_ai",
    "douyin_pet",
    "kuaishou",
    "shipinhao",
    "tiktok",
    "youtube_shorts",
    "youtube_long_form",
    "bilibili",
)


def test_every_canonical_video_platform_resolves_to_complete_profile() -> None:
    from content_platform.video_platform_profile import resolve_video_platform_profile

    for platform in CANONICAL_VIDEO_PROFILES:
        profile = resolve_video_platform_profile(platform)
        assert profile.id == platform
        assert profile.width > 0 and profile.height > 0
        assert profile.aspect_ratio in {"9:16", "16:9"}
        assert profile.language in {"zh-CN", "en"}
        assert 1 <= profile.beat_count_min <= profile.beat_count_max


def test_ambiguous_douyin_and_youtube_ids_fail_before_rendering() -> None:
    from content_platform.video_platform_profile import (
        AmbiguousVideoPlatform,
        resolve_video_platform_profile,
    )

    with pytest.raises(AmbiguousVideoPlatform, match="douyin_ai or douyin_pet"):
        resolve_video_platform_profile("douyin")
    with pytest.raises(AmbiguousVideoPlatform, match="youtube_shorts or youtube_long_form"):
        resolve_video_platform_profile("youtube")


def test_short_and_long_profiles_do_not_share_geometry_or_beat_contract() -> None:
    from content_platform.video_platform_profile import resolve_video_platform_profile

    shorts = resolve_video_platform_profile("youtube_shorts")
    long_form = resolve_video_platform_profile("youtube_long_form")

    assert (shorts.width, shorts.height) == (1080, 1920)
    assert (long_form.width, long_form.height) == (1280, 720)
    assert shorts.beat_count_range == (8, 8)
    assert long_form.beat_count_max > shorts.beat_count_max


def test_douyin_ai_and_pet_profiles_keep_distinct_lanes() -> None:
    from content_platform.video_platform_profile import resolve_video_platform_profile

    assert resolve_video_platform_profile("douyin_ai").lane == "real_world_ai_implementation"
    assert resolve_video_platform_profile("douyin_pet").lane == "pet"
