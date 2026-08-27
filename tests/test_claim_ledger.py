from content_platform.claim_ledger import sanitize_unsupported_claims, validate_claims


def test_claim_gate_rejects_unsourced_numeric_and_first_person_operations() -> None:
    result = validate_claims("我实测运行了 8 个月，成功率达到 99%。", [])
    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_first_person_operation" in result["failures"]


def test_claim_gate_accepts_claims_with_verifiable_evidence() -> None:
    text = "我实测运行了 8 个月，成功率达到 99%。"
    ledger = [{
        "claim": text,
        "source_url": "https://example.test/report",
        "evidence_path": "evidence/report.json",
        "verified": True,
    }]
    assert validate_claims(text, ledger)["passed"] is True


def test_claim_gate_rejects_malformed_code_fence() -> None:
    result = validate_claims("Run this:\n```python\nprint('x')", [])
    assert result["passed"] is False
    assert "malformed_code_fence" in result["failures"]


def test_claim_gate_allows_unsourced_advice_without_factual_claims() -> None:
    result = validate_claims("先确认负责人，再记录下一步。不要让工具替你猜。", [])
    assert result["passed"] is True


def test_claim_gate_rejects_unsourced_chinese_numbers_and_free_claims() -> None:
    result = validate_claims("三分钟通过审核。沙箱可以零成本试错。一个月省下两万元。", [])
    assert result["passed"] is False
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_sanitizer_removes_only_unsupported_sentences() -> None:
    text = "This checklist is practical. Success rose 99% in 8 months. Verify the owner before acting."
    gate = validate_claims(text, [])
    cleaned = sanitize_unsupported_claims(text, gate["findings"])
    assert "99%" not in cleaned
    assert "Verify the owner" in cleaned
