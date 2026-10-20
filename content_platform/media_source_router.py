"""Deterministic source routing; adapters execute the returned plan elsewhere."""

from __future__ import annotations

from .source_registry import SOURCES


def _row(name: str, reason: str) -> dict:
    profile = SOURCES[name]
    return {
        "source": name,
        "provider": profile.get("provider", name),
        "kind": profile["kind"],
        "mode": profile["mode"],
        "status": profile.get("status", "plan_only"),
        "selectable": profile.get("status") == "runtime_ready" and bool(profile.get("adapter")),
        "applies_to": list(profile.get("applies_to") or []),
        "adapter": profile.get("adapter"),
        "required_evidence": list(profile.get("required_evidence") or []),
        "license_gate": profile.get("license_gate"),
        "fallback": profile.get("fallback"),
        "free_first": bool(profile.get("free_first")),
        "license_required": bool(profile.get("license_required")),
        "reason": reason,
    }


def _filter(names: list[str], *, content_form: str, free_only: bool, allow_external: bool, allow_paid: bool) -> list[str]:
    result = []
    for name in names:
        profile = SOURCES[name]
        if profile.get("status") != "runtime_ready" or not profile.get("adapter"):
            continue
        if content_form and content_form not in (profile.get("applies_to") or []):
            continue
        if free_only and not profile.get("free_first"):
            continue
        if not allow_paid and profile.get("license_gate") == "explicit_paid_authorization":
            continue
        if not allow_external and profile.get("network") == "external_service":
            continue
        result.append(name)
    return result


def plan_source_route(
    kind: str,
    *,
    platform: str = "",
    user_url: bool = False,
    prefer_real: bool = True,
    free_only: bool = False,
    allow_external: bool = False,
    allow_paid: bool = False,
    content_form: str = "",
    quality_first: bool = False,
) -> list[dict]:
    """Return an ordered, auditable source route without invoking any adapter."""
    if kind == "image":
        if quality_first:
            names = ["gpt_image", "go_gemini_image", "sensenova", "cloudflare_workers_ai", "pollinations", "pexels", "pixabay", "wikimedia", "pixazo"]
        elif prefer_real:
            names = ["pexels", "pixabay", "wikimedia", "go_gemini_image", "cloudflare_workers_ai", "sensenova", "pollinations", "gpt_image", "pixazo"]
        else:
            names = ["go_gemini_image", "cloudflare_workers_ai", "sensenova", "pollinations", "pexels", "pixabay", "wikimedia", "gpt_image", "pixazo"]
        reasons = {
            "pexels": "real licensed stock image first",
            "pixabay": "real stock image/video fallback",
            "wikimedia": "open-media fallback with per-file license verification",
            "go_gemini_image": "validated go Gemini image generation/edit provider",
            "cloudflare_workers_ai": "free AI image fallback",
            "sensenova": "free-first AI image provider",
            "pollinations": "keyless AI image fallback",
            "gpt_image": "higher-control AI image fallback; paid/provider-dependent",
            "pixazo": "secondary AI image fallback",
        }
    elif kind == "video":
        names = ["user_url", "yt_dlp", "platform_native", "playwright_cli", "playwright_mcp", "apify_mcp"] if user_url else ["platform_native", "playwright_cli", "playwright_mcp", "apify_mcp"]
        reasons = {
            "user_url": "user-provided URL is the strongest source constraint",
            "yt_dlp": "download the confirmed source for local analysis",
            "platform_native": "verify platform-native sample and evidence",
            "playwright_cli": "low-token high-throughput browser collection",
            "playwright_mcp": "interactive browser exploration fallback",
            "apify_mcp": "external Actor fallback for hard-to-reach platforms",
        }
    elif kind == "stock_video":
        names = ["pixabay_video"]
        reasons = {"pixabay_video": "licensed Pixabay stock-video candidate for B-roll and scene coverage"}
    elif kind == "platform_sample":
        names = ["platform_native", "playwright_cli", "playwright_mcp", "apify_mcp"]
        reasons = {
            "platform_native": f"native {platform or 'target'} evidence first",
            "playwright_cli": "deterministic low-token browser collection",
            "playwright_mcp": "persistent interactive browser fallback",
            "apify_mcp": "external scraper fallback only after local/browser paths",
        }
    elif kind == "audio":
        names = ["archive_org_bgm"]
        reasons = {"archive_org_bgm": "licensed real-instrument BGM with fingerprint and fit evidence"}
    elif kind == "ai_image":
        names = ["go_gemini_image", "cloudflare_workers_ai", "sensenova", "pollinations", "gpt_image", "pixazo"]
        reasons = {
            "cloudflare_workers_ai": "free-first AI generation",
            "go_gemini_image": "validated go Gemini image generation/edit provider",
            "sensenova": "free-first high-quality generation",
            "pollinations": "keyless fallback",
            "gpt_image": "paid high-control generation",
            "pixazo": "secondary provider fallback",
        }
    else:
        raise ValueError(f"unsupported route kind: {kind}")
    selected = [_row(name, reasons[name]) for name in _filter(names, content_form=content_form, free_only=free_only, allow_external=allow_external, allow_paid=allow_paid)]
    # Research fallbacks without a real adapter remain visible as plan-only
    # candidates for auditability, but are explicitly non-selectable.
    if kind == "platform_sample":
        for name in names:
            if SOURCES[name].get("status") == "plan_only":
                selected.append(_row(name, reasons[name]))
    return selected
