import hashlib
import json
from datetime import datetime, timezone

from content_platform.platform_intelligence_state import evaluate_platform_history


def test_history_evaluator_verifies_archive_hash_before_calculating_growth(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    payloads = []
    for stamp, views in [("2026-09-15T00:00:00+00:00", 100), ("2026-09-15T12:00:00+00:00", 150)]:
        payload = {"items": [{
            "platform": "youtube", "content_id": "abc", "canonical_url": "https://www.youtube.com/watch?v=abc",
            "author": "Channel", "published_at": "2026-09-01T00:00:00+00:00", "observed_at": stamp,
            "native_verified": True, "raw_response_hash": "a" * 64, "metrics": {"views": views},
        }]}
        path = history / f"{views}.json"
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        payloads.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "observed_at": stamp})
    index = tmp_path / "index.jsonl"
    index.write_text("\n".join(json.dumps(entry) for entry in payloads) + "\n", encoding="utf-8")

    result = evaluate_platform_history(
        platform="youtube", lane="real_world_ai_implementation", history_index=index,
        now=datetime(2026, 9, 15, 13, tzinfo=timezone.utc),
    )

    assert result["state"] == "S2_DUAL_SNAPSHOT_GROWTH"
    assert result["history"]["verified_archives"] == 2
    assert result["growth"]["abc"]["metrics"]["views"]["delta"] == 50


def test_history_evaluator_fails_closed_for_tampered_archive(tmp_path):
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")
    index = tmp_path / "index.jsonl"
    index.write_text(json.dumps({"path": str(path), "sha256": "0" * 64}) + "\n", encoding="utf-8")

    result = evaluate_platform_history(platform="youtube", lane="real_world_ai_implementation", history_index=index)

    assert result["state"] == "S0_BLOCKED"
    assert "archive_hash_mismatch" in result["blocking_reason_codes"]
