from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from content_platform.artifact_contract import validate_platform_artifacts
from content_platform.pipeline import Pipeline
from content_platform.store import Store


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state.db")
    store.init()
    return store


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("kuaishou", {"video", "cover"}), ("wechat", {"image", "cover"}), ("xiaohongshu", {"image", "cover"})],
)
def test_platform_artifact_contract_rejects_zero_artifacts(platform, expected):
    result = validate_platform_artifacts({"platforms": [platform]}, [])

    assert result["passed"] is False
    assert set(result["missing_kinds"]) == expected


def test_text_only_x_contract_does_not_invent_media_requirement():
    result = validate_platform_artifacts({"platforms": ["twitter"]}, [])

    assert result["passed"] is True
    assert result["required_kinds"] == []


def test_production_approval_rejects_legacy_zero_artifact_review(tmp_path, monkeypatch):
    store = _store(tmp_path)
    job = store.create_job("video", ["kuaishou"], {})
    store.transition(job["id"], {"created"}, "review_required", "legacy_review")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path)})
    monkeypatch.setenv("CONTENT_PLATFORM_RUNTIME_MODE", "production")

    with pytest.raises(ValueError, match="platform artifact contract failed"):
        pipeline.approve(job["id"], "operator")

    assert store.get_job(job["id"])["state"] == "review_required"


def test_pipeline_run_recovers_expired_generation_lease_before_claim(tmp_path):
    store = _store(tmp_path)
    job = store.create_job("resume", ["twitter"], {})
    assert store.claim(job["id"], {"created"}, "dead-worker", -1, "generating")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path)})

    with patch.object(store, "claim", side_effect=RuntimeError("new claim reached")) as claim:
        with pytest.raises(RuntimeError, match="new claim reached"):
            pipeline.run(job["id"])

    assert "failed" in claim.call_args.args[1]
    recovered = store.get_job(job["id"])
    assert recovered["state"] == "failed"
    assert recovered["lease_owner"] == ""
    assert recovered["last_error"] == "stale lease recovered"
