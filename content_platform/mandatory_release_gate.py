"""所有实际产物的 release/deliver 消费者；缺正常执行原件即阻断。

不生产 verdict，不接 packet/evidence 自报的 expected_context，不写 Store。
正常 runtime archive 必须在 data_dir/quality_runtime/job/platform/current.json。
本模块只消费其原执行存档；没有存档时不能以旧 optional 检查替代。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


class MandatoryReleaseBlocked(ValueError):
    pass


def _canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _ident(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise MandatoryReleaseBlocked("current_owner_id_invalid")
    return value


def _file_pin(path, expected=None):
    path = Path(path).expanduser()
    if not path.is_absolute() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise MandatoryReleaseBlocked("native_file_path_not_regular")
    before = path.stat()
    if not path.is_file() or not before.st_size:
        raise MandatoryReleaseBlocked("native_file_empty_or_missing")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise MandatoryReleaseBlocked("native_file_changed_during_read")
    actual = h.hexdigest()
    if expected is not None and expected != actual:
        raise MandatoryReleaseBlocked("native_file_hash_mismatch")
    return {"path": str(path.resolve()), "sha256": actual}


def _json(pin):
    value = json.loads(Path(pin["path"]).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise MandatoryReleaseBlocked("native_archive_object_required")
    return value


def _required_pin(value, label):
    if (not isinstance(value, dict) or not isinstance(value.get("path"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256") or ""))):
        raise MandatoryReleaseBlocked(label + "_pin_missing")
    return _file_pin(value["path"], value["sha256"])


def _source_pin(path):
    # native 安装路径可以是受管理alias；明确resolve后回读实际原文件。
    return _file_pin(Path(path).expanduser().resolve(strict=True))


def _contract_sidecar(data_dir, job_id, platform, contract):
    if not isinstance(contract, dict) or not contract:
        raise MandatoryReleaseBlocked("current_store_run_contract_missing")
    raw = json.dumps(contract, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    folder = Path(data_dir).resolve() / "quality_runtime" / job_id / platform / "source_bytes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("store-run-contract-" + sha + ".json")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return _file_pin(path, sha)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return _file_pin(path, sha)


def _scoped_store(store, platform):
    class ScopedStore:
        def __getattr__(self, name):
            return getattr(store, name)
        def get_job(self, job_id):
            current = store.get_job(job_id)
            if platform not in current.get("platforms", []):
                raise MandatoryReleaseBlocked("current_store_platform_missing")
            from .task_source_inputs import project_task_source_job
            scoped = project_task_source_job(current, platform)
            # 保真实多平台ownership，不能让单平台view借用global copy。
            scoped["platforms"] = current["platforms"]
            if scoped.get("id") != current.get("id"):
                raise MandatoryReleaseBlocked("native_scope_job_changed")
            return scoped
    return ScopedStore()


def _resolve_current_policy(store, data_dir, job_id, platform):
    """仅正常 loader 和当前 Store 来源，不取archive/report指定规则位置。"""
    from . import platform_workflow_context as loader
    job = store.get_job(job_id)
    brief = job.get("brief") or {}
    context = loader.load_platform_workflow_context(platform, plan=brief)
    if not isinstance(context, dict) or not isinstance(context.get("strategy"), dict):
        raise MandatoryReleaseBlocked("normal_platform_workflow_context_missing")
    strategy = context["strategy"]
    if not strategy.get("path"):
        raise MandatoryReleaseBlocked("normal_current_strategy_source_missing")
    contract = brief.get("run_contract")
    if not isinstance(contract, dict):
        raise MandatoryReleaseBlocked("normal_current_store_contract_missing")
    steps = store.workflow_steps(job_id)
    from .visual_candidate_revision import current_visual_binding
    from .native_quality_resume import current_binding as current_quality_binding
    source_revision=current_quality_binding(store,job_id,platform) or current_visual_binding(store,job_id,platform)
    if source_revision is not None:
        actual=source_revision['row']
        if (actual not in steps or actual.get('status')!='SUCCEEDED'
                or actual.get('job_id')!=job_id or actual.get('platform')!=platform
                or (actual.get('output')or{}).get('artifact_manifest')!=source_revision['manifest_ref']):
            raise MandatoryReleaseBlocked('current_source_revision_actual_binding_changed')
        bindings=[actual]
    else:
        bindings = [row for row in steps if row.get("status") == "SUCCEEDED"
            and row.get("platform") == platform
            and row.get("step_name") == "bind_rendered_artifact_sources"]
    binding_pin = None
    binding_roles = set()
    if bindings:
        if len(bindings) != 1:
            raise MandatoryReleaseBlocked("normal_artifact_binding_ambiguous")
        binding_pin = _required_pin((bindings[0].get("output") or {}).get("artifact_manifest"),
            "normal_artifact_binding")
        binding_manifest = _json(binding_pin)
        if binding_manifest.get("job_id") != job_id or binding_manifest.get("platform") != platform:
            raise MandatoryReleaseBlocked("normal_artifact_binding_owner_mismatch")
        binding_roles = {row.get("role") for row in binding_manifest.get("artifacts") or []
                         if isinstance(row, dict)}
    names = set(contract.get("required_skills") or [])
    names.update({"meta/content-preflight", "content/content-strategy-workflow"})
    current_rows = store.platform_outputs(job_id, platform=platform)
    visual_roles = {"video", "cover", "image", "inline_image", "project_screenshot",
        "knowledge_card", "article_card", "background", "article_html", "wechat_format"}
    form = str(brief.get("content_form") or (job.get("draft_meta") or {}).get("content_form") or "")
    if any(row.get("role") in visual_roles for row in current_rows) or binding_roles & visual_roles:
        names.update({"content/visual-quality-standards", "cover-film-poster"})
    if any(token in form for token in ("video", "image", "card", "carousel")):
        names.update({"content/visual-quality-standards", "content/knowledge-card-designer", "cover-film-poster"})
    # additional loader skills 是实际当前source catalogue，而非模型skill名单。
    for item in context.get("skills") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise MandatoryReleaseBlocked("normal_current_skill_catalogue_invalid")
        names.add(item["name"])
    policy = {
        "rulebook": _source_pin(loader.RULEBOOK),
        "directive": _source_pin(Path(loader.ROOT) / "docs" / "CONTENT_OPERATIONS_QUALITY_DIRECTIVE.md"),
        "strategy": _source_pin(strategy["path"]),
        "run_contract": _contract_sidecar(data_dir, job_id, platform, contract),
        "skills": {name: _source_pin(loader._skill_path(name)) for name in sorted(names)},
        # 目前没有已核完整能力的canonical native program catalogue。
        # 明确空集，不能从model/report/archive自己选echo/tmp脚本补资格。
        "program_sources": {},
    }
    if strategy.get("sha256") and policy["strategy"]["sha256"] != strategy["sha256"]:
        raise MandatoryReleaseBlocked("normal_current_strategy_changed")
    # 仅正常Store workflow output可补现renderer归属索引，不能取模型packet。
    if binding_pin:
        policy["artifact_manifest"] = binding_pin
    return policy


def _helpers():
    from . import mandatory_quality_context as contexts
    from . import mandatory_final_quality_evidence as final
    return contexts, final


def mandatory_release_gate(store, data_dir, job_id, platform, *, phase="release"):
    from .mandatory_quality_context import policy_yaml_read_scope
    with policy_yaml_read_scope():
        return _mandatory_release_gate_body(store, data_dir, job_id, platform, phase=phase)


def _mandatory_release_gate_body(store, data_dir, job_id, platform, *, phase="release"):
    """渲染登记后与publisher构造前都调用；返回明确passed或blocked。"""
    try:
        job_id = _ident(job_id)
        platform = _ident(str(platform).casefold().strip())
        if phase not in {"release", "deliver"}:
            raise MandatoryReleaseBlocked("mandatory_gate_phase_invalid")
        runtime_root = Path(data_dir).resolve() / "quality_runtime" / job_id / platform
        archive_path = runtime_root / "current.json"
        if not archive_path.is_file():
            raise MandatoryReleaseBlocked("normal_quality_runtime_archive_missing")
        archive_pin = _file_pin(archive_path)
        archive = _json(archive_pin)
        if (archive.get("version") != "native_quality_runtime_archive_v1"
                or archive.get("job_id") != job_id or archive.get("platform") != platform
                or archive.get("phase") != "release"):
            raise MandatoryReleaseBlocked("normal_quality_runtime_archive_scope_mismatch")
        records = archive.get("execution_records")
        if not isinstance(records, dict) or set(records) != {"skills", "checks"}:
            raise MandatoryReleaseBlocked("normal_quality_runtime_execution_records_missing")
        contexts, final = _helpers()
        scoped = _scoped_store(store, platform)
        policy = _resolve_current_policy(scoped, data_dir, job_id, platform)
        prepared = contexts.prepare_current_quality_context(scoped, data_dir, job_id, platform, current_policy=policy)
        context_sha = contexts.canonical_sha(prepared)
        if archive.get("context_sha256") != context_sha:
            raise MandatoryReleaseBlocked("normal_quality_runtime_current_context_mismatch")
        expected = contexts.build_current_expected_context(scoped, data_dir, job_id, platform,
            current_policy=policy, execution_records=records)
        if final.final_quality_context(expected) != prepared:
            raise MandatoryReleaseBlocked("final_validator_current_source_identity_incomplete")
        reports = archive.get("final_reports")
        if not isinstance(reports, dict):
            raise MandatoryReleaseBlocked("normal_quality_runtime_part_reports_missing")
        verified = {}
        for role, pins in prepared["parts"].items():
            verified[role] = []
            for part in pins:
                actual = _file_pin(part["path"], part["sha256"])
                report = reports.get(actual["sha256"])
                if not isinstance(report, dict):
                    raise MandatoryReleaseBlocked("normal_quality_runtime_part_report_missing:" + role)
                report_pin = _required_pin(report, "normal_quality_runtime_part_report")
                report_path = Path(report_pin["path"])
                if not report_path.is_relative_to(runtime_root):
                    raise MandatoryReleaseBlocked("normal_quality_runtime_part_report_outside_archive")
                result = final.validate_final_quality_evidence(Path(actual["path"]), _json(report_pin), expected_context=expected)
                if result.get("passed") is not True:
                    raise MandatoryReleaseBlocked("normal_quality_runtime_part_not_passed:" + role)
                verified[role].append(actual)
        # 当次完整消费过程中存档不得替换。
        _file_pin(archive_pin["path"], archive_pin["sha256"])
        return {"passed": True, "state": "qualified", "phase": phase,
            "job_id": job_id, "platform": platform, "context_sha256": context_sha,
            "archive": archive_pin, "verified_parts": verified}
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        return {"passed": False, "state": "blocked", "phase": phase,
            "job_id": job_id, "platform": platform,
            "failures": [str(exc) or type(exc).__name__]}
