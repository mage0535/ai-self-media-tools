from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from unittest.mock import patch

from content_platform.publication_ledger import PublicationLedger
from content_platform.models import DeliveryResult
from content_platform.pipeline import Pipeline
from content_platform.performance_collector import collect_due_metric_windows
from content_platform.publishers import SocialAutoUploadPublisher
from content_platform import scheduler
from content_platform.store import Store


def _intent(**overrides):
    value = {
        "job_id": "job-1",
        "platform": "kuaishou",
        "internal_account_alias": "kuaishou_main",
        "action": "schedule",
        "payload": {"title": "A title", "description": "A full description"},
        "media_hashes": ["sha256:video"],
        "expected_title": "A title",
        "expected_description": "A full description",
        "scheduled_at": "2026-08-25T12:00:00+00:00",
        "absence_window_seconds": 3600,
    }
    value.update(overrides)
    return value


def test_delivery_intent_is_immutable_and_timeout_is_unknown_until_absence_window(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    intent = ledger.create_delivery_intent(_intent())
    assert intent["intent_id"]
    assert ledger.create_delivery_intent(_intent())["intent_id"] == intent["intent_id"]
    with pytest.raises(ValueError, match="immutable"):
        ledger.create_delivery_intent(_intent(expected_title="changed"))

    started = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    attempt = ledger.begin_attempt(intent["intent_id"], "worker-1", now=started)
    ledger.finish_attempt(intent["intent_id"], attempt["attempt_id"], "unknown", error="timeout", now=started)
    assert ledger.get_delivery_intent(intent["intent_id"])["status"] == "unknown"
    assert ledger.poll_delivery(intent["intent_id"], lambda _: {"status": "absent"}, now=started + timedelta(minutes=30))["retry_allowed"] is False
    assert ledger.poll_delivery(intent["intent_id"], lambda _: {"status": "absent"}, now=started + timedelta(hours=1, seconds=1))["retry_allowed"] is True


def test_auth_conflict_and_inconclusive_results_require_review_without_retry(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    for reason in ("auth_failed", "conflict", "inconclusive"):
        intent = ledger.create_delivery_intent(_intent(job_id=f"job-{reason}"))
        attempt = ledger.begin_attempt(intent["intent_id"], "worker-1")
        ledger.finish_attempt(intent["intent_id"], attempt["attempt_id"], reason)
        result = ledger.get_delivery_intent(intent["intent_id"])
        assert result["status"] == "unknown_requires_review"
        assert result["retry_allowed"] is False


def test_only_verified_publication_creates_idempotent_metric_windows(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    published_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    payload = {
        "intent_id": ledger.create_delivery_intent(_intent(job_id="job-published", action="publish"))["intent_id"],
        "platform": "kuaishou",
        "internal_account_alias": "kuaishou_main",
        "platform_content_id": "ks-1",
        "canonical_url": "https://kuaishou.test/ks-1",
        "published_at": published_at.isoformat(),
        "verification": {
            "account_alias": "kuaishou_main",
            "content_id": "ks-1",
            "url": "https://kuaishou.test/ks-1",
            "published_at": published_at.isoformat(),
            "source": "management_page",
        },
    }
    identity = ledger.register_verified_publication(payload)
    assert identity["passed"] is True
    assert [row["hours"] for row in ledger.due_windows()] == [1, 24, 72]
    assert ledger.register_verified_publication(payload)["identity_id"] == identity["identity_id"]

    draft = ledger.create_delivery_intent(_intent(job_id="job-draft", action="draft"))
    ledger.record_delivery_result(draft["intent_id"], {"status": "drafted", "external_id": "draft-1"})
    assert ledger.due_windows(identity_id=None, include_all=True) == ledger.due_windows()


def test_observation_binds_platform_alias_content_source_and_confidence(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    published_at = datetime.now(timezone.utc)
    identity = ledger.register_verified_publication(
        {
            "platform": "wechat",
            "internal_account_alias": "wechat_main",
            "platform_content_id": "wx-1",
            "canonical_url": "https://wechat.test/wx-1",
            "published_at": published_at.isoformat(),
            "verification": {
                "account_alias": "wechat_main",
                "content_id": "wx-1",
                "url": "https://wechat.test/wx-1",
                "published_at": published_at.isoformat(),
                "source": "management_page",
            },
        }
    )
    window = ledger.due_windows()[0]
    observed = ledger.record_metrics(
        window["id"],
        {"views": 12},
        source="creator_backend",
        confidence="medium",
        platform="wechat",
        internal_account_alias="wechat_main",
        platform_content_id="wx-1",
    )
    assert observed["state"] == "collected"
    row = ledger.observations(identity_id=identity["identity_id"])[0]
    assert row["platform"] == "wechat"
    assert row["internal_account_alias"] == "wechat_main"
    assert row["platform_content_id"] == "wx-1"
    assert row["confidence"] == "medium"


def test_store_migration_exposes_task7_tables_and_manual_record_needs_verification_for_identity(tmp_path):
    store = Store(tmp_path / "state.db")
    with store.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"delivery_intents", "delivery_attempts", "delivery_leases", "publication_identities", "metric_windows", "metric_observations"} <= tables

    with pytest.raises(ValueError, match="required"):
        store.record_manual_publication("xiaohongshu", "Manual topic", external_id="manual-1")
    assert store.publication_ledger.identities() == []


def test_pipeline_persists_intent_before_publisher_and_timeout_is_not_retried(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})
    observed = []

    class Publisher:
        def deliver(self, job, platform):
            observed.append(store.publication_ledger.identities())
            with store.connect() as conn:
                row = conn.execute("SELECT * FROM delivery_intents").fetchone()
            assert row["platform"] == platform
            raise TimeoutError("publisher timed out after external call")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("bilibili", {"id": "job-1", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})
    assert result.status == "unknown"
    assert result.ok is False
    assert observed == [[]]
    with store.connect() as conn:
        intent = dict(conn.execute("SELECT * FROM delivery_intents").fetchone())
        attempts = conn.execute("SELECT count(*) FROM delivery_attempts").fetchone()[0]
    assert intent["status"] == "unknown"
    assert attempts == 1


def test_pipeline_does_not_accept_published_result_without_verification(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def deliver(self, job, platform):
            return DeliveryResult(True, "published", "content-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("bilibili", {"id": "job-verified", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})
    assert result.status == "unknown_requires_review"
    assert store.publication_ledger.identities() == []


def test_pipeline_rejects_invalid_verified_identity_before_persisting_published(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def set_delivery_callback(self, callback):
            self.callback = callback

        def deliver(self, job, platform):
            self.callback({
                "status": "published",
                "verification": {
                    "account_alias": "default",
                    "content_id": "content-1",
                    "url": "not-a-url",
                    "published_at": "2026-08-25T12:00:00+00:00",
                    "source": "management_page",
                },
            })
            return DeliveryResult(True, "published", "content-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("bilibili", {"id": "job-invalid", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})

    assert result.status == "unknown_requires_review"
    assert store.publication_ledger.identities() == []
    assert store.publication_ledger.due_windows() == []
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM delivery_intents").fetchone()[0] == "unknown_requires_review"
        assert conn.execute("SELECT state FROM delivery_attempts").fetchone()[0] == "unknown_requires_review"


def test_pipeline_converts_failed_external_auth_to_review_without_retry(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def deliver(self, job, platform):
            return DeliveryResult(False, "failed", error="auth cookie expired")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("bilibili", {"id": "job-auth", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})
    assert result.status == "unknown_requires_review"
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM delivery_intents").fetchone()[0] == "unknown_requires_review"


def test_pipeline_preserves_publisher_unknown_requires_review_without_retry(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})

    class Publisher:
        def deliver(self, job, platform):
            return DeliveryResult(False, "unknown_requires_review", "submitted-1", "immutable post identity missing")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("twitter", {"id": "job-review", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})

    assert result.status == "unknown_requires_review"
    assert result.external_id == "submitted-1"
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM delivery_intents").fetchone()[0] == "unknown_requires_review"
        assert conn.execute("SELECT retry_allowed FROM delivery_intents").fetchone()[0] == 0


def test_delivery_callback_can_prove_real_publication_identity(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    pipeline = Pipeline(store, {"data_dir": str(tmp_path), "delivery_health": {"allow_unknown_health": True}, "publishers": {"default": {"type": "file"}}})
    published_at = datetime.now(timezone.utc).isoformat()

    class Publisher:
        def set_delivery_callback(self, callback):
            self.callback = callback

        def deliver(self, job, platform):
            self.callback({"status": "published", "verification": {"account_alias": "default", "content_id": "content-1", "url": "https://b.test/content-1", "published_at": published_at, "source": "management_page"}})
            return DeliveryResult(True, "published", "content-1")

    monkeypatch.setattr("content_platform.pipeline.build_publisher", lambda *args, **kwargs: Publisher())
    result = pipeline._deliver("bilibili", {"id": "job-callback", "title": "Title", "body": "Body", "platform_payload": {"title": "Title", "text": "Body"}, "artifacts": []})
    assert result.status == "published"
    assert len(store.publication_ledger.identities("bilibili")) == 1
    assert [row["hours"] for row in store.publication_ledger.due_windows()] == [1, 24, 72]


def test_kuaishou_scheduled_postcheck_requires_all_management_page_evidence(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    intent = ledger.create_delivery_intent(_intent())
    missing = ledger.validate_kuaishou_scheduled_postcheck(intent, {"account_alias": "kuaishou_main", "title": "A title", "scheduled_at": intent["scheduled_at"], "screenshot_path": "proof.png"})
    assert missing["passed"] is False
    valid = ledger.validate_kuaishou_scheduled_postcheck(intent, {"account_alias": "kuaishou_main", "title": "A title", "description_digest": intent["expected_description_digest"], "scheduled_at": intent["scheduled_at"], "dom_snapshot": "<row>"})
    assert valid["passed"] is True


def test_due_metric_collector_binds_real_identity_and_marks_missing_data_insufficient(tmp_path):
    store = Store(tmp_path / "state.db")
    published_at = datetime.now(timezone.utc) - timedelta(hours=2)
    identity = store.publication_ledger.register_verified_publication({
        "platform": "wechat",
        "internal_account_alias": "wechat_main",
        "platform_content_id": "wx-1",
        "canonical_url": "https://wechat.test/wx-1",
        "published_at": published_at.isoformat(),
        "verification": {"account_alias": "wechat_main", "content_id": "wx-1", "url": "https://wechat.test/wx-1", "published_at": published_at.isoformat(), "source": "management_page"},
    })
    report = collect_due_metric_windows(store.publication_ledger, lambda _: {"status": "ok", "metrics": {"views": 8}, "source": "backend", "confidence": "high"})
    assert report["collected"] == 1
    assert store.publication_ledger.observations(identity_id=identity["identity_id"])[0]["confidence"] == "high"

    identity2 = store.publication_ledger.register_verified_publication({
        "platform": "wechat",
        "internal_account_alias": "wechat_main",
        "platform_content_id": "wx-2",
        "canonical_url": "https://wechat.test/wx-2",
        "published_at": published_at.isoformat(),
        "verification": {"account_alias": "wechat_main", "content_id": "wx-2", "url": "https://wechat.test/wx-2", "published_at": published_at.isoformat(), "source": "management_page"},
    })
    report = collect_due_metric_windows(store.publication_ledger, lambda _: {"status": "unavailable", "source": "backend", "confidence": "low"})
    assert report["insufficient"] == 1
    assert any(row["identity_id"] == identity2["identity_id"] and row["state"] == "insufficient" for row in store.publication_ledger.observations())


def test_kuaishou_adapter_never_calls_scheduled_success_without_management_postcheck(tmp_path, monkeypatch):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("content_platform.publishers.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})())
    base_job = {"id": "job-ks", "title": "A title", "body": "A full description", "platform_payload": {"kind": "video", "title": "A title", "caption": "A full description"}, "artifacts": [{"kind": "video", "path": str(video)}]}
    without = SocialAutoUploadPublisher("kuaishou", "kuaishou_main", project_dir=tmp_path, schedule_at="2026-08-25 12:00")
    assert without.deliver(base_job, "kuaishou").status == "unknown_requires_review"
    with_postcheck = SocialAutoUploadPublisher(
        "kuaishou", "kuaishou_main", project_dir=tmp_path, schedule_at="2026-08-25 12:00",
        postcheck_callback=lambda intent: {"account_alias": "kuaishou_main", "title": "A title", "description": "A full description", "scheduled_at": "2026-08-25 12:00", "screenshot_path": "proof.png"},
    )
    assert with_postcheck.deliver(base_job, "kuaishou").status == "scheduled"


def test_kuaishou_adapter_uses_management_postcheck_script_by_default(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if any("kuaishou_postcheck_manifest.py" in str(item) for item in command):
            out_dir = Path(command[-1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "postcheck.json").write_text(
                '{"passed": true, "status": "management_postcheck_found", "evidence_path": "proof.png"}',
                encoding="utf-8",
            )
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    job = {
        "id": "job-ks-default",
        "title": "A title",
        "body": "A full description",
        "platform_payload": {"kind": "video", "title": "A title", "caption": "A full description"},
        "artifacts": [{"kind": "video", "path": str(video)}],
    }
    with patch("content_platform.publishers.subprocess.run", side_effect=run):
        result = SocialAutoUploadPublisher(
            "kuaishou", "kuaishou_main", project_dir=tmp_path, python_bin="python", schedule_at="2026-08-25 12:00"
        ).deliver(job, "kuaishou")

    assert result.status == "scheduled"
    assert any("kuaishou_postcheck_manifest.py" in str(item) for command in calls for item in command)


def test_delivery_lease_cannot_be_overwritten_by_second_live_worker(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    intent = ledger.create_delivery_intent(_intent(job_id="lease-race"))

    results = []
    for owner in ("worker-1", "worker-2"):
        try:
            results.append(ledger.begin_attempt(intent["intent_id"], owner, now="2026-08-25T12:00:00+00:00"))
        except ValueError as exc:
            results.append(str(exc))

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(not isinstance(result, dict) for result in results) == 1
    with ledger._connect() as conn:
        assert conn.execute("SELECT count(*) FROM delivery_attempts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM delivery_leases").fetchone()[0] == 1


def test_unknown_delivery_polling_is_available_to_scheduler(tmp_path):
    ledger = PublicationLedger(tmp_path / "state.db")
    intent = ledger.create_delivery_intent(_intent(job_id="poll-me"))
    attempt = ledger.begin_attempt(intent["intent_id"], "worker-1")
    ledger.finish_attempt(intent["intent_id"], attempt["attempt_id"], "unknown", error="timeout")

    seen = []
    report = scheduler.process_unknown_deliveries(
        Store(tmp_path / "state.db"),
        lambda immutable: seen.append(immutable) or {"status": "absent"},
        now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
    )

    assert report["polled"] == 1
    assert seen[0]["expected_description_digest"] == intent["expected_description_digest"]


def test_metric_collection_persists_attempt_and_releases_lease(tmp_path):
    store = Store(tmp_path / "state.db")
    published_at = datetime.now(timezone.utc) - timedelta(hours=2)
    identity = store.publication_ledger.register_verified_publication({
        "platform": "wechat",
        "internal_account_alias": "wechat_main",
        "platform_content_id": "wx-attempt",
        "canonical_url": "https://wechat.test/wx-attempt",
        "published_at": published_at.isoformat(),
        "verification": {"account_alias": "wechat_main", "content_id": "wx-attempt", "url": "https://wechat.test/wx-attempt", "published_at": published_at.isoformat(), "source": "management_page"},
    })
    report = collect_due_metric_windows(store.publication_ledger, lambda _: {"status": "unavailable", "reason": "backend down"})

    assert report["insufficient"] == 1
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM metric_collection_attempts").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM metric_collection_leases").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM metric_collection_retries").fetchone()[0] == 1
