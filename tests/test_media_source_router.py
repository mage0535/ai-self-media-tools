from __future__ import annotations


def test_source_route_prefers_real_free_image_sources_before_ai_fallbacks():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("image", prefer_real=True, free_only=True)

    assert route[0]["source"] in {"pexels", "pixabay", "wikimedia"}
    assert all(row["source"] not in {"gpt_image", "pixazo"} for row in route)
    assert any(row["source"] == "cloudflare_workers_ai" for row in route)
    assert all(row["reason"] for row in route)


def test_source_route_user_url_starts_with_ingest_and_ytdlp():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("video", user_url=True, platform="tiktok")
    names = [row["source"] for row in route]

    assert names[:2] == ["user_url", "yt_dlp"]
    assert "apify_mcp" not in names


def test_source_route_platform_research_uses_cli_before_mcp_and_paid_fallback():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("platform_sample", platform="douyin_ai", allow_external=True)
    names = [row["source"] for row in route]

    assert names[:3] == ["platform_native", "playwright_cli", "playwright_mcp"]
    assert names[-1] == "apify_mcp"


def test_quality_first_image_route_explicitly_promotes_openai():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("image", quality_first=True, allow_paid=True, content_form="cover")
    names = [row["source"] for row in route]

    assert names[0] == "gpt_image"
    assert route[0]["provider"] == "openai"
    assert route[0]["selectable"] is True


def test_quality_first_does_not_bypass_paid_authorization():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("image", quality_first=True, allow_paid=False, content_form="cover")
    names = [row["source"] for row in route]

    assert names[0] != "gpt_image"
    assert "gpt_image" not in names


def test_source_route_exposes_validated_go_gemini_provider():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("ai_image")
    go = next(row for row in route if row["source"] == "go_gemini_image")

    assert go["status"] == "runtime_ready"
    assert go["selectable"] is True
    assert go["provider"] == "go_gemini"
