from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_strategy_skill_audit_accepts_matching_declared_facts(tmp_path: Path):
    from scripts.audit_strategy_skill_conflicts import audit

    policy = tmp_path / "policy.json"
    skill = tmp_path / "SKILL.md"
    _write_json(policy, {"wechat": {"articles_per_week": 2, "newspic_dual_track": True}, "video": {"vertical_resolution": "1080x1920", "short_max_seconds": 60, "layered_motion": True}})
    skill.write_text("wechat_articles_per_week: 2\nnewspic_dual_track: true\nvertical_resolution: 1080x1920\nshort_max_seconds: 60\nlayered_motion: true\n", encoding="utf-8")

    result = audit(policy, [skill])

    assert result["passed"] is True


def test_strategy_skill_audit_reports_frequency_conflict(tmp_path: Path):
    from scripts.audit_strategy_skill_conflicts import audit

    policy = tmp_path / "policy.json"
    skill = tmp_path / "SKILL.md"
    _write_json(policy, {"wechat": {"articles_per_week": 2, "newspic_dual_track": True}, "video": {"vertical_resolution": "1080x1920", "short_max_seconds": 60, "layered_motion": True}})
    skill.write_text("wechat_articles_per_week: 3\nnewspic_dual_track: true\nvertical_resolution: 1080x1920\nshort_max_seconds: 60\nlayered_motion: true\n", encoding="utf-8")

    result = audit(policy, [skill])

    assert result["passed"] is False
    assert result["conflicts"][0]["field"] == "wechat_articles_per_week"


def test_rulebook_validator_uses_operations_policy_contract(monkeypatch, tmp_path: Path):
    from scripts import validate_channel_rulebook as validator

    policy = tmp_path / "policy.json"
    contract = tmp_path / "OPERATIONS_POLICY_CONTRACT.md"
    _write_json(policy, {"wechat": {"articles_per_week": 2, "newspic_dual_track": True}, "video": {"vertical_resolution": "1080x1920", "short_max_seconds": 60, "layered_motion": True}})
    contract.write_text("wechat_articles_per_week: 3\n", encoding="utf-8")
    monkeypatch.setattr(validator, "OPERATIONS_POLICY_PATH", policy)
    monkeypatch.setattr(validator, "OPERATIONS_CONTRACT_PATH", contract)

    result = validator.operations_policy_audit()

    assert result["passed"] is False


def test_rulebook_validator_runs_as_a_direct_script():
    root = Path(__file__).resolve().parents[1]

    process = subprocess.run(
        [sys.executable, "scripts/validate_channel_rulebook.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert "channel rulebook ok" in process.stdout
