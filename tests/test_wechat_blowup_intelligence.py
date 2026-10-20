from __future__ import annotations

import json
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

from content_platform.wechat_blowup_intelligence import (
    build_wechat_blowup_report,
    collect_wechat_blowup_sources,
    load_wechat_blowup_compact,
)


def _vendor_article(**overrides):
    row = {
        "platform": "wechat",
        "title": "AI Agent 落地：三个月后我们删掉了 80% 工作流",
        "canonical_url": "https://mp.weixin.qq.com/s/vendor-sample",
        "account_name": "AI 实践观察",
        "published_at": "2026-09-14T09:00:00+08:00",
        "observed_at": "2026-09-15T09:00:00+08:00",
        "source_kind": "authorized_vendor_export",
        "source_vendor": "vendor_demo",
        "metric_name": "vendor_hot_rank",
        "metric_value": 1,
        "metric_definition": "AI category daily hot article rank in vendor monitored panel",
        "raw_snapshot_ref": "exports/vendor_demo_20260915.csv",
        "raw_snapshot_sha256": "a" * 64,
        "ai_subcluster": "agent_automation",
    }
    row.update(overrides)
    return row


def test_authorized_vendor_articles_are_strategy_ready_and_preserve_provenance():
    report = build_wechat_blowup_report([_vendor_article(canonical_url=f"https://mp.weixin.qq.com/s/{i}", title=f"AI Agent 实践 {i}") for i in range(3)])

    assert report["status"] == "strategy_ready"
    assert report["counts"] == {"G1": 0, "G2": 0, "G3": 3, "G4": 0, "rejected": 0}
    assert len(report["strategy_samples"]) == 3
    assert report["strategy_samples"][0]["evidence_grade"] == "G3"
    assert report["strategy_samples"][0]["claim_scope"] == "vendor_monitored_hot_article"


def test_search_or_sogou_article_never_upgrades_to_blowup_sample():
    report = build_wechat_blowup_report([
        _vendor_article(
            source_kind="sogou_wechat_search",
            source_vendor="",
            metric_name="search_rank",
            metric_value=1,
            metric_definition="search result rank",
            raw_snapshot_ref="",
            raw_snapshot_sha256="",
        )
    ])

    assert report["status"] == "blocked_no_strategy_evidence"
    assert report["counts"] == {"G1": 1, "G2": 0, "G3": 0, "G4": 0, "rejected": 0}
    assert report["strategy_samples"] == []
    assert report["gate_failures"] == ["insufficient_g3_or_g4_samples"]


def test_compact_loader_rejects_tampered_artifact_and_loads_verified_report(tmp_path):
    path = tmp_path / "wechat_blowup_latest.json"
    payload = build_wechat_blowup_report([_vendor_article(canonical_url=f"https://mp.weixin.qq.com/s/{i}", title=f"AI Agent 实践 {i}") for i in range(3)])
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    compact = load_wechat_blowup_compact(path)
    assert compact["status"] == "strategy_ready"
    assert len(compact["samples"]) == 3

    payload["strategy_samples"][0]["title"] = "tampered"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tampered = load_wechat_blowup_compact(path)
    assert tampered["status"] == "blocked"
    assert tampered["failures"] == ["artifact_sha256_mismatch"]


def test_collects_legal_vendor_export_without_copying_raw_snapshot(tmp_path):
    export = tmp_path / "vendor.json"
    export.write_text(
        json.dumps({"articles": [{"title": "Agent 工程实践", "canonical_url": "https://mp.weixin.qq.com/s/real-1", "account_name": "AI 工程化", "published_at": "2026-09-15T08:00:00+08:00", "metric_name": "vendor_hot_rank", "metric_value": 2}]}),
        encoding="utf-8",
    )
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps({"sources": [{"name": "licensed_vendor", "kind": "authorized_vendor_export", "path": str(export), "metric_definition": "Daily AI hot-article rank in licensed vendor panel"}]}),
        encoding="utf-8",
    )

    report = collect_wechat_blowup_sources(config)

    assert report["status"] == "blocked_no_strategy_evidence"
    assert report["counts"]["G3"] == 1
    row = report["strategy_samples"][0]
    assert row["source_vendor"] == "licensed_vendor"
    assert row["raw_snapshot_ref"] == "source:licensed_vendor"
    assert len(row["raw_snapshot_sha256"]) == 64
    assert "Agent 工程实践" not in json.dumps(report["source_audit"], ensure_ascii=False)


def test_cli_refreshes_configured_sources_into_verified_artifact(tmp_path):
    from content_platform.cli import main

    export = tmp_path / "vendor.json"
    export.write_text(json.dumps({"articles": [_vendor_article(canonical_url="https://mp.weixin.qq.com/s/refresh")]}), encoding="utf-8")
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"sources": [{"name": "licensed_vendor", "kind": "authorized_vendor_export", "path": str(export), "metric_definition": "daily AI rank"}]}), encoding="utf-8")
    output = tmp_path / "latest.json"

    with redirect_stdout(StringIO()):
        assert main(["wechat-blowup-refresh", "--sources", str(config), "--output", str(output)]) == 0

    compact = load_wechat_blowup_compact(output)
    assert compact["counts"]["G3"] == 1
