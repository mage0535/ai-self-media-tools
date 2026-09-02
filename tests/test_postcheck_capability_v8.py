from content_platform.adapter_executor import execute_capability
from content_platform.capability_router import load_registry
from content_platform.execution_trace import complete_delivery_trace, merge_execution_manifests, record_execution_stage
from content_platform.pipeline import Pipeline
from content_platform.store import Store
from content_platform.models import DeliveryResult
import json
import pytest


def _capability():
    return next(item for item in load_registry()["capabilities"] if item["id"] == "postcheck")


def test_postcheck_capability_executes_for_verified_publication():
    result = execute_capability(
        _capability(),
        {
            "delivery_result": {"status": "published", "external_id": "post-1"},
            "publication_identity": {
                "passed": True, "platform_content_id": "post-1",
                "published_at": "2026-09-02T12:00:00+08:00",
            },
        },
    )

    assert result["status"] == "executed"
    assert result["contract_valid"] is True


def test_postcheck_capability_skips_draft_without_claiming_publication():
    result = execute_capability(_capability(), {"delivery_result": {"status": "drafted", "external_id": "draft-1"}})

    assert result["status"] == "skipped"
    assert result["reason"] == "non_publication_status:drafted"


def test_postcheck_capability_rejects_published_without_verified_identity():
    result = execute_capability(
        _capability(),
        {"delivery_result": {"status": "published", "external_id": "task-id"}, "publication_identity": {}},
    )

    assert result["status"] == "failed"
    assert "publication_identity_not_verified" in result["output"]["reason"]


def _pre_delivery_trace():
    records = []
    for stage in ("collection", "selection", "blueprint", "generation", "assets", "render", "gate"):
        records.append(record_execution_stage(stage, manifest_hash="a" * 64))
    return merge_execution_manifests(records, allow_incomplete=True)


def test_published_delivery_trace_requires_and_executes_postcheck():
    evidence = execute_capability(
        _capability(),
        {
            "delivery_result": {"status": "published", "external_id": "post-1"},
            "publication_identity": {"passed": True, "platform_content_id": "post-1", "published_at": "2026-09-02T12:00:00+08:00"},
        },
    )

    trace = complete_delivery_trace(
        _pre_delivery_trace(), platform="twitter",
        result={"ok": True, "status": "published", "external_id": "post-1"},
        postcheck_evidence=evidence,
    )

    delivery = trace["stages"][-1]
    assert trace["passed"] is True
    assert "postcheck" in {item["node_id"] for item in delivery["executed"]}


def test_draft_delivery_trace_records_optional_postcheck_skip_reason():
    evidence = execute_capability(_capability(), {"delivery_result": {"status": "drafted", "external_id": "draft-1"}})

    trace = complete_delivery_trace(
        _pre_delivery_trace(), platform="wechat",
        result={"ok": True, "status": "drafted", "external_id": "draft-1"},
        postcheck_evidence=evidence,
    )

    delivery = trace["stages"][-1]
    assert trace["passed"] is True
    skipped = next(item for item in delivery["skipped"] if item["node_id"] == "postcheck")
    assert skipped["reason"] == "non_publication_status:drafted"


def test_published_delivery_trace_fails_when_required_postcheck_did_not_execute():
    trace = complete_delivery_trace(
        _pre_delivery_trace(), platform="twitter",
        result={"ok": True, "status": "published", "external_id": "post-1"},
        postcheck_evidence={"status": "failed", "reason": "identity missing"},
    )

    assert trace["passed"] is False
    assert "required_node_not_executed:delivery:postcheck" in trace["failures"]


