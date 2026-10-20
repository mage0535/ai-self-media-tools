"""Bind final AUTO/VLM/WATCH reports to the pipeline's current revision.

The caller supplies applicability compiled from the current rule sources and
pins executions accepted by the existing quality runners. A report can neither
select weaker rules nor exempt its own assets. This verifies evidence identity
and coverage; it does not turn a synthetic receipt into a semantic review.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class InvalidFinalQualityEvidence(ValueError):
    pass


CHANNELS = ("auto", "vlm", "watch")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def candidate_sha256(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise InvalidFinalQualityEvidence("final candidate is missing")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _pin(pin: dict, label: str) -> dict:
    if (not isinstance(pin, dict) or not isinstance(pin.get("path"), str)
            or not pin["path"].strip() or not SHA256.fullmatch(str(pin.get("sha256") or ""))):
        raise InvalidFinalQualityEvidence(f"{label}_pin_invalid")
    path = Path(pin["path"]).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise InvalidFinalQualityEvidence(f"{label}_file_missing")
    if candidate_sha256(path) != pin["sha256"]:
        raise InvalidFinalQualityEvidence(f"{label}_hash_mismatch")
    return {"path": str(path.resolve()), "sha256": pin["sha256"]}


def _read_object(pin: dict, label: str) -> dict:
    try:
        value = json.loads(Path(pin["path"]).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise InvalidFinalQualityEvidence(f"{label}_unreadable") from exc
    if not isinstance(value, dict):
        raise InvalidFinalQualityEvidence(f"{label}_not_object")
    return value


def _names(value, label: str, *, allow_empty: bool = False) -> list[str]:
    if (not isinstance(value, (list, tuple)) or (not value and not allow_empty)
            or any(not isinstance(name, str) or not name.strip() for name in value)
            or len(set(value)) != len(value)):
        raise InvalidFinalQualityEvidence(f"{label}_invalid")
    return sorted(value)


def final_quality_context(expected_context: dict | None) -> dict:
    """Re-read current sources and parts; only call with pipeline/store facts.

    required_checks, check_parts and not_applicable are current rule compilation
    results, never fields copied from an untrusted report or packet. Execution
    files are separately pinned to avoid a recursive context hash.
    """
    if not isinstance(expected_context, dict) or not expected_context:
        raise InvalidFinalQualityEvidence("expected_context_missing")
    context = {}
    for key in ("version", "job_id", "platform", "account_id", "lane", "content_type", "revision_id", "phase"):
        value = expected_context.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidFinalQualityEvidence(f"expected_context_{key}_missing")
        context[key] = value
    if context["phase"] != "release":
        raise InvalidFinalQualityEvidence("expected_context_release_phase_required")
    draft = expected_context.get("draft_version_id")
    if not ((type(draft) is int and draft > 0) or (isinstance(draft, str) and draft.strip())):
        raise InvalidFinalQualityEvidence("expected_context_draft_version_id_missing")
    context["draft_version_id"] = draft
    compiled = expected_context.get("strategy_compiled_sha256")
    if not SHA256.fullmatch(str(compiled or "")):
        raise InvalidFinalQualityEvidence("expected_context_strategy_compiled_sha256_missing")
    context["strategy_compiled_sha256"] = compiled
    for key in ("run_contract", "rulebook", "directive", "strategy"):
        context[key] = _pin(expected_context.get(key), f"expected_context_{key}")
    programs = expected_context.get("program_sources")
    if not isinstance(programs, dict):
        raise InvalidFinalQualityEvidence("expected_context_program_sources_missing")
    context["program_sources"] = {name: _pin(pin, f"program_{name}") for name, pin in programs.items()}
    skills = expected_context.get("skills")
    if not isinstance(skills, dict) or not skills:
        raise InvalidFinalQualityEvidence("expected_context_skills_missing")
    if any(not isinstance(name, str) or not name.strip() for name in skills):
        raise InvalidFinalQualityEvidence("expected_context_skill_id_invalid")
    context["skills"] = {name: _pin(pin, f"skill_{name}") for name, pin in skills.items()}
    parts = expected_context.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise InvalidFinalQualityEvidence("expected_context_parts_missing")
    context["parts"] = {}
    for name, pins in parts.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(pins, list) or not pins:
            raise InvalidFinalQualityEvidence("expected_context_part_invalid")
        checked = [_pin(pin, f"part_{name}") for pin in pins]
        if len({row["path"] for row in checked}) != len(checked):
            raise InvalidFinalQualityEvidence(f"part_{name}_duplicate")
        context["parts"][name] = checked
    required = expected_context.get("required_checks")
    applicability = expected_context.get("not_applicable") or {}
    if not isinstance(applicability, dict):
        raise InvalidFinalQualityEvidence("expected_context_applicability_invalid")
    if not isinstance(required, dict) or set(required) != set(CHANNELS):
        raise InvalidFinalQualityEvidence("expected_context_required_checks_missing")
    context["required_checks"] = {}
    context["not_applicable"] = {}
    for channel in CHANNELS:
        names = _names(required[channel], f"{channel}_required_checks", allow_empty=True)
        context["required_checks"][channel] = names
        if not names:
            decision = applicability.get(channel)
            if (not isinstance(decision, dict) or not str(decision.get("reason") or "").strip()
                    or not str(decision.get("rule_id") or "").strip()
                    or decision.get("source_sha256") not in {context["rulebook"]["sha256"], *[p["sha256"] for p in context["skills"].values()]}):
                raise InvalidFinalQualityEvidence(f"{channel}_applicability_unproven")
            context["not_applicable"][channel] = dict(decision)
    if not any(context["required_checks"].values()):
        raise InvalidFinalQualityEvidence("expected_context_all_checks_exempted")
    check_parts = expected_context.get("check_parts")
    if not isinstance(check_parts, dict):
        raise InvalidFinalQualityEvidence("expected_context_check_parts_missing")
    context["check_parts"] = {}
    covered = set()
    for name in set().union(*map(set, context["required_checks"].values())):
        bound = _names(check_parts.get(name), f"check_{name}_parts")
        if not set(bound) <= set(context["parts"]):
            raise InvalidFinalQualityEvidence(f"check_{name}_part_missing")
        context["check_parts"][name] = bound
        covered.update(bound)
    if covered != set(context["parts"]):
        raise InvalidFinalQualityEvidence("expected_context_unreviewed_parts")
    return context


def _execution(pin: dict, label: str, context: dict, parts: dict, **scope) -> tuple[dict, dict]:
    # Re-use the normal builder's raw/native/session validation rather than accepting a second,
    # weaker receipt format at final delivery.
    try:
        from .mandatory_quality_context import _execution as validate_native_execution, QualityContextBlocked
    except ImportError as exc:
        raise InvalidFinalQualityEvidence("native_quality_context_validator_missing") from exc
    try:
        checked = validate_native_execution(pin, label, context, parts, **scope)
    except QualityContextBlocked as exc:
        raise InvalidFinalQualityEvidence(str(exc)) from exc
    return checked, _read_object(checked, label)


def validate_final_quality_evidence(candidate: Path, evidence: dict, *,
                                    expected_context: dict | None = None) -> dict:
    context = final_quality_context(expected_context)
    context_sha = _canonical_sha256(context)
    digest = candidate_sha256(candidate)
    if digest not in {p["sha256"] for pins in context["parts"].values() for p in pins}:
        raise InvalidFinalQualityEvidence("candidate_not_in_current_parts")
    if not isinstance(evidence, dict) or evidence.get("version") != "final_quality_evidence_v1":
        raise InvalidFinalQualityEvidence("final_quality_evidence_invalid")
    if evidence.get("candidate_sha256") != digest:
        raise InvalidFinalQualityEvidence("final_quality_evidence_candidate_hash_mismatch")
    if evidence.get("context") != context or evidence.get("context_sha256") != context_sha:
        raise InvalidFinalQualityEvidence("final_quality_evidence_context_mismatch")
    skills = expected_context.get("skill_executions")
    if not isinstance(skills, dict) or set(skills) != set(context["skills"]):
        raise InvalidFinalQualityEvidence("skill_executions_missing")
    checked_skills = {}
    for name, skill in context["skills"].items():
        pin, execution = _execution(skills[name], f"skill_{name}", context, context["parts"], skill_id=name)
        if execution.get("skill_id") != name or execution.get("skill_sha256") != skill["sha256"]:
            raise InvalidFinalQualityEvidence(f"skill_{name}_execution_source_mismatch")
        checked_skills[name] = pin
    executions = expected_context.get("check_executions")
    if not isinstance(executions, dict):
        raise InvalidFinalQualityEvidence("check_executions_missing")
    checked_reports = {}
    for channel in CHANNELS:
        item = evidence.get(channel)
        if not isinstance(item, dict) or item.get("candidate_sha256") != digest or item.get("passed") is not True:
            raise InvalidFinalQualityEvidence(f"{channel}_evidence_not_passed")
        pin = _pin({"path": item.get("evidence_path"), "sha256": item.get("evidence_sha256")}, f"{channel}_report")
        report = _read_object(pin, f"{channel}_report")
        if (report.get("candidate_sha256") != digest or report.get("channel") != channel
                or report.get("passed") is not True or report.get("context") != context
                or report.get("context_sha256") != context_sha
                or not str(report.get("producer") or report.get("reviewer") or "").strip()
                or report.get("skill_executions") != checked_skills):
            raise InvalidFinalQualityEvidence(f"{channel}_report_context_mismatch")
        names = context["required_checks"][channel]
        if not names:
            if report.get("checks") != [] or report.get("not_applicable") != context["not_applicable"][channel]:
                raise InvalidFinalQualityEvidence(f"{channel}_applicability_mismatch")
        else:
            checks = report.get("checks")
            if (not isinstance(checks, list) or any(not isinstance(row, dict)
                    or not isinstance(row.get("name"), str) for row in checks)
                    or len(checks) != len(names) or {row.get("name") for row in checks} != set(names)):
                raise InvalidFinalQualityEvidence(f"{channel}_required_checks_mismatch")
            channel_exec = executions.get(channel)
            if not isinstance(channel_exec, dict) or set(channel_exec) != set(names):
                raise InvalidFinalQualityEvidence(f"{channel}_executions_missing")
            for row in checks:
                name = row["name"]
                if row.get("passed") is not True or row.get("verdict") != "passed":
                    raise InvalidFinalQualityEvidence(f"{channel}_{name}_not_passed")
                parts = {part: context["parts"][part] for part in context["check_parts"][name]}
                exec_pin, execution = _execution(channel_exec[name], f"{channel}_{name}", context, parts,
                                                  channel=channel, check_name=name)
                if (execution.get("check_name") != name or execution.get("channel") != channel
                        or row.get("execution") != exec_pin):
                    raise InvalidFinalQualityEvidence(f"{channel}_{name}_execution_binding_mismatch")
        checked_reports[channel] = pin
    return {"passed": True, "candidate_sha256": digest, "context_sha256": context_sha,
            "revision_id": context["revision_id"], "channels": list(CHANNELS), "reports": checked_reports}
