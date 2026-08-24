from datetime import datetime, timezone

from content_platform.publication_ledger import PublicationLedger


def test_verified_publication_creates_three_metric_windows(tmp_path):
    ledger = PublicationLedger(tmp_path / "publication.db")
    identity = ledger.register_identity({"platform": "kuaishou", "account_id": "kuaishou_main", "platform_content_id": "ks-1", "canonical_url": "https://example.test/ks-1", "published_at": datetime.now(timezone.utc).isoformat(), "verification_level": "url_verified", "identity_source": "postcheck"})
    assert identity["passed"] is True
    windows = ledger.due_windows()
    assert [row["hours"] for row in windows] == [1, 24, 72]


def test_unverified_publication_does_not_create_metric_windows(tmp_path):
    ledger = PublicationLedger(tmp_path / "publication.db")
    identity = ledger.register_identity({"platform": "xiaohongshu", "account_id": "xiaohongshu_main", "platform_content_id": "", "canonical_url": "", "published_at": "", "verification_level": "user_confirmed", "identity_source": "manual"})
    assert identity["passed"] is False
    assert ledger.due_windows() == []


def test_empty_metrics_are_insufficient(tmp_path):
    ledger = PublicationLedger(tmp_path / "publication.db")
    ledger.register_identity({"platform": "x", "account_id": "x_main", "platform_content_id": "x-1", "canonical_url": "https://x.test/x-1", "published_at": datetime.now(timezone.utc).isoformat(), "verification_level": "url_verified", "identity_source": "postcheck"})
    window = ledger.due_windows()[0]
    result = ledger.record_metrics(window["id"], {})
    assert result["state"] == "insufficient"
