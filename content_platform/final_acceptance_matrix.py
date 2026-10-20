"""Offline full-platform acceptance matrix.

This is the shared contract used before any receipt can be considered a
completion.  It describes the required local artifact evidence without
performing a platform call.
"""
from __future__ import annotations

PLATFORM_ACCEPTANCE_MATRIX = {
    "douyin_ai": {"kind": "video", "renderer": "video_toolchain", "postcheck": "management_or_manual_receipt"},
    "douyin_pet": {"kind": "video", "renderer": "video_toolchain", "postcheck": "management_or_manual_receipt", "lane": "pet"},
    "shipinhao": {"kind": "video", "renderer": "video_toolchain", "postcheck": "management_page"},
    "tiktok": {"kind": "video", "renderer": "video_toolchain", "postcheck": "platform_receipt_or_handoff"},
    "youtube_long_form": {"kind": "video", "renderer": "video_toolchain", "postcheck": "youtube_receipt_or_handoff"},
    "youtube_shorts": {"kind": "video", "renderer": "video_toolchain", "postcheck": "youtube_receipt_or_handoff"},
    "bilibili": {"kind": "video", "renderer": "video_toolchain", "postcheck": "platform_receipt_or_handoff"},
    "xiaohongshu": {"kind": "article", "renderer": "image_renderer", "postcheck": "manual_handoff"},
    "kuaishou": {"kind": "video", "renderer": "video_toolchain", "postcheck": "management_page"},
    "twitter": {"kind": "micro", "renderer": "text_renderer", "postcheck": "platform_receipt"},
    "x": {"kind": "micro", "renderer": "text_renderer", "postcheck": "platform_receipt"},
    "wechat": {"kind": "article", "renderer": "wechat_renderer", "postcheck": "draft_batchget"},
    "wechat_newspic": {"kind": "article", "renderer": "wechat_renderer", "postcheck": "draft_batchget"},
    "zhihu": {"kind": "article", "renderer": "markdown_renderer", "postcheck": "draft_identity_and_images"},
    "juejin": {"kind": "article", "renderer": "markdown_renderer", "postcheck": "draft_receipt"},
}


def normalize_platform(platform: str) -> str:
    value = str(platform or "").strip().casefold().replace("-", "_")
    return {"twitter_x": "x", "youtube": "youtube_long_form", "weixin": "wechat", "wechat_official": "wechat"}.get(value, value)


def validate_platform_acceptance(platform: str, packet: dict, *, receipt: dict | None = None) -> dict:
    key = normalize_platform(platform)
    contract = PLATFORM_ACCEPTANCE_MATRIX.get(key)
    failures = []
    if not contract:
        failures.append("platform_not_in_acceptance_matrix")
        return {"passed": False, "platform": key, "failures": failures}
    if str(packet.get("platform") or "").casefold() not in {key, platform.casefold(), "youtube", "wechat"}:
        failures.append("platform_identity_mismatch")
    for field in ("artifact_manifest", "renderer", "quality_gate"):
        if not packet.get(field):
            failures.append(f"{field}_missing")
    if contract["kind"] == "video":
        video = packet.get("video") or {}
        for field in ("aspect_ratio", "duration", "audio_track", "subtitle", "cover"):
            if not video.get(field):
                failures.append(f"video_{field}_missing")
    elif contract["kind"] == "article":
        if not packet.get("cover"):
            failures.append("cover_missing")
        if len(packet.get("inline_images") or []) < 3 and key == "zhihu":
            failures.append("inline_images_minimum_missing")
    if contract["postcheck"] != "manual_handoff" and not (receipt or {}).get("postcheck_verified"):
        failures.append("platform_postcheck_receipt_missing")
    if key in {"douyin_ai", "douyin_pet"} and packet.get("lane") not in {key.removeprefix("douyin_") , "ai", "pet"}:
        failures.append("douyin_lane_isolation_missing")
    return {"passed": not failures, "platform": key, "contract": contract, "failures": failures}