def test_pipeline_persists_postcheck_execution_on_real_job(tmp_path):
    store = Store(tmp_path / "state.db")
    store.init()
    job = store.create_job("Topic", ["twitter"], {})
    store.save_draft(job["id"], "Title", "Body", "pass", {}, "test", {"execution_trace": _pre_delivery_trace()})
    pipeline = Pipeline(store, {"data_dir": str(tmp_path)})
    evidence = execute_capability(
        _capability(),
        {
            "delivery_result": {"status": "published", "external_id": "post-1"},
            "publication_identity": {"passed": True, "platform_content_id": "post-1", "published_at": "2026-09-02T12:00:00+08:00"},
        },
    )

    assert pipeline._persist_delivery_postcheck(store.get_job(job["id"]), "twitter", evidence) is True
    saved = store.get_job(job["id"])["draft_meta"]["delivery_postcheck_execution"]["twitter"]
    assert saved["status"] == "executed"
    assert saved["output_hash"]


@pytest.mark.parametrize("evidence", [None, {}, {"status": "executed", "contract_valid": False, "output_hash": "sha256:" + "a" * 64}])
def test_missing_or_invalid_postcheck_never_bypasses_published_gate(evidence):
    trace = complete_delivery_trace(
        _pre_delivery_trace(), platform="twitter",
        result={"ok": True, "status": "published", "external_id": "post-1"},
        postcheck_evidence=evidence,
    )
    assert trace["passed"] is False
    assert "required_node_not_executed:delivery:postcheck" in trace["failures"]


def test_postcheck_rejects_identity_for_different_content():
    evidence = execute_capability(_capability(), {
        "delivery_result": {"status": "published", "external_id": "post-2"},
        "publication_identity": {"passed": True, "platform_content_id": "post-1", "published_at": "2026-09-02T12:00:00+08:00"},
    })
    assert evidence["status"] == "failed"


