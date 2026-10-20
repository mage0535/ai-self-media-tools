import importlib.util
import json
from pathlib import Path

import pytest

from content_platform import platform_workflow_context


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "real_world_ai_implementation_v1.json"
RULEBOOK_PATH = ROOT / "config" / "channel_content_rulebook.json"
PS_VALIDATOR_PATH = ROOT / "scripts" / "validate_channel_rulebook.ps1"


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ai_rulebook_entries_store_only_canonical_ref_and_platform_adaptation():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    expected_ref = {
        "source": "config/real_world_ai_implementation_v1.json",
        "policy_profile": policy["policy_profile"],
        "policy_revision": policy["policy_revision"],
    }

    for platform in policy["platforms"]:
        positioning = rulebook["channel_rules"][platform]["real_world_ai_positioning"]
        assert set(positioning) == {"canonical_contract", "platform_adaptation"}, platform
        assert positioning["canonical_contract"] == expected_ref, platform
        assert positioning["platform_adaptation"] == policy["platform_adaptation"][platform], platform


def test_workflow_context_rejects_stale_rulebook_revision(tmp_path, monkeypatch):
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))
    rulebook["channel_rules"]["wechat"]["real_world_ai_positioning"]["canonical_contract"]["policy_revision"] = "stale"
    stale = tmp_path / "channel_content_rulebook.json"
    stale.write_text(json.dumps(rulebook, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(platform_workflow_context, "RULEBOOK", stale)

    with pytest.raises(ValueError, match="canonical AI rulebook reference mismatch"):
        platform_workflow_context.load_platform_workflow_context("wechat")


def test_non_ai_rulebook_entries_remain_isolated_from_ai_contract():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    rulebook = json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))

    assert "douyin_pet" not in policy["platforms"]
    assert "xiaohongshu" not in policy["platforms"]
    assert rulebook["account_lane_separation_policy"]["accounts"]["douyin_pet"]["lane"] == "pet_healing"
    assert "real_world_ai_positioning" not in rulebook["channel_rules"]["xiaohongshu"]


def test_legacy_unified_strategy_blocks_ai_platforms_and_publication_queue():
    module = _load_script("unified_content_strategy_legacy", ROOT / "scripts" / "unified_content_strategy.py")

    assert module.LEGACY_ONLY is True
    assert module.PUBLICATION_QUEUE_ELIGIBLE is False
    with pytest.raises(RuntimeError, match="canonical pipeline"):
        module.run_strategy(["wechat"], dry_run=True)
    with pytest.raises(RuntimeError, match="legacy-only"):
        module.run_strategy(["xiaohongshu"], dry_run=False)


def test_legacy_international_handoff_is_never_publication_queue_eligible(tmp_path, monkeypatch):
    module = _load_script("intl_short_video_pipeline_legacy_gate", ROOT / "scripts" / "intl_short_video_pipeline.py")
    monkeypatch.setattr(module, "DRAFT_DIR", tmp_path)
    strategy = {
        "self_gen": ["AI客服工单分类后由人工审核高风险问题"],
        "cross_kw": [],
        "date": "2026-09-16",
    }

    result = module.run_daily_pipeline(strategy=strategy, dry_run=True)

    assert result["self_gen"]
    assert all(item["legacy_only"] is True for item in result["self_gen"])
    assert all(item["publication_queue_eligible"] is False for item in result["self_gen"])


def test_powershell_validator_delegates_to_canonical_python_validator_without_old_contracts():
    source = PS_VALIDATOR_PATH.read_text(encoding="utf-8")

    assert "validate_channel_rulebook.py" in source
    assert "ai_efficiency_open_source" not in source
    assert "weekly_mix.cat_knowledge_or_original must be 2" not in source
    assert "weekly_mix.tiktok_hot_localized_reposts must be 5" not in source
