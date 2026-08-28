"""Compile verified WeChat first-party signals into the official matrix contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SOURCE_KINDS = {"wewrite_hotspots", "creator_backend"}
WECHAT_HOSTS = {"mp.weixin.qq.com", "weixin.qq.com"}
SOGOU_HOSTS = {"sogou.com", "weixin.sogou.com", "www.sogou.com"}
KEYWORD_KEYS = ("search_queries", "search_keywords", "keywords")
ACTIVITY_KEYS = ("activities", "campaigns", "events")


def _rows(payload: Any, source_kind: str) -> list[tuple[dict[str, Any], str]]:
    if isinstance(payload, list):
        return [(row, "") for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if source_kind == "creator_backend":
        rows: list[tuple[dict[str, Any], str]] = []
        for key in KEYWORD_KEYS:
            values = payload.get(key)
            if isinstance(values, list):
                rows.extend((row, "official_keyword") for row in values if isinstance(row, dict))
        for key in ACTIVITY_KEYS:
            values = payload.get(key)
            if isinstance(values, list):
                rows.extend((row, "official_activity") for row in values if isinstance(row, dict))
        if rows:
            return rows
    values = payload.get("items", payload.get("hotspots", payload.get("results", [])))
    return [(row, "") for row in values if isinstance(row, dict)] if isinstance(values, list) else []


def _text(row: dict[str, Any]) -> str:
    return str(
        row.get("title") or row.get("topic") or row.get("keyword")
        or row.get("query") or row.get("name") or ""
    ).strip()


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def _valid_time(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").casefold()


def _is_host(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _evidence_type(row: dict[str, Any], hinted: str, source_kind: str) -> str:
    explicit = str(row.get("evidence_type") or row.get("signal_type") or row.get("type") or "").casefold()
    if hinted:
        return hinted
    if any(token in explicit for token in ("activity", "campaign", "event", "活动")):
        return "official_activity"
    if explicit in {"official_activity", "official_keyword"}:
        return explicit
    return "official_keyword" if source_kind == "wewrite_hotspots" else ""


def build_wechat_official_contracts(
    payload: Any,
    *,
    raw_snapshot: bytes,
    source_kind: str,
) -> dict[str, Any]:
    """Return only complete, non-Sogou WeChat official signal contracts."""
    normalized_kind = str(source_kind or "").casefold().strip()
    snapshot = bytes(raw_snapshot or b"")
    snapshot_sha = hashlib.sha256(snapshot).hexdigest() if snapshot else ""
    contracts = []
    rejected = []
    if normalized_kind not in SOURCE_KINDS:
        return {
            "schema": "wechat_official_signal_contract_v1",
            "source_kind": normalized_kind,
            "raw_snapshot_sha256": snapshot_sha,
            "contracts": [],
            "rejected": [{"index": -1, "failures": ["source_kind_unsupported"]}],
            "passed": False,
        }

    parent = payload if isinstance(payload, dict) else {}
    backend_visible = parent.get("backend_visible") is True
    for index, (row, hinted_type) in enumerate(_rows(payload, normalized_kind)):
        title = _text(row)
        source_url = str(
            row.get("source_url") or row.get("official_url") or row.get("url")
            or parent.get("official_url") or parent.get("source_url") or ""
        ).strip()
        captured_at = str(
            row.get("captured_at") or row.get("observed_at") or row.get("fetched_at")
            or parent.get("captured_at") or parent.get("observed_at") or parent.get("fetched_at") or ""
        ).strip()
        heat = _number(row.get("heat") if row.get("heat") is not None else row.get("points", row.get("score")))
        rank = _number(row.get("rank") if row.get("rank") is not None else row.get("position"))
        evidence_type = _evidence_type(row, hinted_type, normalized_kind)
        host = _host(source_url)
        declared_sha = str(row.get("raw_snapshot_sha256") or row.get("snapshot_sha256") or "").casefold().strip()
        source_label = " ".join(str(row.get(key) or "") for key in ("source", "collector", "evidence_type")).casefold()
        failures = []
        if not title:
            failures.append("signal_missing")
        if not source_url.startswith(("https://", "http://")) or not host:
            failures.append("source_url_missing")
        elif _is_host(host, SOGOU_HOSTS) or "sogou" in source_label or "搜狗" in source_label:
            failures.append("sogou_source_forbidden")
        elif normalized_kind == "creator_backend" and not _is_host(host, WECHAT_HOSTS):
            failures.append("wechat_first_party_url_required")
        if normalized_kind == "creator_backend" and not backend_visible:
            failures.append("backend_visibility_unverified")
        if not _valid_time(captured_at):
            failures.append("captured_at_missing")
        if heat <= 0 and rank <= 0:
            failures.append("heat_or_rank_missing")
        if evidence_type not in {"official_keyword", "official_activity"}:
            failures.append("official_evidence_type_missing")
        if not snapshot_sha:
            failures.append("raw_snapshot_missing")
        if declared_sha and declared_sha != snapshot_sha:
            failures.append("raw_snapshot_sha256_mismatch")
        if failures:
            rejected.append({"index": index, "title": title, "failures": sorted(set(failures))})
            continue
        signal_type = "creator_backend_activity" if evidence_type == "official_activity" else (
            "creator_metrics_and_search_queries" if normalized_kind == "creator_backend" else "hot_list"
        )
        metric_heat = int(heat) if heat.is_integer() else heat
        metric_rank = int(rank) if rank.is_integer() else rank
        upstream_source = str(row.get("source") or "").strip()
        contract = {
            "platform": "wechat",
            "status": "backend_loaded" if normalized_kind == "creator_backend" else "verified",
            "signal_type": signal_type,
            "evidence_type": evidence_type,
            "signals": [title],
            "official_url": source_url,
            "final_url": source_url,
            "captured_at": captured_at,
            "heat": metric_heat,
            "rank": metric_rank,
            "evidence_sha256": snapshot_sha,
            "raw_snapshot_sha256": snapshot_sha,
            "collector": normalized_kind,
            "native_verified": False,
        }
        if upstream_source and upstream_source != normalized_kind:
            contract["upstream_source"] = upstream_source
        contracts.append(contract)
    return {
        "schema": "wechat_official_signal_contract_v1",
        "source_kind": normalized_kind,
        "raw_snapshot_sha256": snapshot_sha,
        "contracts": contracts,
        "rejected": rejected,
        "passed": bool(contracts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-kind", choices=sorted(SOURCE_KINDS), required=True)
    args = parser.parse_args(argv)
    source = Path(args.input)
    raw = source.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    result = build_wechat_official_contracts(payload, raw_snapshot=raw, source_kind=args.source_kind)
    output = {
        "schema": "official-platform-signal-matrix-v3",
        "platforms": result["contracts"],
        "passed": result["passed"],
        "source_report": {
            "source_kind": result["source_kind"],
            "raw_snapshot_sha256": result["raw_snapshot_sha256"],
            "rejected": result["rejected"],
        },
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