@pytest.mark.parametrize("status", ["published", "drafted", "scheduled", "handoff_pending"])
def test_real_delivery_path_persists_adapter_and_completed_trace(tmp_path, monkeypatch, status):
    store = Store(tmp_path / "state.db")
    store.init()
    job = store.create_job("Topic", ["twitter"], {})
    store.save_draft(job["id"], "Title", "Body", "pass", {}, "test", {"execution_trace": _pre_delivery_trace(), "preserve": "value"})
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def set_delivery_callback(self, callback):
            self.callback = callback

        def deliver(self, job, platform):
            if status == "published":
                self.callback({"status": status, "verification": {
                    "account_alias": "default", "content_id": "post-1", "url": "https://x.com/account/status/post-1",
                    "published_at": "2026-09-02T12:00:00+08:00", "source": "management_page",
                }})
            return DeliveryResult(True, status, "post-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *a, **k: Publisher())
    stale_job = store.get_job(job["id"])
    result = pipeline._deliver("twitter", stale_job)
    pipeline._complete_execution_trace(stale_job, "twitter", result)
    meta = store.get_job(job["id"])["draft_meta"]
    evidence = meta["delivery_postcheck_execution"]["twitter"]
    assert evidence["status"] == ("executed" if status == "published" else "skipped")
    assert meta["preserve"] == "value"
    assert meta["execution_trace"]["passed"] is True
    with store.connect() as conn:
        saved = json.loads(conn.execute("SELECT metadata_json FROM delivery_attempts").fetchone()[0])
    assert saved["postcheck_execution"] == evidence
    assert len(store.publication_ledger.identities()) == (1 if status == "published" else 0)


@pytest.mark.parametrize("second_platform", ["twitter", "wechat"])
def test_previous_success_cannot_mask_later_missing_postcheck(second_platform):
    from content_platform.capability_runtime import execute_delivery_postcheck_capability

    result = {"ok": True, "status": "published", "external_id": "post-1"}
    evidence = execute_delivery_postcheck_capability(result, {
        "passed": True, "platform_content_id": "post-1", "published_at": "2026-09-02T12:00:00+08:00",
    })
    first = complete_delivery_trace(_pre_delivery_trace(), platform="twitter", result=result, postcheck_evidence=evidence)
    assert first["passed"] is True
    second = complete_delivery_trace(first, platform=second_platform, result={**result, "external_id": "post-2"})
    assert second["passed"] is False


def test_attempt_evidence_survives_draft_metadata_write_failure(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.init()
    job = store.create_job("Topic", ["twitter"], {})
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def deliver(self, job, platform):
            return DeliveryResult(True, "drafted", "draft-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *a, **k: Publisher())
    def fail(*args):
        raise OSError("metadata unavailable")
    monkeypatch.setattr(pipeline, "_persist_delivery_postcheck", fail)
    with pytest.raises(OSError, match="metadata unavailable"):
        pipeline._deliver("twitter", job)
    with store.connect() as conn:
        row = conn.execute("SELECT state,metadata_json FROM delivery_attempts").fetchone()
        assert row[0] == "drafted"
        assert json.loads(row[1])["postcheck_execution"]["status"] == "skipped"
        assert conn.execute("SELECT count(*) FROM delivery_leases").fetchone()[0] == 0


@pytest.mark.parametrize("mismatch", ["account", "content", "platform"])
def test_delivery_rejects_wrong_identity_before_creating_metric_windows(tmp_path, monkeypatch, mismatch):
    store = Store(tmp_path / "state.db")
    store.init()
    job = store.create_job("Topic", ["twitter"], {})
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def set_delivery_callback(self, callback):
            self.callback = callback

        def deliver(self, job, platform):
            self.callback({"status": "published", "verification": {
                "account_alias": "someone_else" if mismatch == "account" else "default",
                "content_id": "other-post" if mismatch == "content" else "post-1",
                "platform": "wechat" if mismatch == "platform" else "twitter",
                "url": "https://x.com/account/status/post-1", "published_at": "2026-09-02T12:00:00+08:00", "source": "management_page",
            }})
            return DeliveryResult(True, "published", "post-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *a, **k: Publisher())
    result = pipeline._deliver("twitter", job)
    assert result.status == "unknown_requires_review"
    assert result.ok is False
    assert store.publication_ledger.identities() == []
    assert store.publication_ledger.due_windows() == []


def test_trace_rejects_tampered_postcheck_output():
    from content_platform.capability_runtime import execute_delivery_postcheck_capability
    result = {"ok": True, "status": "published", "external_id": "post-1"}
    evidence = execute_delivery_postcheck_capability(result, {
        "passed": True, "platform_content_id": "post-1", "published_at": "2026-09-02T12:00:00+08:00",
    })
    evidence["output"]["extra_claim"] = "not part of original adapter output"
    trace = complete_delivery_trace(_pre_delivery_trace(), platform="twitter", result=result, postcheck_evidence=evidence)
    assert trace["passed"] is False


def test_postcheck_evidence_participates_in_delivery_manifest_hash():
    result = {"ok": True, "status": "published", "external_id": "post-1"}
    traces = [complete_delivery_trace(_pre_delivery_trace(), platform="twitter", result=result,
              postcheck_evidence={"status": "failed", "reason": reason}) for reason in ("no proof", "wrong owner")]
    assert traces[0]["stages"][-1]["manifest_ref"]["hash"] != traces[1]["stages"][-1]["manifest_ref"]["hash"]


def test_automated_job_without_pre_delivery_trace_fails_and_persists_findings(tmp_path):
    store = Store(tmp_path / "state.db")
    store.init()
    job = store.create_job("Topic", ["twitter"], {"automated_workflow": True})
    pipeline = Pipeline(store, {"data_dir": str(tmp_path)})
    with pytest.raises(RuntimeError, match="canonical execution trace failed"):
        pipeline._complete_execution_trace(job, "twitter", DeliveryResult(True, "drafted", "draft-1"))
    saved = store.get_job(job["id"])["draft_meta"]["execution_trace"]
    assert saved["passed"] is False
    assert "required_stage_missing:generation" in saved["failures"]
