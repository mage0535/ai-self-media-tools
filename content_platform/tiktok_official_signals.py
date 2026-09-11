from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


CREATIVE_CENTER_PAGE = "https://ads.tiktok.com/creative/creativeCenter/trends/video?countryCode=US&period=30"
OVERVIEW_URL = "https://ads.tiktok.com/CreativeOne/Report/GetTopContentsOverview"
TOP_VIDEOS_URL = "https://ads.us.tiktok.com/CreativeOne/Report/CreativeCenterGetTopContentsList"
TECH_FINANCE_LABEL = 11015


def parse_creative_center_top_videos(
    payload: dict[str, Any],
    *,
    captured_at: str,
    source_url: str,
    snapshot_sha256: str,
) -> dict[str, Any]:
    failures: list[str] = []
    parsed_url = urlparse(source_url)
    if parsed_url.hostname not in {"ads.tiktok.com", "ads.us.tiktok.com"} or "CreativeCenterGetTopContentsList" not in parsed_url.path:
        failures.append("creative_center_source_url_invalid")
    if len(str(snapshot_sha256 or "")) != 64:
        failures.append("snapshot_sha256_missing")
    base = payload.get("BaseResp") if isinstance(payload.get("BaseResp"), dict) else {}
    if int(base.get("StatusCode") or 0) != 0:
        failures.append("creative_center_api_failed")
    try:
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        captured = captured.astimezone(timezone.utc)
    except ValueError:
        captured = datetime.now(timezone.utc)
        failures.append("captured_at_invalid")

    details = []
    for rank, entity in enumerate(payload.get("entityInfos") or [], 1):
        if not isinstance(entity, dict):
            continue
        info = entity.get("itemInfo") if isinstance(entity.get("itemInfo"), dict) else {}
        metrics = entity.get("itemMetrics") if isinstance(entity.get("itemMetrics"), dict) else {}
        author = entity.get("itemAuthorInfo") if isinstance(entity.get("itemAuthorInfo"), dict) else {}
        item_id = str(info.get("itemID") or "").strip()
        title = str(info.get("title") or "").strip()
        handle = str(author.get("handlerName") or "").strip().lstrip("@")
        created = int(info.get("createTime") or 0)
        views = int(metrics.get("videoViews") or 0)
        labels = [
            str(tag.get("contentLabelName") or "")
            for tag in entity.get("contentTags") or []
            if isinstance(tag, dict) and int(tag.get("contentLabelID") or 0) == TECH_FINANCE_LABEL
        ]
        if not (item_id.isdigit() and title and handle and created > 0 and views > 0 and labels):
            continue
        published = datetime.fromtimestamp(created, tz=timezone.utc)
        if published > captured + timedelta(hours=1) or captured - published > timedelta(days=30):
            continue
        details.append({
            "rank": rank,
            "title": title[:300],
            "content_id": item_id,
            "canonical_url": f"https://www.tiktok.com/@{handle}/video/{item_id}",
            "author_id_hash": hashlib.sha256(f"tiktok:{handle.casefold()}".encode("utf-8")).hexdigest(),
            "published_at": published.isoformat(),
            "metrics": {
                "views": views,
                "organic_views": int(metrics.get("organicVideoViews") or 0),
                "engagement_rate": float(metrics.get("engagementRate") or 0),
                "six_second_vtr": float(metrics.get("sixSecondsVTR") or 0),
            },
            "content_labels": labels,
        })
    if not details:
        failures.append("creative_center_top_videos_missing")

    pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
    public_preview = int(pagination.get("limit") or len(details)) <= 4 and int(pagination.get("totalCount") or 0) > len(details)
    row = {
        "platform": "tiktok",
        "status": "verified",
        "signal_type": "official_trending_videos",
        "evidence_type": "official_reference",
        "signals": [item["title"] for item in details],
        "signal_details": details,
        "official_url": CREATIVE_CENTER_PAGE,
        "final_url": source_url,
        "captured_at": captured.isoformat(),
        "expires_at": (captured + timedelta(hours=12)).isoformat(),
        "evidence_sha256": snapshot_sha256,
        "raw_snapshot_sha256": snapshot_sha256,
        "collector": "tiktok_creative_center_top_videos",
        "native_verified": False,
        "access_level": "public_preview" if public_preview else "authenticated",
        "content_label_id": TECH_FINANCE_LABEL,
        "content_label": "Technology & Finance",
    }
    return {"passed": not failures, "failures": failures, "matrix_row": row if not failures else {}}


def collect_tiktok_creative_center_signals(
    output_dir: str | Path,
    *,
    state_file: str | Path | None = None,
    fetch_json: Callable[..., dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import requests

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(timezone.utc)
    session = requests.Session()
    state_used = False
    if state_file and Path(state_file).is_file():
        try:
            state = json.loads(Path(state_file).read_text(encoding="utf-8"))
            for cookie in state.get("cookies") or []:
                if not isinstance(cookie, dict) or not cookie.get("name") or not cookie.get("value"):
                    continue
                session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path") or "/"
                )
            state_used = bool(state.get("cookies"))
        except (OSError, ValueError, TypeError):
            state_used = False
    headers = {"User-Agent": "Mozilla/5.0", "Referer": CREATIVE_CENTER_PAGE}

    def default_fetch(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = session.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("creative_center_response_not_object")
        return payload

    fetch = fetch_json or default_fetch
    try:
        overview = fetch(OVERVIEW_URL)
        end_timestamp = int(overview.get("lastDailyEndTimestamp") or 0)
        if end_timestamp > 1_000_000_000_000:
            end_timestamp //= 1000
        payload = fetch(
            TOP_VIDEOS_URL,
            params={
                "periodDimension": 5,
                "periodEndTimestamp": str(end_timestamp),
                "orderByMetric": 1,
                "countryCode": "US",
                "contentLabelIDs": str(TECH_FINANCE_LABEL),
                "organicOnly": "false",
                "limit": 100,
                "page": 1,
            },
        )
    except Exception as exc:
        return {}, {
            "source": "tiktok:official_creative_center",
            "status": "failed",
            "count": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
            "state_used": state_used,
        }

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot_sha = hashlib.sha256(raw).hexdigest()
    snapshot = output / "creative_center_top_videos.json"
    temporary = snapshot.with_name(f".{snapshot.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(raw)
        temporary.chmod(0o600)
        os.replace(temporary, snapshot)
    finally:
        temporary.unlink(missing_ok=True)
    parsed = parse_creative_center_top_videos(
        payload,
        captured_at=captured.isoformat(),
        source_url=TOP_VIDEOS_URL,
        snapshot_sha256=snapshot_sha,
    )
    row = parsed.get("matrix_row") or {}
    return row, {
        "source": "tiktok:official_creative_center",
        "status": "ok" if row else "contract_failed",
        "count": len(row.get("signal_details") or []),
        "access_level": row.get("access_level", ""),
        "state_used": state_used,
        "snapshot_sha256": snapshot_sha,
        "failures": parsed.get("failures") or [],
    }
