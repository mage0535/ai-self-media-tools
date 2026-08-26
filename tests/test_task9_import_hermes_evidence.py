import json
from pathlib import Path

from scripts.task9_import_hermes_evidence import import_evidence


def test_import_accepts_native_x_and_rejects_indirect_wechat(tmp_path: Path):
    root = tmp_path / "hermes-recapture"
    (root / "twitter").mkdir(parents=True)
    (root / "wechat").mkdir(parents=True)
    (root / "twitter" / "evidence_raw.json").write_text('{"tweet":"AI Agent workflow"}', encoding="utf-8")
    (root / "wechat" / "evidence_raw.json").write_text('{"search":"AI workflow"}', encoding="utf-8")
    report = root / "report.json"
    report.write_text(json.dumps({"platforms": {
        "twitter": {
            "status": "success", "evidence_type": "native_search", "source_url": "https://x.com/search?q=AI",
            "observed_title": "AI Agent workflow", "captured_at": "2026-08-26T00:00:00Z", "native_verified": True,
            "metrics": {"tweets_found": 2},
        },
        "wechat": {
            "status": "success", "evidence_type": "sogou_wechat_search", "source_url": "https://weixin.sogou.com/weixin",
            "observed_title": "AI workflow", "captured_at": "2026-08-26T00:00:00Z", "native_verified": False,
        },
    }}), encoding="utf-8")

    result = import_evidence(report, tmp_path / "canary")

    assert [row["platform"] for row in result["accepted"]] == ["twitter"]
    assert result["rejected"] == [{"platform": "wechat", "failures": ["native_verification_missing", "platform_domain_mismatch"]}]
    saved = json.loads((tmp_path / "canary" / "_inputs" / "hotspots" / "twitter.json").read_text(encoding="utf-8"))
    assert saved["native_verified"] is True
    assert saved["snapshot_path"].endswith(".json")
