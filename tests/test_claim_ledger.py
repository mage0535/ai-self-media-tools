from content_platform.claim_ledger import compile_verified_claim_ledger, sanitize_unsupported_claims, validate_claims


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


def test_claim_gate_rejects_vague_personal_savings_and_no_code_claims() -> None:
    result = validate_claims("我之前订阅了七八个工具。费用砍掉一大半。这个平台不用写代码，一个平台全搞定。", [])
    assert result["passed"] is False
    assert "unsourced_first_person_operation" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_rejects_approximate_counts_half_hours_and_friend_anecdotes() -> None:
    result = validate_claims("手机里装了十几个工具，每天浪费半小时。朋友之前试了四五个平台。这个功能是免费的。", [])
    assert "unsourced_numeric_claim" in result["failures"]
    assert "unsourced_anecdote" in result["failures"]
    assert "unsourced_promotional_claim" in result["failures"]


def test_claim_gate_allows_non_quantitative_single_item_instructions() -> None:
    result = validate_claims("注册一个账号。选择一个入口。逐个检查接口。", [])
    assert result["passed"] is True


def test_verified_hotspot_text_compiles_to_claim_ledger_but_incomplete_evidence_does_not() -> None:
    hotspot = {
        "observed_title": "做内容还要在几十个AI工具之间来回切？",
        "source_url": "https://cp.kuaishou.com/profile",
        "snapshot_path": "hotspots/kuaishou.txt",
        "provenance_hash": "a" * 64,
        "evidence_type": "native",
        "evidence_verified": True,
    }
    ledger = compile_verified_claim_ledger({"associated_hotspot": hotspot})
    assert validate_claims(hotspot["observed_title"], ledger)["passed"] is True
    assert compile_verified_claim_ledger({"associated_hotspot": {**hotspot, "evidence_verified": False}}) == []


def test_claim_sanitizer_removes_only_unsupported_sentences() -> None:
    text = "This checklist is practical. Success rose 99% in 8 months. Verify the owner before acting."
    gate = validate_claims(text, [])
    cleaned = sanitize_unsupported_claims(text, gate["findings"])
    assert "99%" not in cleaned
    assert "Verify the owner" in cleaned
