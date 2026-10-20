from __future__ import annotations


def _scenario():
    return {
        "actor": {"role": "财务专员", "context": "每周核对供应商发票"},
        "inputs": [{"type": "发票表格", "source": "财务系统导出", "example_or_schema": "发票号、金额、供应商"}],
        "process": {"steps": [
            {"action": "导入表格", "ai_function": "字段标准化", "output": "标准化明细"},
            {"action": "比对异常", "ai_function": "差异识别", "output": "待复核清单"},
        ]},
        "outcome": {"deliverable": "差异清单", "measurement_method": "与人工基线比较", "status": "verification_required", "value_or_verification": "记录每周处理时间"},
        "boundaries": [{"type": "reliability", "detail": "金额异常必须人工复核"}],
        "human_handoff": {"trigger": "金额不一致", "responsible_role": "财务专员", "review_or_action": "核对原始凭证", "acceptance_or_escalation_rule": "确认后再入账"},
        "evidence_status": "verification_required",
    }


def _spec(**overrides):
    spec = {
        "platform": "douyin_ai",
        "content_type": "short_video",
        "topic": "AI 自动整理 Excel 表格",
        "audience": "没有代码基础的普通用户",
        "goal": "让用户收藏并尝试",
        "evidence": ["真实运行截图", "真实耗时对比"],
        "visual_style": "终端实录 + 数据对比",
        "duration": "40-60秒",
        "constraints": ["禁止PPT翻页", "禁止纯色背景"],
        "policy_profile": "real_world_ai_implementation_v1",
        "policy_revision": "2026-09-16-universal-ai-lane-r2",
        "prompt_profile": "douyin_ai_real_world_ai_v1",
        "scenario": _scenario(),
    }
    spec.update(overrides)
    return spec


def test_compile_prompt_bundle_is_deterministic_and_grouped():
    from content_platform.prompt_compiler import compile_prompt_bundle

    first = compile_prompt_bundle(_spec())
    second = compile_prompt_bundle(_spec())

    assert first == second
    assert first["version"] == "prompt_bundle_v1"
    assert first["fingerprint"]
    assert first["keywords"]["platform"]
    assert first["keywords"]["visual"]
    assert "topic" in first["prompts"]
    assert "quality_contract" in first


def test_platform_and_content_type_change_compiled_contract():
    from content_platform.prompt_compiler import compile_prompt_bundle

    douyin = compile_prompt_bundle(_spec(platform="douyin_ai", content_type="short_video"))
    zhihu = compile_prompt_bundle(_spec(platform="zhihu", content_type="article", prompt_profile="zhihu_real_world_ai_v1"))

    assert douyin["fingerprint"] != zhihu["fingerprint"]
    assert douyin["quality_contract"]["duration_required"] is True
    assert zhihu["quality_contract"]["duration_required"] is False
    assert "zhihu_real_world_ai_v1" in zhihu["keywords"]["platform"]


def test_validate_prompt_bundle_fails_closed_for_missing_core_context():
    from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle

    bundle = compile_prompt_bundle(_spec(topic="", audience="", constraints=[]))
    result = validate_prompt_bundle(bundle)

    assert result["passed"] is False
    assert "missing_topic" in result["errors"]
    assert "missing_audience" in result["errors"]
    assert "missing_constraints" in result["errors"]


def test_failure_classifier_distinguishes_input_provider_quality_and_pipeline():
    from content_platform.prompt_compiler import classify_failure

    assert classify_failure("missing_topic") == "input_invalid"
    assert classify_failure("HTTP 429 provider timeout") == "provider_failure"
    assert classify_failure("semantic_asset_mismatch") == "quality_failure"
    assert classify_failure("stale_checkpoint_reused") == "pipeline_failure"
    assert classify_failure("unknown issue") == "unknown"


