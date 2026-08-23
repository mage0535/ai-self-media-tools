"""Run due publication metric windows through explicit platform collectors."""

from __future__ import annotations

from datetime import datetime, timezone

from .publication_ledger import PublicationLedger


def run_due_collections(ledger: PublicationLedger, collector) -> dict:
    due = ledger.due_windows(datetime.now(timezone.utc))
    results = []
    for window in due:
        identity = ledger.identity_for_window(window["id"])
        if not identity:
            results.append({"window_id": window["id"], "status": "insufficient", "reason": "identity_missing"})
            continue
        try:
            metrics = collector(identity, window["window"])
            if not isinstance(metrics, dict):
                raise ValueError("collector must return an object")
            ok = ledger.record_metrics(identity["platform"], identity["account_alias"], identity["content_id"], window["window"], metrics)
            results.append({"window_id": window["id"], "status": "collected" if ok else "insufficient"})
        except Exception as exc:
            results.append({"window_id": window["id"], "status": "insufficient", "reason": f"collector_error:{type(exc).__name__}"})
    return {"due": len(due), "results": results}
