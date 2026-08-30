#!/usr/bin/env python3
"""Smoke-test configured image providers without exposing credentials."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.image_provider import ImageProviderError, generate_image, load_secret


def _provider_config_status(provider: str) -> str:
    if provider in {"auto", "pollinations"}:
        return "configured"
    if provider == "cloudflare":
        if load_secret("CF_WORKER_URL") or load_secret("CLOUDFLARE_IMAGE_WORKER_URL"):
            return "configured"
        if load_secret("CLOUDFLARE_ACCOUNT_ID") and (
            load_secret("CLOUDFLARE_API_TOKEN") or load_secret("CF_WORKER_KEY")
        ):
            return "configured"
        return "missing_config"
    if provider == "pexels":
        return "configured" if load_secret("PEXELS_API_KEY") else "missing_config"
    if provider == "pixabay":
        return "configured" if load_secret("PIXABAY_API_KEY") else "missing_config"
    if provider in {"sense_nova", "sensenova"}:
        return "configured" if (load_secret("SN_API_KEY") or load_secret("SENSENOVA_API_KEY")) else "missing_config"
    if provider == "pixazo":
        return "configured" if load_secret("PIXAZO_API_KEY") else "missing_config"
    if provider == "stock":
        return "configured" if (load_secret("PEXELS_API_KEY") or load_secret("PIXABAY_API_KEY")) else "missing_config"
    return "unknown_provider"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test image provider chain")
    parser.add_argument("--providers", default="stock,sense_nova,pixazo,cloudflare,pollinations,auto")
    parser.add_argument("--output-dir", default="/tmp/image-provider-smoke")
    parser.add_argument("--size", default="768x768")
    parser.add_argument("--prompt", default="clean editorial illustration of automated content production, no text")
    parser.add_argument("--intent", default="editorial_illustration")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for provider in [p.strip() for p in args.providers.split(",") if p.strip()]:
        status = _provider_config_status(provider)
        item = {"provider": provider, "config": status}
        if status == "missing_config":
            item["ok"] = False
            item["reason"] = "missing_config"
            results.append(item)
            continue
        output = output_dir / f"{provider.replace(',', '_')}.png"
        start = time.time()
        try:
            result = generate_image(args.prompt, output, provider=provider, size=args.size, intent=args.intent)
            item.update(
                {
                    "ok": True,
                    "selected_provider": result.get("provider", provider),
                    "model": result.get("model", ""),
                    "bytes": output.stat().st_size,
                    "cache_hit": bool(result.get("cache_hit")),
                    "elapsed_sec": round(time.time() - start, 2),
                    "path": str(output),
                }
            )
        except (ImageProviderError, OSError) as exc:
            item.update({"ok": False, "reason": type(exc).__name__, "message": str(exc)[:220]})
        results.append(item)
    any_passed = any(item.get("ok") for item in results)
    all_passed = bool(results) and all(item.get("ok") for item in results)
    report = {"ok": all_passed if args.require_all else any_passed, "all_requested_passed": all_passed, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
