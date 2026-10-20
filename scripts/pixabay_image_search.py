#!/usr/bin/env python3
"""Pixabay stock-image adapter with auditable provider metadata."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from content_platform.image_provider import ImageProviderError, generate_image, load_secret


def search_images(query: str, count: int = 1, min_width: int = 800, min_height: int = 400) -> list[dict]:
    if not load_secret("PIXABAY_API_KEY"):
        return []
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(max(1, int(count))):
            output = Path(tmp) / f"pixabay_{index + 1:02d}.jpg"
            try:
                record = generate_image(
                    query,
                    output,
                    provider="pixabay",
                    size=f"{max(min_width, 256)}x{max(min_height, 256)}",
                )
            except ImageProviderError:
                break
            results.append({
                "url": record.get("source_url", ""),
                "original_url": record.get("source_url", ""),
                "alt": query,
                "photographer": record.get("photographer", ""),
                "width": min_width,
                "height": min_height,
                "license": record.get("license", "Pixabay"),
                "license_verified": bool(record.get("license_verified", True)),
                "downloadable": output.is_file(),
                "provider": "pixabay",
                "query": record.get("query", query),
            })
            break
    return results


def get_images_for_article(topic: str, keywords: list[str] | None = None) -> list[dict]:
    terms = [str(topic or "").strip(), *[str(item).strip() for item in (keywords or []) if str(item).strip()]]
    query = " ".join(item for item in terms if item).strip() or "technology workspace"
    return search_images(query)


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "AI productivity workspace"
    print(json.dumps(get_images_for_article(topic), ensure_ascii=False, indent=2))
