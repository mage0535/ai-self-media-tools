"""从当前 Store、原规则及实物建立最终审核上下文。

本模块不生成审核 verdict，不读报告自己的 context/parts，不写 Store。
prepare 仅提供待执行的来源上下文；build 缺正常执行原件时抛出阻断。
文本侧车只是 Store 原文字节的不可变表示，不是新内容或业务审核。
"""
from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import shlex
import sqlite3
from pathlib import Path


VERSION = "fix_quality_context_20261013"
CHANNELS = ("auto", "vlm", "watch")
SHA = re.compile(r"^[0-9a-f]{64}$")
VIDEO_FORMS = {"short_video", "edited_short_video", "microcase_video", "cat_knowledge_video",
    "knowledge_image_video", "knowledge_card_video", "image_card_knowledge_video",
    "visual_card_voiceover", "tutorial_video", "short_viral_video", "long_form_tutorial",
    "shorts_tip", "practical_workflow_demo"}
ARTICLE_FORMS = {"long_form_article", "image_text_article", "technical_longform", "tutorial",
    "reasoned_longform", "column_article", "technical_article", "short_article", "email_newsletter",
    "long_article", "evidence_answer"}  # overnight slot forms (10-31)
IMAGE_FORMS = {"image_text_note", "knowledge_card_block", "carousel", "image_text_post", "manual_carousel"}
TEXT_FORMS = {"short_post", "thread_post", "short_anonymous_post"}
PIECE_FORMS = {"title", "body", "image", "cover", "article_card", "knowledge_card",
    "voiceover", "tts", "subtitle", "subtitles", "bgm", "rewrite", "translation"}
ALIASES = {"weixin": "wechat", "wechat_official": "wechat", "rednote": "xiaohongshu",
    "x": "twitter", "douyin_pet": "douyin"}
ROLES = {"video": "video", "cover": "covers", "image": "images", "inline_image": "images",
    "project_screenshot": "images", "article_card": "article_cards", "knowledge_card": "article_cards",
    "background": "backgrounds", "background_asset": "backgrounds", "narration": "narration",
    "voiceover": "narration", "tts": "narration", "audio": "narration", "voice_segment": "voice_segments",
    "bgm": "bgm", "background_music": "bgm", "subtitle": "subtitles", "subtitles": "subtitles",
    "srt": "subtitles", "vtt": "subtitles", "rights": "rights", "license": "rights",
    "script": "source_script", "source_script": "source_script", "source_text": "source_text",
    "article": "article_render", "html": "article_render", "article_html": "article_render",
    "wechat_format": "article_render", "markdown": "article_render",
    "render_manifest": "render_manifest", "article_artifact_manifest": "render_manifest"}
VISUAL_PARTS = {"video", "covers", "images", "article_cards", "backgrounds", "article_render"}
AUDIO_PARTS = {"video", "narration", "voice_segments", "bgm", "subtitles", "source_script"}
NATIVE_TASK_ROOTS = tuple(Path(p) for p in ("/srv/hermes-worker", "/srv/hermes-worker-interactive",
    "/srv/hermes-worker-interactive-control", "/srv/hermes-worker-media"))
NATIVE_HOME_ROOT = Path("/srv/hermes-worker/authority-runtime-homes")
SEMANTIC_AUTO_CHECKS = {"content_facts_risk_humanization", "semantic_fidelity_and_certainty",
    "target_language_and_full_text", "content_blueprint"}


class QualityContextBlocked(ValueError):
    """来源、实物或正常执行未闭合，不能进入交付。"""



from contextlib import contextmanager
from contextvars import ContextVar

_POLICY_YAML_READ_SCOPE = ContextVar('native_policy_yaml_read_scope', default=None)


@contextmanager
def policy_yaml_read_scope():
    """One full gate only. Nested/concurrent calls own separate parsing dictionaries."""
    parsed = {}
    token = _POLICY_YAML_READ_SCOPE.set(parsed)
    try:
        yield
    finally:
        parsed.clear()
        _POLICY_YAML_READ_SCOPE.reset(token)


def _read_native_policy_yaml(pin, task_id):
    import yaml
    raw = Path(pin['path']).read_bytes()
    parsed = _POLICY_YAML_READ_SCOPE.get()
    if parsed is None:
        return yaml.safe_load(raw)
    # _pin has already checked the live original. Close its read/parse race too.
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        _fail('native_profile_config_changed_during_read')
    key = (task_id, pin['path'], pin['sha256'])
    if key not in parsed:
        parsed[key] = yaml.safe_load(raw)
    return parsed[key]

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _fail(reason):
    raise QualityContextBlocked(reason)


