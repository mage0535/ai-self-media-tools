from datetime import datetime, timezone

from content_platform.publication_ledger import PublicationLedger
from content_platform.publication_metrics import run_due_collections


def test_only_verified_publication_creates_metric_windows(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    assert ledger.register({"platform": "wechat", "internal_account_alias": "wechat_main", "platform_content_id": "media-1", "canonical_url": "https://example.test/a", "published_at": datetime.now(timezone.utc).isoformat(), "verification_level": "postcheck_verified"})["ok"]
    assert len(ledger.due_windows(now=datetime.now(timezone.utc))) == 0
    assert ledger.register({"platform": "wechat", "internal_account_alias": "wechat_main", "platform_content_id": "draft-1", "canonical_url": "", "published_at": "", "verification_level": "publisher_result"})["ok"] is False


def test_insufficient_metrics_are_not_analysis_ready(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    identity = {"platform": "x", "internal_account_alias": "x_main", "platform_content_id": "tweet-1", "canonical_url": "https://x.com/a/status/1", "published_at": datetime.now(timezone.utc).isoformat(), "verification_level": "url_verified"}
    ledger.register(identity)
    for window in ("1h", "24h", "72h"):
        ledger.record_metrics(identity["platform"], identity["internal_account_alias"], identity["platform_content_id"], window, {"views": None})
    assert ledger.ready_for_analysis() == []


def test_due_collector_failure_is_insufficient_not_fake_zero(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    identity = {"platform": "x", "internal_account_alias": "x_main", "platform_content_id": "tweet-2", "canonical_url": "https://x.com/a/status/2", "published_at": "2020-01-01T00:00:00+00:00", "verification_level": "url_verified"}
    ledger.register(identity)
    report = run_due_collections(ledger, lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    assert report["results"][0]["status"] == "insufficient"
    assert ledger.ready_for_analysis() == []


def test_empty_metrics_are_insufficient(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    identity = {"platform": "x", "internal_account_alias": "x_main", "platform_content_id": "tweet-3", "canonical_url": "https://x.com/a/status/3", "published_at": "2020-01-01T00:00:00+00:00", "verification_level": "url_verified"}
    ledger.register(identity)
    assert ledger.record_metrics("x", "x_main", "tweet-3", "1h", {}) is True
    assert ledger.ready_for_analysis() == []


def test_ledger_records_required_metrics_and_observation_attempt_tables(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    identity = {"platform": "x", "internal_account_alias": "x_main", "platform_content_id": "tweet-4", "canonical_url": "https://x.com/a/status/4", "published_at": "2020-01-01T00:00:00+00:00", "verification_level": "url_verified"}
    ledger.register(identity)
    assert ledger.record_metrics("x", "x_main", "tweet-4", "1h", {"views": 10, "likes": 2, "comments": 1, "shares": 1}) is True
    with ledger._connect() as conn:
        tables = {row["name"] for row in conn.execute("select name from sqlite_master where type='table'")}
        assert {"metric_observations", "metric_collection_attempts"} <= tables
        assert conn.execute("select count(*) from metric_observations").fetchone()[0] == 1


def test_missing_required_metric_is_insufficient(tmp_path):
    ledger = PublicationLedger(tmp_path / "ledger.db")
    identity = {"platform": "x", "internal_account_alias": "x_main", "platform_content_id": "tweet-5", "canonical_url": "https://x.com/a/status/5", "published_at": "2020-01-01T00:00:00+00:00", "verification_level": "url_verified"}
    ledger.register(identity)
    ledger.record_metrics("x", "x_main", "tweet-5", "1h", {"views": 10})
    assert ledger.ready_for_analysis() == []
