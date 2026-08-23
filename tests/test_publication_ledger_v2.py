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
