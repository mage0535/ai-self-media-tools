from __future__ import annotations

import json

from content_platform.hot_work_intelligence import build_hot_work_parameter_pack
from content_platform.overnight_batch import load_hot_work_parameter_pack_compact
from content_platform.wechat_blowup_intelligence import ingest_authorized_backend_export, load_wechat_blowup_compact


def _backend_observation(index: int) -> dict:
    return {
        "platform": "wechat",
        "source_kind": "authorized_backend_export",
        "canonical_url": f"https://mp.weixin.qq.com/s/article-{index}",
        "article_id": f"msg-{index}",
        "account_name": "授权账号",
        "title": f"AI 工作流实战 {index}",
        "published_at": f"2026-09-{10 + index:02d}T08:00:00+00:00",
        "observed_at": "2026-09-15T06:00:00+00:00",
        "metric_name": "total_read_uv",
        "metric_definition": "Unique readers shown by authorized WeChat MP article analysis",
        "metric_value": 1000 + index * 100,
        "metric_window": "2026-09-15",
        "baseline_required": True,
    }


def test_authorized_backend_article_observations_build_verified_g4_report(tmp_path):
    source = tmp_path / "authorized_backend_export.json"
    source.write_text(json.dumps({"article_observations": [_backend_observation(i) for i in range(3)]}), encoding="utf-8")
    output = tmp_path / "wechat_blowup.json"

    report = ingest_authorized_backend_export(source, output)
    compact = load_wechat_blowup_compact(output)

    assert report["counts"]["G4"] == 3
    assert report["status"] == "strategy_ready"
    assert compact["status"] == "strategy_ready"
    assert len(compact["samples"]) == 3
    assert all(sample["raw_snapshot_sha256"] == report["source_audit"][0]["raw_snapshot_sha256"] for sample in compact["samples"])
    assert all(sample["baseline"]["sample_n"] == 3 for sample in compact["samples"])


def test_wechat_blowup_cli_routes_backend_observations_through_g4_gate(tmp_path):
    from content_platform.cli import main

    source = tmp_path / "collector.json"
    source.write_text(json.dumps({"article_observations": [_backend_observation(i) for i in range(3)]}), encoding="utf-8")
    output = tmp_path / "latest.json"

    assert main(["wechat-blowup-ingest", "--input", str(source), "--output", str(output)]) == 0
    assert load_wechat_blowup_compact(output)["status"] == "strategy_ready"


def test_douyin_ai_context_reads_public_douyin_discovery_samples(tmp_path):
    pack = {
        "platforms": {
            "douyin_ai": {
                "ready": False,
                "strong_sample_count": 0,
                "top_samples": [],
                "top_discovery_samples": [],
            },
            "douyin": {
                "ready": False,
                "strong_sample_count": 0,
                "top_samples": [],
                "top_discovery_samples": [{"title": "AI 智能体", "source": "douyin_public_hot_page", "generation_only": True}],
            }
        }
    }
    source = tmp_path / "hot_pack.json"
    source.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    compact = load_hot_work_parameter_pack_compact("douyin_ai", path=source)

    assert compact["status"] == "insufficient"
    assert compact["discovery_samples"][0]["title"] == "AI 智能体"


def test_bilibili_discovery_samples_are_visible_but_not_promoted_in_generation_context(tmp_path):
    pack = build_hot_work_parameter_pack(
        [
            {
                "platform": "bilibili",
                "title": "Agent 工程化实战",
                "author": "测试作者",
                "views": 120000,
                "source": "bilibili_popular_api",
                "evidence_strength": "third_party_ranked_candidate",
                "generation_only": True,
                "auto_selection_eligible": False,
                "analysis": {"hook_types": ["结果前置"]},
            }
        ],
        platforms=["bilibili"],
    )
    source = tmp_path / "hot_pack.json"
    source.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")

    compact = load_hot_work_parameter_pack_compact("bilibili", path=source)

    assert compact["status"] == "insufficient"
    assert compact["strong_sample_count"] == 0
    assert compact["top_samples"] == []
    assert len(compact["discovery_samples"]) == 1
    assert compact["discovery_samples"][0]["title"] == "Agent 工程化实战"
    assert compact["discovery_samples"][0]["auto_selection_eligible"] is False
