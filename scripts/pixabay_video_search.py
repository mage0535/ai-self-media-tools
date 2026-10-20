#!/usr/bin/env python3
"""Pixabay stock-video search/download adapter with auditable provenance.

The Pixabay API requires result caching for 24 hours. This adapter caches the
JSON search response, downloads selected videos locally, and never exposes the
API key in returned metadata or logs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from content_platform.image_provider import ImageProviderError, load_secret


API_URL = "https://pixabay.com/api/videos/"
LICENSE_URL = "https://pixabay.com/service/license-summary/"
CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_RESULTS = 8
USER_AGENT = "ai-self-media-tools/pixabay-video/1.0"


def _cache_dir() -> Path:
    root = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    path = Path(os.environ.get("PIXABAY_CACHE_DIR", str(root / "data" / "cache" / "pixabay" / "videos")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(params: dict[str, str]) -> str:
    stable = urllib.parse.urlencode(sorted(params.items()))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _cached_response(params: dict[str, str]) -> dict[str, Any] | None:
    path = _cache_dir() / f"{_cache_key(params)}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at") or 0)
        if time.time() - fetched_at > CACHE_TTL_SECONDS:
            return None
        response = payload.get("response")
        return response if isinstance(response, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cached_response(params: dict[str, str], response: dict[str, Any]) -> None:
    path = _cache_dir() / f"{_cache_key(params)}.json"
    payload = {
        "version": "pixabay_video_search_cache_v1",
        "fetched_at": time.time(),
        "params": {key: value for key, value in params.items() if key != "key"},
        "response": response,
    }
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)


def _search_response(query: str, *, per_page: int, min_width: int, min_height: int, order: str) -> dict[str, Any]:
    key = load_secret("PIXABAY_API_KEY")
    if not key:
        raise ImageProviderError("PIXABAY_API_KEY is not configured")
    params = {
        "key": key,
        "q": " ".join(str(query or "").split())[:100],
        "lang": "en",
        "video_type": "all",
        "per_page": str(max(3, min(per_page, 200))),
        "min_width": str(max(0, int(min_width))),
        "min_height": str(max(0, int(min_height))),
        "safesearch": "true",
        "order": order if order in {"popular", "latest"} else "popular",
        "page": "1",
    }
    cached = _cached_response(params)
    if cached is not None:
        return cached
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:240]
        raise ImageProviderError(f"Pixabay video search failed: HTTP {exc.code} {detail}") from exc
    except (OSError, ValueError) as exc:
        raise ImageProviderError(f"Pixabay video search failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(body, dict):
        raise ImageProviderError("Pixabay video search returned an invalid JSON object")
    _write_cached_response(params, body)
    return body


def _select_rendition(hit: dict[str, Any], min_width: int, min_height: int) -> tuple[str, dict[str, Any]]:
    renditions = hit.get("videos") if isinstance(hit.get("videos"), dict) else {}
    candidates = [
        (name, item)
        for name, item in renditions.items()
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    ]
    if not candidates:
        raise ImageProviderError(f"Pixabay video {hit.get('id', '')} has no downloadable rendition")

    def score(pair: tuple[str, dict[str, Any]]) -> tuple[int, int, int]:
        name, item = pair
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        meets = int(width >= min_width and height >= min_height)
        rank = {"large": 4, "medium": 3, "small": 2, "tiny": 1}.get(name, 0)
        # Prefer the smallest rendition that satisfies the requested minimum;
        # otherwise choose the highest available resolution.
        distance = abs(width - min_width) + abs(height - min_height)
        return (meets, -distance if meets else width * height, rank)

    return max(candidates, key=score)


def _download_video(url: str, output: Path) -> None:
    download_url = url + ("&" if "?" in url else "?") + "download=1"
    request = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:180]
        raise ImageProviderError(f"Pixabay video download failed: HTTP {exc.code} {detail}") from exc
    except OSError as exc:
        raise ImageProviderError(f"Pixabay video download failed: {type(exc).__name__}: {exc}") from exc
    if len(payload) < 4096:
        raise ImageProviderError("downloaded Pixabay video was too small")
    # MP4 files normally contain the ftyp box at byte 4. Keep content-type as
    # a valid alternative because some CDN responses omit the signature check.
    if "video" not in content_type.casefold() and b"ftyp" not in payload[:32]:
        raise ImageProviderError(f"Pixabay download was not a video: {content_type}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output)


def search_videos(
    query: str,
    count: int = 1,
    *,
    min_width: int = 640,
    min_height: int = 360,
    output_dir: str | Path | None = None,
    order: str = "popular",
) -> list[dict[str, Any]]:
    """Search Pixabay videos and optionally download selected local copies.

    At most eight results are requested to avoid systematic mass downloads.
    Returned records are candidates; downstream semantic/license gates remain
    responsible for publish readiness.
    """
    query = " ".join(str(query or "").split()).strip()
    if not query:
        raise ImageProviderError("Pixabay video query is empty")
    count = max(1, min(int(count), MAX_RESULTS))
    body = _search_response(query, per_page=max(3, count * 2), min_width=min_width, min_height=min_height, order=order)
    hits = body.get("hits") or []
    if not isinstance(hits, list) or not hits:
        raise ImageProviderError("Pixabay video search returned no videos")

    root = Path(output_dir) if output_dir else None
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        video_id = str(hit.get("id") or "").strip()
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        rendition_name, rendition = _select_rendition(hit, min_width, min_height)
        record: dict[str, Any] = {
            "provider": "pixabay",
            "kind": "stock_video",
            "mode": "search_download" if root else "search",
            "video_id": video_id,
            "query": query,
            "source_url": str(hit.get("pageURL") or f"https://pixabay.com/videos/id-{video_id}/"),
            "download_url": str(rendition.get("url") or ""),
            "user": str(hit.get("user") or ""),
            "license": "Pixabay Content License",
            "license_url": LICENSE_URL,
            "license_verified": True,
            "rights_cleared": True,
            "duration": float(hit.get("duration") or 0),
            "dimensions": {
                "width": int(rendition.get("width") or 0),
                "height": int(rendition.get("height") or 0),
            },
            "rendition": rendition_name,
            "thumbnail_url": str(rendition.get("thumbnail") or ""),
            "semantic_match_score": None,
            "match_reason": "Pixabay candidate selected by query; downstream semantic gate required",
            "semantic_tags": [tag.strip() for tag in str(hit.get("tags") or "").split(",") if tag.strip()],
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if root:
            target = root / f"pixabay_{video_id}_{rendition_name}.mp4"
            _download_video(str(rendition["url"]), target)
            record["path"] = str(target)
            record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            record["bytes"] = target.stat().st_size
        results.append(record)
        if len(results) >= count:
            break
    if not results:
        raise ImageProviderError("Pixabay video search returned no usable videos")
    return results


def get_videos_for_video(topic: str, output_dir: str | Path, count: int = 1) -> list[dict[str, Any]]:
    return search_videos(topic, count=count, output_dir=output_dir, min_width=640, min_height=360)


def main() -> int:
    parser = argparse.ArgumentParser(description="Search and download Pixabay stock videos")
    parser.add_argument("query")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-width", type=int, default=640)
    parser.add_argument("--min-height", type=int, default=360)
    parser.add_argument("--order", choices=["popular", "latest"], default="popular")
    args = parser.parse_args()
    records = search_videos(
        args.query,
        count=args.count,
        min_width=args.min_width,
        min_height=args.min_height,
        output_dir=args.output_dir or None,
        order=args.order,
    )
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