def _pin(value, label):
    if (not isinstance(value, dict) or not isinstance(value.get("path"), str)
            or not SHA.fullmatch(str(value.get("sha256") or ""))):
        _fail(label + "_pin_missing")
    path = Path(value["path"]).expanduser()
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        _fail(label + "_path_not_regular")
    try:
        before = path.stat()
        if not path.is_file() or not before.st_size:
            _fail(label + "_file_empty_or_missing")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as exc:
        raise QualityContextBlocked(label + "_file_missing") from exc
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        _fail(label + "_changed_during_read")
    if digest.hexdigest() != value["sha256"]:
        _fail(label + "_hash_mismatch")
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def _object(pin, label):
    try:
        value = json.loads(Path(pin["path"]).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise QualityContextBlocked(label + "_json_unreadable") from exc
    if not isinstance(value, dict):
        _fail(label + "_object_required")
    return value


def _compile_strategy(pin, platform):
    try:
        from .strategy_compiler import compile_strategy, validate_compiled_strategy
    except ImportError as exc:
        raise QualityContextBlocked("native_strategy_compiler_unavailable") from exc
    result = compile_strategy(Path(pin["path"]), platform)
    if not validate_compiled_strategy(result).get("passed"):
        _fail("current_strategy_compilation_failed")
    return canonical_sha(result)


def _source_policy(policy, platform, job):
    if not isinstance(policy, dict):
        _fail("current_policy_missing")
    pins = {key: _pin(policy.get(key), "current_" + key)
            for key in ("rulebook", "directive", "run_contract", "strategy")}
    rules = _object(pins["rulebook"], "rulebook")
    contract = _object(pins["run_contract"], "run_contract")
    entry = (rules.get("channel_rules") or {}).get(ALIASES.get(platform, platform))
    if not isinstance(entry, dict) or entry.get("status") == "unsupported_pre_onboarding":
        _fail("current_platform_rules_missing_or_unsupported")
    if (contract.get("platform") != platform or contract.get("version") != "run_contract_v1"
            or contract.get("enforce_strategy_evidence") is not True
            or contract.get("strategy_evidence_required") is not True
            or contract.get("channel_rules") != entry
            or contract.get("mandatory_sequence") != rules.get("mandatory_sequence")
            or (contract.get("rulebook") or {}).get("sha256") != pins["rulebook"]["sha256"]
            or (contract.get("rulebook") or {}).get("version") != rules.get("version")
            or contract.get("visual_quality_standards") != rules.get("visual_quality_standards")
            or (job.get("brief") or {}).get("run_contract") != contract):
        _fail("current_run_contract_source_mismatch")
    skills = policy.get("skills")
    if not isinstance(skills, dict) or not skills:
        _fail("current_skill_sources_missing")
    return pins, rules, contract, entry, skills


def _text_pin(data_dir, job_id, platform, role, text):
    if not isinstance(text, str) or not text.strip():
        _fail("current_" + role + "_missing")
    raw = text.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    for name in (str(job_id), str(platform)):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            _fail("current_owner_id_invalid")
    folder = Path(data_dir).resolve() / "artifacts" / str(job_id) / "platforms" / platform / "quality_source_bytes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (role + "-" + digest + ".txt")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _pin({"path": str(path), "sha256": digest}, role)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return _pin({"path": str(path), "sha256": digest}, role)


def current_draft_source_sha256(scoped_job, draft_version_id):
    return canonical_sha({"draft_version_id": draft_version_id,
        "title": scoped_job.get("title"), "body": scoped_job.get("body"),
        "brief_sources": (scoped_job.get("brief") or {}).get("sources") or [],
        "draft_source_catalog": (scoped_job.get("draft_meta") or {}).get("source_catalog") or []})


def _formatted_copy(job, platform):
    try:
        from .formatters import format_for_platform
    except ImportError as exc:
        raise QualityContextBlocked("native_current_formatter_unavailable") from exc
    return format_for_platform(job, platform)


def _owned_rows(store, job, platform, version, policy):
    rows = store.platform_outputs(job["id"], platform)
    rows = [row for row in rows if row.get("draft_version_id") == version]
    if rows:
        if any(row.get("job_id") != job["id"] or row.get("platform") != platform for row in rows):
            _fail("artifact_platform_owner_mismatch")
        revisions = {row.get("content_revision") for row in rows}
        if len(revisions) != 1 or not next(iter(revisions)):
            _fail("artifact_revision_owner_mismatch")
        return next(iter(revisions)), rows
    # 正常 renderer 的来源 manifest 只桥接尚未登记 platform_outputs 的产物。
    # 必须与真实 Store artifact ID/path/hash 逐项一致；不接受报告里的 parts。
    source = _pin(policy.get("artifact_manifest"), "native_artifact_owner_manifest")
    manifest = _object(source, "native_artifact_owner_manifest")
    if (manifest.get("version") != "native_render_artifact_binding_v1"
            or manifest.get("job_id") != job["id"] or manifest.get("platform") != platform
            or manifest.get("draft_version_id") != version or not manifest.get("revision_id")):
        _fail("native_artifact_revision_owner_missing")
    registered = {row.get("id"): row for row in store.artifacts(job["id"])}
    result = []
    for row in manifest.get("artifacts") or []:
        original = registered.get(row.get("artifact_id"))
        if (not original or original.get("job_id") != job["id"]
                or row.get("path") != original.get("path")
                or row.get("checksum") != original.get("checksum")):
            _fail("native_artifact_store_binding_mismatch")
        if row.get("role") == "copy" and original.get("kind") != "platform_copy":
            _fail("native_copy_artifact_kind_mismatch")
        result.append(dict(row, job_id=job["id"], platform=platform,
            draft_version_id=version, content_revision=manifest["revision_id"]))
    if not result:
        _fail("native_artifact_store_binding_missing")
    return manifest["revision_id"], result


def _current_parts(store, data_dir, job, platform, policy):
    versions = store.draft_versions(job["id"])
    if not versions or not versions[-1].get("id"):
        _fail("current_store_draft_version_missing")
    version = versions[-1]
    revision, rows = _owned_rows(store, job, platform, version["id"], policy)
    copies = [r for r in rows if r.get("role") == "copy"]
    if len(copies) > 1:
        _fail("current_copy_ambiguous")
    if not copies:
        _fail("current_platform_specific_copy_missing")
    content = copies[0].get("content")
    if not isinstance(content, dict):
        _fail("current_copy_missing")
    if copies[0].get("checksum") != canonical_sha(content):
        _fail("current_copy_hash_mismatch")
    if content != _formatted_copy(job, platform):
        _fail("current_copy_not_native_scoped_formatter")
    provenance = copies[0].get("provenance") or {}
    if (provenance.get("producer_step") != "format_for_platform"
            or provenance.get("draft_source_sha256") != current_draft_source_sha256(job, version["id"])):
        _fail("current_copy_draft_source_mismatch")
    if copies[0].get("path"):
        publication_copy = _pin({"path": copies[0]["path"], "sha256": copies[0]["checksum"]}, "current_publication_copy")
        if _object(publication_copy, "current_publication_copy") != content:
            _fail("current_publication_copy_file_mismatch")
    else:
        # Only a genuine current Store copy row can use a content-addressed representation.
        publication_copy = _text_pin(data_dir, job["id"], platform, "publication_copy",
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    title, body = _current_copy_components(content, job)
    parts = {"publication_copy": [publication_copy],
        "title": [_text_pin(data_dir, job["id"], platform, "title", title)]}
    if isinstance(body, str) and body.strip():
        parts["body"] = [_text_pin(data_dir, job["id"], platform, "body", body)]
    for row in rows:
        role = row.get("role")
        if role in {"copy", "manifest"}:
            continue
        part = ROLES.get(role)
        if not part:
            _fail("unmapped_current_artifact_role:" + str(role))
        pin = _pin({"path": row.get("path"), "sha256": row.get("checksum")}, "artifact_" + part)
        if any(p["path"] == pin["path"] for p in parts.get(part, [])):
            _fail("duplicate_current_artifact")
        parts.setdefault(part, []).append(pin)
    return revision, version["id"], parts


def _current_copy_components(content, job):
    """格式器短帖交付完整text；稿件组件仍只来自已核当前Store，整份copy另绑原SHA。"""
    title, body = content.get('title'), content.get('body')
    if content.get('kind') == 'short' and isinstance(content.get('text'), str) and content['text'].strip():
        if title is None:
            title = job.get('title')
        if body is None:
            body = job.get('body')
    if content.get('kind') == 'article' and body is None:
        # Article formatters deliver the body as markdown (Juejin/Zhihu) or html (WeChat), never as "body".
        markdown = content.get('markdown')
        body = markdown if isinstance(markdown, str) and markdown.strip() else job.get('body')
    return title, body


def _compile_applicability(form, parts, rules, entry, source_sha):
    if form not in VIDEO_FORMS | ARTICLE_FORMS | IMAGE_FORMS | TEXT_FORMS | PIECE_FORMS:
        _fail("unknown_current_content_form")
    required = {channel: [] for channel in CHANNELS}
    check_parts = {}
    def add(channel, name, bound):
        bound = sorted(set(bound) & set(parts))
        if not bound:
            _fail("check_actual_parts_missing:" + name)
        required[channel].append(name)
        check_parts[name] = sorted(set(check_parts.get(name, [])) | set(bound))
    all_parts = list(parts)
    add("auto", "artifact_integrity", all_parts)
    add("auto", "current_source_and_strategy", all_parts)
    add("auto", "content_blueprint", all_parts)
    add("auto", "platform_policy", all_parts)
    add("auto", "seven_day_all_channel_dedup", all_parts)
    text = set(parts) & {"title", "body", "publication_copy", "source_script", "source_text", "subtitles", "article_render"}
    add("auto", "content_facts_risk_humanization", text)
    for gate in entry.get("quality_gates") or []:
        if not isinstance(gate, str) or not gate.strip():
            _fail("current_channel_quality_rule_invalid")
        add("auto", "channel_rule:" + gate, all_parts)
    visual = set(parts) & VISUAL_PARTS
    if visual:
        for name in ("real_scene_background", "scene_semantic_match", "layout_diversity", "mobile_readability"):
            add("vlm", name, visual | text)
        if "covers" in parts:
            add("vlm", "cover_content_match", {"covers"} | text)
        role = (rules.get("global_hard_gates") or {}).get("ai_knowledge_cat_dog_role_policy") or {}
        if role.get("enforced") and ("ai" in str(entry.get("lane") or "").casefold() or form == "cat_knowledge_video"):
            add("vlm", "functional_cat_dog_roles", visual | text)
    actual_rights = set(parts) & {"rights", "images", "covers", "backgrounds", "article_cards", "narration", "bgm", "voice_segments", "video"}
    if actual_rights:
        if "rights" not in parts:
            _fail("actual_source_rights_missing")
        add("auto", "source_rights", actual_rights)
    if form in VIDEO_FORMS:
        for part in ("video", "narration", "subtitles", "backgrounds", "covers", "source_script"):
            if part not in parts:
                _fail("actual_video_" + part + "_missing")
        add("auto", "duration", {"video", "narration", "source_script"})
        add("auto", "audio_subtitle_sync", AUDIO_PARTS)
        add("watch", "complete_playback", AUDIO_PARTS | VISUAL_PARTS)
        add("watch", "silent_readability", visual | {"subtitles"})
    if "narration" in parts:
        for name in ("voice_intelligibility", "voice_naturalness", "voice_controls_and_pronunciation"):
            bound = {"narration", "voice_segments", "source_script", "source_text", "body"}
            if name == "voice_controls_and_pronunciation":
                bound.add("render_manifest")
            add("watch", name, bound)
        add("auto", "complete_voice_segments", {"narration", "voice_segments", "source_script", "source_text", "body"})
    if "subtitles" in parts:
        if "narration" not in parts:
            _fail("actual_subtitle_narration_missing")
        add("auto", "audio_subtitle_sync", AUDIO_PARTS)
        add("watch", "audio_subtitle_sync", AUDIO_PARTS)
    if "bgm" in parts:
        add("watch", "bgm_mix_audibility", {"bgm", "narration", "video"})
        add("auto", "bgm_loudness_and_rights", {"bgm", "rights", "narration", "video"})
    if form in ARTICLE_FORMS and "body" not in parts:
        _fail("actual_article_body_missing")
    if form in IMAGE_FORMS and not set(parts) & {"images", "article_cards"}:
        _fail("actual_image_content_missing")
    expected = {"image": "images", "cover": "covers", "article_card": "article_cards",
        "knowledge_card": "article_cards", "voiceover": "narration", "tts": "narration",
        "subtitle": "subtitles", "subtitles": "subtitles", "bgm": "bgm", "body": "body"}
    if form in expected and expected[form] not in parts:
        _fail("actual_piece_" + expected[form] + "_missing")
    if form in {"rewrite", "translation"}:
        if "source_text" not in parts or "body" not in parts:
            _fail("actual_rewrite_translation_source_missing")
        add("auto", "semantic_fidelity_and_certainty", {"source_text", "body", "title"})
        add("auto", "target_language_and_full_text", {"source_text", "body", "title"})
    na = {}
    for channel in CHANNELS:
        required[channel] = sorted(set(required[channel]))
        if not required[channel]:
            na[channel] = {"reason": "当前真实形态与全部产物不含此通道的媒体对象",
                "rule_id": "applicability:" + form + ":" + channel,
                "source_sha256": source_sha}
    return required, check_parts, na


def prepare_current_quality_context(store, data_dir, job_id, platform, *, current_policy):
    """只准备当前来源；返回值没有审核 passed 或执行资格。"""
    platform = str(platform).casefold().strip()
    job = store.get_job(job_id)
    if job.get("id") != job_id or platform not in job.get("platforms", []):
        _fail("current_job_platform_owner_missing")
    pins, rules, contract, entry, skill_sources = _source_policy(current_policy, platform, job)
    brief = job.get("brief") or {}
    dm = job.get("draft_meta") or {}
    form = brief.get("content_form") or dm.get("content_form")
    if brief.get("content_form") and dm.get("content_form") and brief["content_form"] != dm["content_form"]:
        _fail("current_content_form_conflict")
    # The generator's image_text alias is the channel's declared image-text post.
    # Preserve raw Store inputs and all IMAGE_FORMS/visual/rights applicability.
    if form == "image_text" and "image_text_post" in (entry.get("primary_types") or []):
        form = "image_text_post"
    lane = brief.get("account_lane") or brief.get("lane")
    account = brief.get("account_id") or brief.get("account_handle")
    account_context = brief.get("account_context") or (brief.get("workflow_context") or {}).get("account_context") or {}
    if isinstance(account_context, dict):
        account = account or account_context.get("account_id") or account_context.get("account_handle")
        lane = lane or account_context.get("account_lane") or account_context.get("lane")
    if not isinstance(lane, str) or lane != entry.get("lane"):
        _fail("current_account_lane_missing_or_mismatch")
    if not isinstance(account, str) or not account.strip():
        _fail("current_account_id_missing")
    _native_revision, draft_version, parts = _current_parts(store, data_dir, job, platform, current_policy)
    parts = {key: sorted(value, key=lambda row: row["path"]) for key, value in sorted(parts.items())}
    # 原 native content_revision 包含 quality；若纳入待生成报告会形成循环。
    # 原 ID 已用于上面的归属一致性检查，此处明确另算当前内容指纹，绝不写回DB。
    revision = "content-" + canonical_sha({"version": "current_store_content_fingerprint_v1",
        "job_id": job_id, "platform": platform, "draft_version_id": draft_version,
        "account_id": account, "lane": lane, "content_type": form, "parts": parts})
    required, check_parts, na = _compile_applicability(form, parts, rules, entry, pins["rulebook"]["sha256"])
    names = set(contract.get("required_skills") or [])
    names.update({"meta/content-preflight", "content/content-strategy-workflow"})
    if set(parts) & VISUAL_PARTS:
        names.update({"content/visual-quality-standards", "cover-film-poster"})
    if form in VIDEO_FORMS | IMAGE_FORMS or "article_cards" in parts:
        names.add("content/knowledge-card-designer")
    skills = {name: _pin(skill_sources.get(name), "current_skill_" + name) for name in sorted(names)}
    # native recompile 是读取资格，不能冒完成全部策略或媒体审核。
    compiled_sha = _compile_strategy(pins["strategy"], platform)
    programs = current_policy.get("program_sources") or {}
    if not isinstance(programs, dict) or not set(programs) <= set(required["auto"]):
        _fail("current_program_source_scope_invalid")
    programs = {name: _pin(pin, "current_program_" + name) for name, pin in programs.items()}
    return {"version": VERSION, "job_id": job_id, "platform": platform, "account_id": account,
        "lane": lane, "content_type": form, "revision_id": str(revision), "draft_version_id": draft_version,
        "phase": "release", **pins, "strategy_compiled_sha256": compiled_sha,
        "skills": skills, "parts": {k: sorted(v, key=lambda row: row["path"]) for k, v in sorted(parts.items())},
        "required_checks": required, "check_parts": check_parts, "not_applicable": na,
        "program_sources": programs}


def _current_object(path, label):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise QualityContextBlocked(label + "_missing") from exc
    return _object(_pin({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}, label), label)


def _native_task_home(task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
        _fail("native_actual_task_identity_missing")
    ready_paths = [p / "jobs" / task_id / name
        for p in NATIVE_TASK_ROOTS
        for name in ("current-model-ready.private.json", "media-authority-ready.private.json")
        if (p / "jobs" / task_id / name).is_file()]
    if len(ready_paths) != 1:
        _fail("native_actual_task_receipt_missing_or_ambiguous")
    ready_path = ready_paths[0]
    ready = _current_object(ready_path, "native_ready")
    home = Path(ready.get("home") or "")
    if (ready.get("job_id") != task_id or home.parent != NATIVE_HOME_ROOT
            or not re.fullmatch(r"media-" + task_id, home.name)):
        _fail("native_actual_task_home_mismatch")
    binding_path = home / "old-runtime-authority.private.json"
    if ready_path.name == "media-authority-ready.private.json":
        proof = ready.get("proof") or {}
        if (ready.get("schema") != "media-original-authority-ready-v1"
                or ready.get("native_model_calls_before_ready") != 0
                or ready.get("store_business_calls_before_ready") != 0
                or proof.get("home") != str(home)
                or proof.get("authority_receipt_path") != str(binding_path)
                or proof.get("official_cli_config_and_startup_route_used") is not True
                or proof.get("official_sdk_global_fallback_none") is not True
                or proof.get("refresh_grant_present") is not False
                or proof.get("canonical_auth_reads") != 0 or proof.get("network_attempts") != 0):
            _fail("native_media_ready_sdk_proof_invalid")
        binding = _object(_pin({"path": str(binding_path),
            "sha256": proof.get("authority_receipt_sha256")}, "native_media_authority"), "native_media_authority")
        if (binding.get("source_snapshot_sha256") != ready.get("snapshot_sha256")
                or binding.get("provenance") != proof.get("provenance")
                or binding.get("access_sha256") != proof.get("actual_access_sha256")):
            _fail("native_media_ready_authority_binding_mismatch")
        # The SDK canonical provider (e.g. custom) is already bound by the exact
        # proof.provenance == authority.provenance comparison above. The CLI/config
        # request identity (e.g. custom:workbuddy2api) remains a separate binding.
        ready_route = {"provider": binding.get("requested_provider"),
            "model": (proof.get("provenance") or {}).get("model")}
    else:
        binding = _current_object(binding_path, "native_authority")
        ready_route = ready.get("current_route")
    if (binding.get("task_id") != task_id or binding.get("profile_id") != task_id
            or binding.get("home") != str(home) or binding.get("refresh_grant_present") is not False):
        _fail("native_actual_authority_identity_mismatch")
    cfg = _pin({"path": str(home / "config.yaml"), "sha256": binding.get("profile_config_sha256")}, "native_profile_config")
    model = (_read_native_policy_yaml(cfg, task_id) or {}).get("model") or {}
    provenance = binding.get("provenance") or {}
    route = {"provider": binding.get("requested_provider"), "model": provenance.get("model"),
        "api_mode": provenance.get("api_mode"), "endpoint": provenance.get("endpoint")}
    if (ready_route != {k: route[k] for k in ("provider", "model")}
            or model.get("provider") != route["provider"] or model.get("default") != route["model"]
            or model.get("api_mode") != route["api_mode"] or model.get("base_url") != route["endpoint"]):
        _fail("native_current_route_profile_mismatch")
    return home, route, provenance


def _same_native_text(raw, actual):
    if not isinstance(actual, str):
        return False
    try:
        return json.loads(raw) == json.loads(actual)
    except (ValueError, TypeError):
        return raw.rstrip("\n") == actual.rstrip("\n")


def _native_call(db, session_id, observation):
    if not isinstance(observation, dict):
        _fail("native_media_observation_missing")
    query_id, result_id = observation.get("query_message_id"), observation.get("result_message_id")
    if type(query_id) is not int or type(result_id) is not int:
        _fail("native_media_message_identity_missing")
    query = db.execute("SELECT tool_calls FROM messages WHERE id=? AND session_id=? AND role='assistant'", (query_id, session_id)).fetchone()
    result = db.execute("SELECT tool_call_id,tool_name,content FROM messages WHERE id=? AND session_id=? AND role='tool'", (result_id, session_id)).fetchone()
    if not query or not result:
        _fail("native_tool_database_messages_missing")
    try:
        calls = json.loads(query[0] or "[]")
        matches = [c for c in calls if isinstance(c,dict) and c.get("id") == result[0]]
        if len(matches) != 1:
            _fail("native_tool_outer_call_ambiguous")
        call = matches[0]
        function = call["function"]
        args = json.loads(function.get("arguments") or "{}")
        name = function.get('name')
        if name == 'tool_call':
            inner = args.get('calls') if isinstance(args,dict) else None
            if not isinstance(inner,list) or len(inner)!=1 or not isinstance(inner[0],dict):
                _fail('native_tool_wrapper_inner_call_ambiguous')
            name = inner[0].get('name')
            args = inner[0].get('arguments')
        if not isinstance(args,dict):
            _fail('native_tool_database_arguments_invalid')
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        raise QualityContextBlocked("native_tool_database_call_invalid") from exc
    if (observation.get("tool_call_id") != result[0] or observation.get("tool_name") != result[1]
            or name != result[1]):
        _fail("native_tool_call_identity_mismatch")
    return args, result[2]


def _native_input_audio(db, session_id, inputs):
    """Only actual persisted input_audio payload bytes count; ASR text does not."""
    def payloads(value):
        if isinstance(value, list):
            for item in value:
                yield from payloads(item)
        elif isinstance(value, dict):
            if value.get("type") == "input_audio":
                audio = value.get("input_audio") or value
                if isinstance(audio, dict) and isinstance(audio.get("data"), str):
                    yield audio["data"]
            for child in value.values():
                if isinstance(child, (list, dict)):
                    yield from payloads(child)
    digests = {}
    for path, pin in inputs.items():
        checked = _pin(pin, "native_current_audio")
        digests.setdefault(checked["sha256"], set()).add(path)
    observed = set()
    for content, api in db.execute("SELECT content,api_content FROM messages WHERE session_id=? AND role='user'", (session_id,)):
        try:
            value = json.loads(api or content or "null")
            for data in payloads(value):
                observed.update(digests.get(hashlib.sha256(base64.b64decode(data, validate=True)).hexdigest(), set()))
        except (ValueError, TypeError):
            continue
    return observed


def _verify_native_session(native, session, context, subset, raw_pin, *, channel=None, check_name=None, skill_id=None):
    """Verify real task/DB messages, not a reviewer-authored session JSON."""
    task_id = native.get("task_job_id")
    if session.get("task_job_id") != task_id:
        _fail("native_session_task_owner_mismatch")
    home, route, provenance = _native_task_home(task_id)
    if session.get("route") != route:
        _fail("native_session_actual_route_mismatch")
    database = home / "state.db"
    if not database.is_file() or database.is_symlink():
        _fail("native_actual_session_database_missing")
    raw = Path(raw_pin["path"]).read_text(encoding="utf-8-sig")
    sid = session.get("session_id")
    capabilities = {"text"}
    try:
        db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT source,model,billing_provider,api_call_count,ended_at FROM sessions WHERE id=?", (sid,)).fetchone()
        if (not row or row[0] != "oneshot" or row[1] != route["model"]
                or row[2] != provenance.get("provider") or not row[3] or row[4] is None):
            _fail("native_actual_session_execution_mismatch")
        prompts = [r[0] or "" for r in db.execute("SELECT content FROM messages WHERE session_id=? AND role='user'", (sid,))]
        if not any(canonical_sha(context) in p for p in prompts):
            _fail("native_actual_query_context_missing")
        observations = session.get("native_observations") or []
        if native.get("kind") == "program":
            if channel in {"vlm", "watch"} or check_name in SEMANTIC_AUTO_CHECKS or skill_id:
                _fail("program_cannot_replace_semantic_review")
            if not isinstance(native.get("argv"), list) or not all(isinstance(a, str) and a for a in native["argv"]):
                _fail("native_program_argv_missing")
            source = _pin(native.get("program_source"), "native_program_source")
            if source != context["program_sources"].get(check_name) or source["path"] not in native["argv"]:
                _fail("native_program_not_current_rule_executor")
            if not isinstance(observations, list) or len(observations) != 1:
                _fail("native_program_observation_missing")
            args, actual = _native_call(db, sid, observations[0])
            if observations[0].get("tool_name") != "terminal" or shlex.split(args.get("command") or "") != native["argv"]:
                _fail("native_program_actual_argv_mismatch")
            result = json.loads(actual)
            if result.get("exit_code") != 0 or result.get("error") or not _same_native_text(raw, result.get("output")):
                _fail("native_program_actual_output_mismatch")
        else:
            protocol = session.get('submission_protocol')
            if protocol is not None:
                from .quality_review_submission import PROTOCOL, load_scope, read_session_submission, strict_loads,verify_current_vision_route_selections
                if protocol != PROTOCOL:_fail('native_typed_submission_protocol_unknown')
                scope_pin = _pin(session.get('submission_scope_ref'), 'native_typed_submission_scope')
                scope, unused = load_scope(scope_pin['path'], scope_pin['sha256'])
                if scope.get('task_job_id') != task_id:_fail('native_typed_submission_task_mismatch')
                if scope.get('current_role_route') != {key:route.get(key)for key in('provider','model','api_mode','endpoint')}:
                    _fail('native_typed_submission_current_role_route_mismatch')
                verify_current_vision_route_selections(session.get('vision_route_selection_refs'),scope_pin,context,route,
                    provenance['provider'],home,require_real=scope['channel']=='vlm'or(scope['channel']=='watch'and'silent_readability'in context['required_checks'].get('watch',[])))
                if channel is not None and scope.get('channel') != channel:_fail('native_typed_submission_channel_mismatch')
                cursor = db.execute('SELECT * FROM sessions WHERE id=?', (sid,))
                actual_session = dict(zip([x[0] for x in cursor.description], cursor.fetchone()))
                cursor = db.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id', (sid,))
                columns = [x[0] for x in cursor.description]
                actual_messages = [dict(zip(columns, row)) for row in cursor.fetchall()]
                submitted = read_session_submission(actual_messages, actual_session, context, scope['channel'], scope_pin)
                if (submitted['observation'] != session.get('submission_observation')
                        or session.get('result_message_id') != submitted['observation']['result_message_id']
                        or strict_loads(raw) != submitted['review']):
                    _fail('native_typed_submission_actual_values_changed')
                for key, original in (('submission_arguments_ref', submitted['raw_arguments']),
                                      ('submission_receipt_ref', submitted['raw_receipt'])):
                    pin = _pin(session.get(key), 'native_' + key)
                    if Path(pin['path']).read_text(encoding='utf-8') != original:
                        _fail('native_typed_submission_original_bytes_changed')
                finals = [m for m in actual_messages if m['role']=='assistant' and not m.get('tool_calls') and str(m.get('content')or'').strip()]
                final = finals[-1] if finals else None
                final_pin = _pin(session.get('native_final_raw_result'), 'native_typed_uninterpreted_final')
                if (session.get('native_final_message_id') != (final['id'] if final else None)
                        or Path(final_pin['path']).read_text(encoding='utf-8') != (str(final['content']) if final else '')):
                    _fail('native_typed_submission_natural_final_changed')
            else:
                result_id = session.get("result_message_id")
                result = db.execute("SELECT content FROM messages WHERE id=? AND session_id=? AND role='assistant'", (result_id, sid)).fetchone()
                if not result or not _same_native_text(raw, result[0]):
                    _fail("native_actual_raw_result_mismatch")
            if channel in {"vlm", "watch"}:
                allowed = {"vision_analyze", "video_analyze"} if channel == "vlm" or check_name == "silent_readability" else {"audio_analyze"}
                if not isinstance(observations, list):
                    _fail("native_actual_media_observation_missing")
                inputs = {p["path"]: p for pins in subset.values() for p in pins}
                applicable = VISUAL_PARTS if channel == "vlm" or check_name == "silent_readability" else ({"narration", "voice_segments", "bgm", "video"} if check_name=="complete_playback" else {"narration", "voice_segments", "bgm"})
                media_inputs = {p["path"]: p for part, pins in subset.items() if part in applicable for p in pins}
                observed = (_native_input_audio(db, sid, media_inputs)
                    if channel == "watch" and check_name != "silent_readability" else set())
                for observation in observations:
                    args, actual = _native_call(db, sid, observation)
                    if observation.get("tool_name") not in allowed:
                        _fail("native_observed_media_capability_missing")
                    source = args.get("image_url") or args.get("video_url") or args.get("audio_url") or args.get("audio_path")
                    if source not in inputs:
                        _fail("native_media_source_not_current_part")
                    if observation.get('tool_name')=='audio_analyze' and (
                            args.get('audio_sha256')!=inputs[source]['sha256']
                            or args.get('context_sha256')!=canonical_sha(context)):
                        _fail('native_audio_actual_input_context_or_sha_mismatch')
                    _pin(inputs[source], "native_actual_media_source")
                    tool_result = json.loads(actual)
                    if tool_result.get("success") is not True or not str(tool_result.get("analysis") or "").strip():
                        _fail("native_actual_media_analysis_missing")
                    if observation.get('tool_name')=='audio_analyze' and (tool_result.get('auxiliary_execution')or{}).get('evidence_mode')in{'scoped_blind_full_WAV_v1','scoped_blind_full_audio_v2'}:
                        from .current_audio_review_runtime import verify_scoped_blind_audio
                        verify_scoped_blind_audio(tool_result,context,args,session['task_job_id'],session.get('submission_scope_ref'))
                    observed.add(source)
                media = {p["path"] for part, pins in subset.items() if part in applicable for p in pins}
                if not media or not media <= observed:
                    _fail("native_current_media_parts_not_all_observed")
                capabilities.add("vision" if channel == "vlm" or check_name == "silent_readability" else "audio")
        verdict = json.loads(raw)
        if not isinstance(verdict, dict) or verdict.get("context_sha256") != canonical_sha(context):
            _fail("native_raw_verdict_context_missing")
        rows = verdict.get("skill_executions") if skill_id else verdict.get("checks")
        key, identity = ("skill_id", skill_id) if skill_id else ("name", check_name)
        if not isinstance(rows, list):
            _fail("native_raw_review_rows_missing")
        matches = [r for r in rows if isinstance(r, dict) and r.get(key) == identity]
        if len(matches) != 1 or matches[0].get("passed") is not True or matches[0].get("verdict") != "passed":
            _fail("native_raw_review_verdict_not_passed")
        if not isinstance(matches[0].get("observations"), (str, list, dict)) or not matches[0]["observations"]:
            _fail("native_raw_review_observations_missing")
        if skill_id and matches[0].get("skill_sha256") != context["skills"][skill_id]["sha256"]:
            _fail("native_raw_skill_source_mismatch")
        if skill_id:
            applied = matches[0].get("applied_checks")
            required = set().union(*map(set, context["required_checks"].values()))
            if not isinstance(applied, list) or not applied or not set(applied) <= required:
                _fail("native_raw_skill_application_missing")
        return {"session_id": sid, "task_job_id": task_id, "route": route,
            "observed_capabilities": sorted(capabilities), "raw_result_sha256": raw_pin["sha256"]}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, QualityContextBlocked):
            raise
        raise QualityContextBlocked("native_actual_session_evidence_unreadable") from exc
    finally:
        if "db" in locals():
            db.close()


# Audio/visual consumers share this DB verification boundary, not a self-reported runtime dictionary.
verify_native_quality_session = _verify_native_session


def _execution(pin, label, context, subset, *, channel=None, check_name=None, skill_id=None):
    checked = _pin(pin, label)
    record = _object(checked, label)
    if (record.get("context_sha256") != canonical_sha(context) or record.get("parts") != subset
            or record.get("status") != "completed" or record.get("passed") is not True
            or record.get("verdict") != "passed" or record.get("failures") != []
            or not record.get("execution_id") or not record.get("producer")):
        _fail(label + "_execution_incomplete_or_other_context")
    source_context = {key: context[key] for key in ("version", "job_id", "platform", "account_id",
        "lane", "content_type", "revision_id", "draft_version_id", "phase", "rulebook", "directive",
        "run_contract", "strategy", "strategy_compiled_sha256", "skills", "program_sources")}
    if record.get("source_context") != source_context:
        _fail(label + "_execution_source_phase_mismatch")
    raw_pin = _pin(record.get("raw_result"), label + "_raw_result")
    if channel and (record.get("channel") != channel or record.get("check_name") != check_name):
        _fail(label + "_execution_check_mismatch")
    if skill_id and (record.get("skill_id") != skill_id
            or record.get("skill_sha256") != context["skills"][skill_id]["sha256"]):
        _fail(label + "_execution_skill_mismatch")
    # 正常 runner 必须保原始执行回执。纯 schema flags 不足。
    native_pin = _pin(record.get("native_receipt"), label + "_native_receipt")
    native = _object(native_pin, label + "_native_receipt")
    if (native.get("execution_id") != record["execution_id"] or native.get("status") != "completed"
            or native.get("context_sha256") != record["context_sha256"]
            or native.get("source_context") != source_context or native.get("parts") != subset
            or native.get("raw_result") != raw_pin or native.get("exit_code") != 0):
        _fail(label + "_native_receipt_binding_mismatch")
    kind = native.get("kind")
    if kind == "hermes":
        session_pin = _pin(native.get("session_receipt"), label + "_session_receipt")
        session = _object(session_pin, label + "_session_receipt")
        if (not session.get("session_id") or session.get("execution_id") != record["execution_id"]
                or session.get("raw_result") != raw_pin or session.get("context_sha256") != record["context_sha256"]
                or session.get("source_context") != source_context or session.get("parts") != subset
                or session.get("status") != "completed" or not session.get("route")):
            _fail(label + "_native_session_binding_mismatch")
    elif kind == "program":
        session_pin = _pin(native.get("session_receipt"), label + "_session_receipt")
        session = _object(session_pin, label + "_session_receipt")
        if not native.get("argv") or channel in {"vlm", "watch"}:
            _fail(label + "_program_cannot_replace_semantic_review")
    else:
        _fail(label + "_native_execution_kind_missing")
    _verify_native_session(native, session, context, subset, raw_pin,
        channel=channel, check_name=check_name, skill_id=skill_id)
    return checked


verify_native_quality_execution = _execution


def build_current_expected_context(store, data_dir, job_id, platform, *, current_policy, execution_records):
    """正常 runner 完成后复读；缺执行原件/语义/音频能力均阻断。"""
    context = prepare_current_quality_context(store, data_dir, job_id, platform, current_policy=current_policy)
    if not isinstance(execution_records, dict) or set(execution_records) != {"skills", "checks"}:
        _fail("normal_execution_records_missing")
    skills = execution_records["skills"]
    checks = execution_records["checks"]
    if not isinstance(skills, dict) or set(skills) != set(context["skills"]):
        _fail("normal_skill_executions_missing")
    if not isinstance(checks, dict) or set(checks) != set(CHANNELS):
        _fail("normal_check_executions_missing")
    skill_pins = {name: _execution(pin, "skill_" + name, context, context["parts"], skill_id=name)
                  for name, pin in skills.items()}
    check_pins = {}
    for channel in CHANNELS:
        if not isinstance(checks[channel], dict) or set(checks[channel]) != set(context["required_checks"][channel]):
            _fail(channel + "_normal_check_executions_missing")
        check_pins[channel] = {}
        for name, pin in checks[channel].items():
            subset = {part: context["parts"][part] for part in context["check_parts"][name]}
            check_pins[channel][name] = _execution(pin, channel + "_" + name, context, subset,
                channel=channel, check_name=name)
    return dict(context, skill_executions=skill_pins, check_executions=check_pins)
