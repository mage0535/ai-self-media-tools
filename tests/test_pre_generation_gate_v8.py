from unittest.mock import patch

from content_platform.pipeline import Pipeline
from content_platform.run_contract import build_run_contract
from content_platform.store import Store


def _matrix(platform: str) -> dict:
    return {
        "version": "platform_source_matrix_v2",
        "platform": platform,
        "attempted_sources": [{"source": platform, "status": "success"}],
        "real_platform_collection_verified": True,
    }


def test_production_source_gate_blocks_before_model_generation(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.init()
    pipeline = Pipeline(store, {"data_dir": str(tmp_path)})
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    brief = {
        "automated_workflow": True,
        "run_contract": build_run_contract("twitter"),
        "content_blueprint": {"topic": "AI workflow", "content_form": "short_post"},
    }
    job = pipeline.create("AI workflow", ["twitter"], brief)

    with patch.object(pipeline.generator, "generate") as generate:
        result = pipeline.run(job["id"])

    assert result["state"] == "blocked"
    assert "platform_source_matrix" in result["last_error"]
    generate.assert_not_called()


def test_production_source_gate_accepts_verified_same_platform_matrix(tmp_path, monkeypatch):
    from content_platform.pre_generation_gate import validate_pre_generation

    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    brief = {
        "automated_workflow": True,
        "run_contract": build_run_contract("twitter"),
        "platform_source_matrix": _matrix("twitter"),
        "content_blueprint": {"topic": "AI workflow", "content_form": "short_post"},
        "content_profile": {"content_domain": "tech"},
        "capability_plan": {"selected": ["hook_structure_reference"]},
        "compiled_skill_rules": {"rules": [{"id": "hook-1"}]},
        "bounded_model_input": {"content_blueprint": {"topic": "AI workflow"}},
    }
    job = {"platforms": ["twitter"], "brief": brief}
    config = {"publishers": {"platforms": {"twitter": {"type": "x-playwright"}}}}

    result = validate_pre_generation(job, brief, config)

    assert result["passed"] is True
    assert result["failures"] == []


def test_production_source_gate_rejects_cross_platform_native_identity(tmp_path, monkeypatch):
    from content_platform.pre_generation_gate import validate_pre_generation

    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")
    brief = {
        "automated_workflow": True,
        "run_contract": build_run_contract("twitter"),
        "platform_source_matrix": _matrix("youtube"),
        "content_blueprint": {"topic": "AI workflow"},
        "content_profile": {"content_domain": "tech"},
        "capability_plan": {"selected": ["hook_structure_reference"]},
        "compiled_skill_rules": {"rules": [{"id": "hook-1"}]},
        "bounded_model_input": {"content_blueprint": {"topic": "AI workflow"}},
    }

    result = validate_pre_generation({"platforms": ["twitter"], "brief": brief}, brief, {})

    assert result["passed"] is False
    assert "platform_source_matrix.platform_mismatch" in result["failures"]
