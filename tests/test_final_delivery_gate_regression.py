import hashlib
import json
from pathlib import Path

from content_platform.final_acceptance_matrix import PLATFORM_ACCEPTANCE_MATRIX, validate_platform_acceptance


def _packet(tmp_path):
    asset = tmp_path / "cover.png"
    asset.write_bytes(b"cover")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    assets = tmp_path / "assets.json"
    assets.write_text(json.dumps({
        "job_id": "job-1", "platform": "wechat", "content_package_id": "cp-1",
        "assets": [{"path": str(asset), "role": "cover", "source": "generated", "rights": "owned",
                    "match_reason": "topic cover", "semantic_match": True, "sha256": digest}],
    }))
    html = tmp_path / "article.html"
    html.write_text('<body><img data-src="cover.png"><p>body</p></body>')
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{}')
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"job_id": "job-1", "platform": "wechat", "content_package_id": "cp-1",
                                 "status": "drafted", "draft_batchget_verified": True, "evidence": str(evidence)}))
    return assets, html, state


def test_final_gate_rejects_failure_status_and_identity(tmp_path):
    from scripts.final_delivery_gate import run_gate
    assets, html, state = _packet(tmp_path)
    payload = json.loads(state.read_text())
    payload["status"] = "publish_failed"
    state.write_text(json.dumps(payload))
    result = run_gate(tmp_path, platform="wechat", job_id="job-1", content_package_id="cp-1",
                      html=html, assets=assets, state=state)
    assert not result["passed"]
    assert any("failure_state_cannot_pass" in item for item in result["failures"])


def test_acceptance_matrix_covers_all_required_platforms():
    required = {"douyin_ai", "douyin_pet", "shipinhao", "tiktok", "youtube_long_form", "youtube_shorts",
                "bilibili", "xiaohongshu", "kuaishou", "twitter", "x", "wechat", "wechat_newspic", "zhihu", "juejin"}
    assert required <= set(PLATFORM_ACCEPTANCE_MATRIX)
    result = validate_platform_acceptance("douyin_pet", {"platform": "douyin_pet"})
    assert not result["passed"]
    assert "video_cover_missing" in result["failures"]
