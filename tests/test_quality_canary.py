from scripts.run_quality_canary import run_canary


def test_canary_is_reproducible_and_has_twelve_cases():
    report = run_canary()
    assert report["total"] == 12
    assert report["passed"] == 12
    assert all(case["input_sha256"] for case in report["cases"])
    assert all("evidence" in case for case in report["cases"])
    assert report["production_ready"] is False
    assert "ledger" in report["external_evidence_pending"]