def test_prompt_bundle_cli_compiles_and_validates_json(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    spec = tmp_path / "spec.json"
    output = tmp_path / "bundle.json"
    spec.write_text(json.dumps(_spec(), ensure_ascii=False), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]

    process = subprocess.run(
        [sys.executable, "scripts/compile_prompt_bundle.py", "--spec", str(spec), "--output", str(output), "--validate"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert bundle["version"] == "prompt_bundle_v1"
    assert bundle["validation"]["passed"] is True


def test_cache_keys_are_stable_typed_and_invalidate_on_render_inputs(tmp_path):
    from content_platform.asset_cache import build_cache_key, cache_path

    base = {
        "platform": "douyin_ai",
        "topic": "AI整理Excel",
        "prompt_version": "prompt_bundle_v1",
        "model": "sensenova-u1-fast",
        "source_hash": "abc123",
        "renderer_version": "film_renderer_v2",
    }
    prompt_key = build_cache_key("prompt", base)
    asset_key = build_cache_key("asset", base)
    render_key = build_cache_key("render", base)

    assert len(prompt_key) == 24
    assert len({prompt_key, asset_key, render_key}) == 3
    assert build_cache_key("render", {**base, "renderer_version": "film_renderer_v3"}) != render_key
    assert build_cache_key("render", dict(reversed(list(base.items())))) == render_key
    result = cache_path(tmp_path, "render", render_key, ".json")
    assert result.parent == tmp_path / "render"
    assert result.name == f"{render_key}.json"
    assert str(result).startswith(str(tmp_path))


def test_prompt_registry_loads_versioned_platform_profiles():
    from content_platform.prompt_registry import PromptRegistry

    registry = PromptRegistry.from_default()
    douyin = registry.platform("douyin_ai")
    zhihu = registry.platform("zhihu")

    assert registry.version == "prompt_registry_v1"
    assert douyin["language"] == "zh-CN"
    assert douyin["aspect_ratio"] == "9:16"
    assert douyin["duration_seconds"]["min"] == 20
    assert zhihu["content_type"] == "article"
    assert zhihu["aspect_ratio"] is None


def test_prompt_registry_rejects_unknown_platform_and_bad_snapshot(tmp_path):
    import json
    import pytest
    from content_platform.prompt_registry import PromptRegistry

    registry = PromptRegistry.from_default()
    with pytest.raises(KeyError):
        registry.platform("not-a-platform")

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": "x", "platforms": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        PromptRegistry.from_file(bad)


def test_all_18_ai_platforms_have_canonical_prompt_profiles():
    from content_platform.prompt_registry import PromptRegistry
    from content_platform.real_world_ai_policy import load_real_world_ai_positioning

    policy = load_real_world_ai_positioning()
    registry = PromptRegistry.from_default()

    assert len(policy["platforms"]) == 18
    for platform in policy["platforms"]:
        profile = registry.platform(platform)
        assert profile["prompt_profile"] == f"{platform}_real_world_ai_v1"
        assert profile["policy_profile"] == policy["policy_profile"]
        assert profile["policy_revision"] == policy["policy_revision"]


def test_compile_consumes_canonical_policy_profile_revision_and_scenario():
    from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle

    bundle = compile_prompt_bundle(_spec())

    assert bundle["contract"] == {
        "policy_profile": "real_world_ai_implementation_v1",
        "policy_revision": "2026-09-16-universal-ai-lane-r2",
        "prompt_profile": "douyin_ai_real_world_ai_v1",
    }
    assert bundle["scenario"] == _scenario()
    assert validate_prompt_bundle(bundle)["passed"] is True
    rendered = "\n".join(bundle["prompts"].values())
    for field in ("actor", "inputs", "process", "outcome", "boundaries", "human_handoff", "evidence_status"):
        assert field in rendered


def test_compile_fails_closed_on_contract_mismatch_or_incomplete_scenario():
    import pytest
    from content_platform.prompt_compiler import compile_prompt_bundle

    with pytest.raises(ValueError, match="policy_revision_mismatch"):
        compile_prompt_bundle(_spec(policy_revision="stale"))
    with pytest.raises(ValueError, match="prompt_profile_mismatch"):
        compile_prompt_bundle(_spec(prompt_profile="other"))
    with pytest.raises(ValueError, match="scenario_contract_invalid"):
        compile_prompt_bundle(_spec(scenario={**_scenario(), "human_handoff": {}}))


def test_validation_rejects_empty_prompt_tamper_and_version_mismatch():
    from copy import deepcopy
    from content_platform.prompt_compiler import compile_prompt_bundle, validate_prompt_bundle

    bundle = compile_prompt_bundle(_spec())
    empty = deepcopy(bundle)
    empty["prompts"]["copy"] = ""
    assert "empty_prompt:copy" in validate_prompt_bundle(empty)["errors"]

    tampered = deepcopy(bundle)
    tampered["prompts"]["copy"] += " tampered"
    assert "fingerprint_mismatch" in validate_prompt_bundle(tampered)["errors"]

    mismatched = deepcopy(bundle)
    mismatched["version"] = "prompt_bundle_v0"
    assert "bundle_version_mismatch" in validate_prompt_bundle(mismatched)["errors"]


def test_prompt_contract_contains_no_legacy_ai_productivity_labels():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    payload = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in (
            "content_platform/prompt_compiler.py",
            "content_platform/prompt_registry.py",
            "config/prompt_registry.json",
        )
    )
    for legacy in ("AI效率", "AI工具教程", "AI productivity"):
        assert legacy not in payload


def test_intelligence_blocks_ai_lane_when_prompt_gate_fails(monkeypatch):
    import pytest
    import content_platform.intelligence as intelligence

    monkeypatch.setattr(intelligence, "compile_prompt_bundle", lambda spec: {"version": "bad"})
    monkeypatch.setattr(
        intelligence,
        "validate_prompt_bundle",
        lambda bundle: {"passed": False, "errors": ["bundle_version_mismatch"], "warnings": []},
    )
    with pytest.raises(ValueError, match="ai_lane_prompt_gate_failed"):
        intelligence.build_generation_context(
            "AI 发票核对",
            {
                "platforms": ["douyin_ai"],
                "platform": "douyin_ai",
                "lane": "real_world_ai_implementation_v1",
                "scenario": _scenario(),
                "evidence": ["真实运行截图"],
            },
        )


def test_generator_blocks_before_provider_when_ai_prompt_gate_is_failed(monkeypatch):
    import pytest
    import content_platform.generator as generator_module

    monkeypatch.setattr(
        generator_module,
        "build_generation_context",
        lambda topic, brief: {
            "prompt_bundle_gate": {"passed": False, "errors": ["fingerprint_mismatch"], "warnings": []},
            "strategy": {"primary_platforms": ["douyin_ai"]},
        },
    )
    with pytest.raises(ValueError, match="ai_lane_prompt_gate_failed"):
        generator_module.DraftGenerator({"allow_fallback": True}).generate(
            "AI 发票核对", {"platforms": ["douyin_ai"], "lane": "real_world_ai_implementation_v1"}
        )


def test_search_spec_emits_query_variants_and_candidate_score():
    from content_platform.search_contract import build_search_spec, score_candidate

    search = build_search_spec(
        topic="AI 自动整理 Excel 表格",
        platform="douyin_ai",
        visual_style="终端实录 + 数据对比",
        aspect_ratio="9:16",
    )
    assert search["version"] == "search_spec_v1"
    assert search["queries"]["semantic"]
    assert search["queries"]["tags"]
    assert "抖音" in search["queries"]["platform"]
    assert search["filters"]["aspect_ratio"] == "9:16"

    candidate = {
        "id": "asset-1",
        "title": "AI Excel spreadsheet workflow",
        "tags": ["excel", "automation", "data"],
        "width": 1920,
        "height": 1080,
        "license_verified": True,
        "downloadable": True,
    }
    result = score_candidate(candidate, search)
    assert result["passed"] is True
    assert 0 < result["score"] <= 1
    assert result["reasons"]


def test_search_candidate_hard_fails_missing_license_or_dimensions():
    from content_platform.search_contract import build_search_spec, score_candidate

    search = build_search_spec("AI工具", "douyin_ai", "真实办公场景", "9:16")
    result = score_candidate({"title": "AI", "license_verified": False}, search)
    assert result["passed"] is False
    assert "license_unverified" in result["hard_failures"]
    assert "dimensions_missing" in result["hard_failures"]
