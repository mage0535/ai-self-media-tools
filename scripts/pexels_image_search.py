#!/usr/bin/env python3
"""Compatibility wrapper for stock image search.

New workflows should use `scripts/image_gen.py --provider stock`. This module
keeps the old Pexels search import surface alive while routing secret loading
and downloads through `content_platform.image_provider`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from content_platform.image_provider import ImageProviderError, generate_image, load_secret
from content_platform.search_contract import build_search_spec, score_candidate


def search_images(query: str, count: int = 3, min_width: int = 800, min_height: int = 400, *, include_evidence: bool = False) -> list[dict]:
    """Return stock-image records for legacy callers without exposing API keys."""
    if not load_secret("PEXELS_API_KEY"):
        return []
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(max(1, int(count))):
            output = Path(tmp) / f"stock_{index + 1:02d}.jpg"
            try:
                record = generate_image(query, output, provider="pexels", size=f"{max(min_width, 256)}x{max(min_height, 256)}")
            except ImageProviderError:
                break
            source_url = record.get("source_url", "")
            candidate = {
                "id": source_url,
                "title": query,
                "tags": query.split(),
                "width": min_width,
                "height": min_height,
                "license_verified": bool(record.get("license_verified", True)),
                "downloadable": output.is_file(),
            }
            aspect_ratio = "9:16" if min_height > min_width else "16:9"
            search_spec = build_search_spec(query, "generic_image", "real scene photo", aspect_ratio)
            candidate_score = score_candidate(candidate, search_spec)
            if include_evidence:
                if not candidate_score["passed"]:
                    continue
                result = {
                    "url": source_url,
                    "original_url": source_url,
                    "alt": query,
                    "photographer": record.get("photographer", ""),
                    "width": min_width,
                    "height": min_height,
                    "license": record.get("license", "Pexels"),
                    "license_verified": candidate["license_verified"],
                    "downloadable": candidate["downloadable"],
                    "search_spec": search_spec,
                    "candidate_score": candidate_score,
                }
            else:
                result = {
                    "url": source_url,
                    "original_url": source_url,
                    "alt": query,
                    "photographer": record.get("photographer", ""),
                    "width": min_width,
                    "height": min_height,
                    "license": record.get("license", "Pexels"),
                }
            results.append(result)
            # The unified provider intentionally returns the best match. Avoid
            # repeating the same result when this compatibility surface asks
            # for multiple images.
            break
    return results


def get_images_for_article(topic: str, keywords: list[str] | None = None) -> list[dict]:
    terms = [str(topic or "").strip(), *[str(item).strip() for item in (keywords or []) if str(item).strip()]]
    query = " ".join([item for item in terms if item]).strip() or "technology workspace"
    return search_images(query, count=2, include_evidence=True)


if __name__ == "__main__":
    import sys

    topic = sys.argv[1] if len(sys.argv) > 1 else "AI productivity workspace"
    print(json.dumps(get_images_for_article(topic), ensure_ascii=False, indent=2))
