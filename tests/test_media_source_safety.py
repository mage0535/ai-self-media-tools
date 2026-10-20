from __future__ import annotations


def test_router_default_excludes_paid_sources_and_maps_real_provider_names():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("image")
    names = [row["source"] for row in route]
    assert "gpt_image" not in names
    assert "pixazo" not in names
    assert next(row for row in route if row["source"] == "cloudflare_workers_ai")["provider"] == "cloudflare"


def test_router_paid_sources_require_explicit_flag():
    from content_platform.media_source_router import plan_source_route

    route = plan_source_route("ai_image", allow_paid=True)
    names = [row["source"] for row in route]
    assert "gpt_image" in names
    assert "pixazo" in names


def test_provider_chain_filters_paid_environment_override(monkeypatch):
    from content_platform.image_provider import _provider_chain

    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "openai,pollinations,pixazo")
    monkeypatch.delenv("IMAGE_PROVIDER_ALLOW_PAID", raising=False)
    assert _provider_chain("auto") == ["pollinations"]

    monkeypatch.setenv("IMAGE_PROVIDER_ALLOW_PAID", "1")
    assert _provider_chain("auto") == ["openai", "pollinations", "pixazo"]


def test_prompt_compiler_defaults_to_generic_image_profile():
    from content_platform.prompt_compiler import compile_prompt_bundle

    bundle = compile_prompt_bundle({"topic": "AI workspace", "constraints": ["no unrelated subject"]})
    assert bundle["input"]["platform"] == "generic_image"
    assert bundle["quality_contract"]["registry_version"] == "prompt_registry_v1"


def test_asset_cache_key_is_consumed_by_image_provider(monkeypatch):
    from content_platform import image_provider

    monkeypatch.setenv("IMAGE_PROVIDER_CACHE_DIR", "/tmp/image-provider-safety-test")
    key = image_provider._cache_key("topic", "pollinations", model="flux", size="1024x1024")
    assert len(key) == 24
