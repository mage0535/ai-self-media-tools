"""Unified search and media-generation source registry."""

from __future__ import annotations

SOURCES = {
    "pexels": {"kind": "stock_image", "mode": "search_download", "status": "runtime_ready", "applies_to": ["article", "cover", "inline_image", "short_video", "long_video"], "adapter": "scripts/pexels_image_search.py", "required_evidence": ["source_url", "license", "semantic_match_score", "dimensions", "sha256"], "license_gate": "verified_stock_license", "fallback": "pixabay", "free_first": True, "license_required": True, "network": "direct"},
    "pixabay": {"kind": "stock_image_video", "mode": "search_download", "status": "runtime_ready", "applies_to": ["article", "cover", "inline_image", "short_video", "long_video"], "adapter": "scripts/pixabay_image_search.py + scripts/pixabay_video_search.py", "required_evidence": ["source_url", "license", "semantic_match_score", "dimensions", "sha256"], "license_gate": "verified_stock_license", "fallback": "pexels", "free_first": True, "license_required": True, "network": "direct"},
    "pixabay_video": {"kind": "stock_video", "mode": "search_download", "status": "runtime_ready", "applies_to": ["short_video", "long_video"], "adapter": "scripts/pixabay_video_search.py", "required_evidence": ["source_url", "license", "duration", "dimensions", "sha256"], "license_gate": "verified_stock_license", "fallback": "pixabay", "free_first": True, "license_required": True, "network": "direct", "provider": "pixabay"},
    "pollinations": {"kind": "ai_image_generation", "mode": "generate", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "semantic_match_score", "dimensions", "sha256"], "license_gate": "provider_terms_recorded", "fallback": "cloudflare_workers_ai", "free_first": True, "license_required": False, "network": "direct", "provider": "pollinations", "models": ["flux"]},
    "cloudflare_workers_ai": {"kind": "ai_image_generation", "mode": "generate", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "semantic_match_score", "dimensions", "sha256"], "license_gate": "provider_terms_recorded", "fallback": "sensenova", "free_first": True, "license_required": False, "network": "direct", "provider": "cloudflare", "models": ["@cf/black-forest-labs/flux-1-schnell"]},
    "sensenova": {"kind": "ai_image_generation", "mode": "generate", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "semantic_match_score", "dimensions", "sha256"], "license_gate": "provider_terms_recorded", "fallback": "pollinations", "free_first": True, "license_required": False, "network": "direct", "provider": "sense_nova", "models": ["sensenova-u1.5-lite"]},
    "gpt_image": {"kind": "ai_image_generation", "mode": "generate", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "paid_authorization", "semantic_match_score", "dimensions", "sha256"], "license_gate": "explicit_paid_authorization", "fallback": "sensenova", "free_first": False, "license_required": True, "network": "direct", "provider": "openai", "models": ["gpt-image-1", "gpt-image-1.5", "gpt-image-2"]},
    "go_gemini_image": {"kind": "ai_image_generation", "mode": "generate_and_edit", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "semantic_match_score", "dimensions", "sha256"], "license_gate": "provider_account_terms_recorded", "fallback": "sensenova", "free_first": False, "license_required": True, "network": "direct", "provider": "go_gemini", "protocol": "chat_completions_images", "models": ["gemini-3.1-flash-image"]},
    "pixazo": {"kind": "ai_image_generation", "mode": "generate", "status": "runtime_ready", "applies_to": ["cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.image_provider", "required_evidence": ["generation_evidence", "paid_authorization", "semantic_match_score", "dimensions", "sha256"], "license_gate": "explicit_paid_authorization", "fallback": "sensenova", "free_first": False, "license_required": True, "network": "direct", "provider": "pixazo"},
    "user_url": {"kind": "user_provided_media", "mode": "url_ingest", "status": "runtime_ready", "applies_to": ["article", "cover", "inline_image", "short_video", "long_video"], "adapter": "content_platform.media_source_router:user_url", "required_evidence": ["source_url", "user_authorization", "dimensions", "sha256"], "license_gate": "user_rights_assertion", "fallback": "yt_dlp", "free_first": True, "license_required": True, "network": "route_by_platform"},
    "yt_dlp": {"kind": "video_source", "mode": "url_download", "status": "runtime_ready", "applies_to": ["short_video", "long_video"], "adapter": "yt-dlp", "required_evidence": ["source_url", "user_authorization", "media_probe", "sha256"], "license_gate": "user_rights_assertion", "fallback": "platform_native", "free_first": True, "license_required": True, "network": "platform_specific"},
    "platform_native": {"kind": "platform_sample", "mode": "browser_or_api", "status": "runtime_ready", "applies_to": ["article", "short_video", "long_video"], "adapter": "content_platform.performance_cycle", "required_evidence": ["source_url", "platform_evidence", "dimensions"], "license_gate": "platform_terms_recorded", "fallback": None, "free_first": True, "license_required": True, "network": "platform_specific"},
    "wikimedia": {"kind": "open_media", "mode": "search_download", "status": "plan_only", "applies_to": ["article", "cover", "inline_image"], "adapter": None, "required_evidence": ["source_url", "per_file_license", "semantic_match_score", "dimensions", "sha256"], "license_gate": "per_file_license_verification", "fallback": None, "free_first": True, "license_required": True, "network": "direct"},
    "playwright_cli": {"kind": "browser_research", "mode": "search_evidence", "status": "plan_only", "applies_to": ["article", "short_video", "long_video"], "adapter": None, "required_evidence": ["source_url", "capture_evidence"], "license_gate": "not_media_asset_source", "fallback": None, "free_first": True, "license_required": False, "network": "platform_specific"},
    "playwright_mcp": {"kind": "browser_research", "mode": "exploration_and_interaction", "status": "plan_only", "applies_to": ["article", "short_video", "long_video"], "adapter": None, "required_evidence": ["source_url", "capture_evidence"], "license_gate": "not_media_asset_source", "fallback": None, "free_first": True, "license_required": False, "network": "platform_specific"},
    "apify_mcp": {"kind": "external_search_scraper", "mode": "actor_fallback", "status": "plan_only", "applies_to": ["article", "short_video", "long_video"], "adapter": None, "required_evidence": ["source_url", "capture_evidence"], "license_gate": "not_media_asset_source", "fallback": None, "free_first": False, "license_required": True, "network": "external_service"},
    "archive_org_bgm": {"kind": "audio_bgm", "mode": "download", "status": "runtime_ready", "applies_to": ["short_video", "long_video"], "adapter": "scripts/fetch_bgm_archive.py", "required_evidence": ["source_url", "license", "fingerprint", "sha256", "fit_reason"], "license_gate": "license_recorded", "fallback": None, "free_first": True, "license_required": True, "network": "external_service"},
}



def source(name: str) -> dict:
    try:
        return dict(SOURCES[name])
    except KeyError:
        raise KeyError(f"unknown media source: {name}") from None


def sources_by_kind(kind: str) -> tuple[str, ...]:
    return tuple(name for name, profile in SOURCES.items() if profile["kind"] == kind)


def source_checklist() -> list[dict]:
    return [{"name": name, **profile} for name, profile in SOURCES.items()]


def validate_source_evidence(name: str, evidence: dict) -> dict:
    """Fail closed before an adapter result can enter a content packet."""
    profile = source(name)
    evidence = evidence if isinstance(evidence, dict) else {}
    missing = [field for field in profile.get("required_evidence", []) if not evidence.get(field)]
    if profile.get("status") != "runtime_ready":
        missing.append("runtime_adapter_unavailable")
    if not profile.get("adapter"):
        missing.append("adapter_missing")
    return {"passed": not missing, "source": name, "missing": sorted(set(missing))}


