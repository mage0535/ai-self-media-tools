def test_source_registry_includes_stock_browser_video_and_ai_generation_paths():
    from content_platform.source_registry import source, sources_by_kind

    assert source("cloudflare_workers_ai")["kind"] == "ai_image_generation"
    assert source("cloudflare_workers_ai")["provider"] == "cloudflare"
    assert source("gpt_image")["kind"] == "ai_image_generation"
    assert source("gpt_image")["provider"] == "openai"
    assert "pexels" in sources_by_kind("stock_image")
    assert "playwright_cli" in source("playwright_cli")["mode"] or source("playwright_cli")["mode"] == "search_evidence"
    assert "yt_dlp" in {row for row in ("yt_dlp", "user_url")}


def test_source_registry_rejects_unknown_source():
    import pytest
    from content_platform.source_registry import source

    with pytest.raises(KeyError):
        source("missing_source")
