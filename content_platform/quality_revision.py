"""按当前规则从真实父任务创建重新生成的质量修订；不继承质量结论。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_request(path, expected_sha):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("quality_revision_request_path_invalid")
    info = path.stat()
    if getattr(os, "geteuid", lambda: -1)() != 0 or info.st_uid != 0 or info.st_mode & 0o077:
        raise PermissionError("quality_revision_root_private_request_required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("quality_revision_request_changed")
    value = json.loads(raw)
    if (value.get("version") != "quality_revision_request_v1"
            or value.get("no_publish_no_approval") is not True
            or not isinstance(value.get("intent"), str) or not value["intent"].strip()
            or not isinstance(value.get("changed_parts"), list) or not value["changed_parts"]):
        raise ValueError("quality_revision_request_invalid")
    if not set(value["changed_parts"]) <= {"title", "body", "cover", "images", "backgrounds",
                                         "video", "narration", "subtitles", "bgm"}:
        raise ValueError("quality_revision_part_unknown")
    if 'user_visual_materials_source' in value:
        verified_user_visual_source(value['user_visual_materials_source'])
    revision_editorial_input(value)
    return value


def verified_user_visual_source(ref):
    """输入实物的正常校验；不接受既有审核、分数、Source质量保证。"""
    if not isinstance(ref,dict) or set(ref)!={'path','sha256'}:
        raise ValueError('quality_revision_user_visual_ref_invalid')
    if not isinstance(ref['sha256'],str) or len(ref['sha256'])!=64 or any(c not in '0123456789abcdef'for c in ref['sha256']):
        raise ValueError('quality_revision_user_visual_sha_invalid')
    path=Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink()for p in path.parents):
        raise ValueError('quality_revision_user_visual_path_invalid')
    info=path.stat()
    if (getattr(os,'geteuid',lambda:-1)()!=0 or info.st_uid!=0
            or info.st_mode&0o077 or not stat.S_ISREG(info.st_mode)
            or info.st_size>4*1024*1024):
        raise PermissionError('quality_revision_user_visual_root_private_required')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('quality_revision_user_visual_manifest_changed')
    value=json.loads(raw)
    if (not isinstance(value,dict) or value.get('version')!='user_visual_materials_inputs_v1'
            or value.get('purpose')!='orders_id_check_visual_inputs'):
        raise ValueError('quality_revision_user_visual_manifest_invalid')
    forbidden={'passed','score','semantic_match_score','semantic_review','quality_evidence','final_quality_evidence','execution_evidence','production_verified'}
    def inspect(node):
        if isinstance(node,dict):
            if forbidden&set(node):raise ValueError('quality_revision_user_visual_quality_claim_forbidden')
            for child in node.values():inspect(child)
        elif isinstance(node,list):
            for child in node:inspect(child)
    inspect(value)
    from .native_visual_inputs import read_user_visual_materials_inputs
    actual=read_user_visual_materials_inputs(ref)
    if actual!=value or path.read_bytes()!=raw:
        raise ValueError('quality_revision_user_visual_source_changed_during_read')
    return {'path':str(path),'sha256':ref['sha256']}



def revision_editorial_input(request):
    value = request.get("editorial_input") or {}
    allowed = {"audience", "language", "tone", "content_form",
               "production_intent", "content_mode", "original_method_source_ref"}
    if not isinstance(value, dict) or not set(value) <= allowed:
        raise ValueError("quality_revision_editorial_fields_invalid")
    for key in ("audience", "language", "tone", "content_form"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ValueError("quality_revision_editorial_value_invalid")
    intent = value.get("production_intent")
    if intent is not None:
        if not isinstance(intent, dict) or set(intent) != {"topic", "scenario_contract"}:
            raise ValueError("quality_revision_production_intent_invalid")
        if not isinstance(intent["topic"], str) or not intent["topic"].strip():
            raise ValueError("quality_revision_current_topic_required")
        scene = intent["scenario_contract"]
        fields = {"actor", "inputs", "process", "outcome", "boundaries", "human_handoff"}
        if (not isinstance(scene, dict) or set(scene) != fields
                or any(not isinstance(scene[key], str) or not scene[key].strip() for key in fields)):
            raise ValueError("quality_revision_real_scene_info_required")
    if "content_mode" in value and value["content_mode"] != "original_method":
        raise ValueError("quality_revision_content_mode_not_admitted")
    ref = value.get("original_method_source_ref")
    if "content_mode" in value or ref is not None:
        if value.get("content_mode") != "original_method" or intent is None or not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError("quality_revision_original_method_inputs_required")
        path = Path(ref["path"])
        if (not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
                or not isinstance(ref["sha256"], str) or len(ref["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in ref["sha256"])):
            raise ValueError("quality_revision_factual_source_ref_invalid")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise PermissionError("quality_revision_factual_source_root_private_required")
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
            raise ValueError("quality_revision_factual_source_changed")
        # The ordinary Source producer validates and reads the typed actual facts.
        # This reference does not claim semantic validity or inherit any QA result.
    for key in ("difference_angle", "recap_reason"):
        if key in request and (not isinstance(request[key], str) or not request[key].strip()):
            raise ValueError("quality_revision_reason_invalid")
    return copy.deepcopy(value)


def create_quality_revision(pipeline, parent_id, request_path, request_sha):
    """普通create API；父对象与原workflow不改，正常run从来源收集重新执行。"""
    request = read_request(request_path, request_sha)
    editorial = revision_editorial_input(request)
    parent = pipeline.store.get_job(parent_id)
    steps = pipeline.store.workflow_steps(parent_id)
    if (request.get("parent_job_id") != parent_id
            or request.get("parent_job_sha256") != digest(parent)
            or request.get("parent_workflow_sha256") != digest(steps)
            or parent.get("state") not in {"review_required", "rejected", "failed", "blocked"}
            or parent.get("lease_owner")):
        raise ValueError("quality_revision_parent_changed_or_active")
    with pipeline.store.connect() as conn:
        existing = conn.execute("SELECT id FROM jobs WHERE json_extract(brief_json,'$.quality_revision.request_sha256')=?",
                                (request_sha,)).fetchall()
    if existing:
        if len(existing) != 1:
            raise ValueError("quality_revision_ambiguous")
        return pipeline.store.get_job(existing[0][0])
    child_topic = (editorial.get("production_intent") or {}).get("topic") or parent["topic"]
    source = copy.deepcopy(parent.get("brief") or {})
    original_ref = copy.deepcopy(source.get("original_knowledge_ref"))
    # 每次正常来源收集和所有适用规则重新执行；过期权限、旧生成结果和通过结论不继承。
    for field in ("media_revision", "media_revision_request", "original_knowledge_ref",
                  "bounded_model_input", "_final_bounded_model_input", "source_collection_audit",
                  "platform_workflow_inputs", "workflow_context", "run_contract",
                  "content_blueprint", "video_asset_requirements", "source_status",
                  "video_script", "narration_script", "video_source_planning", "video_planning_audit",
                  "claim_ledger", "topic_dedup_report", "audio_plan", "quality_gate",
                  "final_quality_evidence", "generation_session", "humanized_copy",
                  "user_visual_materials_source", "topic_request_contract", "production_intent",
                  "scenario_contract", "topic_analysis", "content_mode", "original_method_source_ref",
                  "platform_source_matrix", "reference_posts", "original_factual_reference_posts",
                  "source", "sources", "evidence", "strategy_evidence", "strategy_evidence_gate",
                  "strategy_observation_ref", "content_blueprint_gate", "prompt_bundle_gate",
                  "same_lane_intelligence", "viral_breakdown", "viral_collection", "trend_candidate",
                  "topic_selection", "topic_decision", "factual_reference_posts",
                  "style_research_reference_posts", "original_method_observed_ref",
                  "original_method_factual_inputs", "factual_sources"):
        source.pop(field, None)
    reference = {"parent_job_id": parent_id, "request_path": str(Path(request_path).resolve()),
                 "request_sha256": request_sha, "intent": request["intent"],
                 "changed_parts": request["changed_parts"], "parent_quality_inherited": False,
                 "parent_job_sha256": digest(parent), "parent_workflow_sha256": digest(steps),
                 "production_topic": child_topic, "editorial_input_sha256": digest(editorial)}
    if original_ref:
        from .original_knowledge import historical_revision_facts
        facts = historical_revision_facts(pipeline.store, parent_id, original_ref)
        reference.update(parent_original_knowledge_ref=original_ref,
                         parent_facts_sha256=digest(facts))
    source.update(quality_revision=reference, source_collection_required=True,
                  follow_up_to=parent_id, difference_angle=request.get("difference_angle") or request["intent"],
                  recap_reason=request.get("recap_reason") or request["intent"],
                  publication_authorized=False, no_publish=True)
    if 'user_visual_materials_source' in request:
        source['user_visual_materials_source']=verified_user_visual_source(request['user_visual_materials_source'])
    source.update(editorial)
    from .topic_request_contract import manual_request_brief
    source = manual_request_brief(child_topic, source, producer="quality_revision.create")
    reference["topic_request_contract_sha256"] = digest(source["topic_request_contract"])
    fingerprint = parent.get("topic_fingerprint") or "" if child_topic == parent["topic"] else ""
    job = pipeline.create(child_topic, parent["platforms"], source, parent.get("profile") or "default",
                          fingerprint)
    pipeline.store.record_event(job["id"], "quality_revision_created", reference)
    return job


def verified_quality_revision(store, job):
    """仅从当前Store事件、root原请求及原父快照确认修订，不接受follow_up自述。"""
    reference = (job.get("brief") or {}).get("quality_revision")
    if not isinstance(reference, dict):
        raise ValueError("quality_revision_reference_required")
    request = read_request(reference.get("request_path") or "", reference.get("request_sha256"))
    if (job.get('brief') or {}).get('user_visual_materials_source')!=request.get('user_visual_materials_source'):
        raise ValueError('quality_revision_root_visual_source_changed')
    editorial = revision_editorial_input(request)
    parent_id = reference.get("parent_job_id")
    parent = store.get_job(parent_id)
    if (job.get("id") == parent_id or job.get("topic") != ((editorial.get("production_intent") or {}).get("topic") or parent.get("topic"))
            or job.get("platforms") != parent.get("platforms")
            or request.get("parent_job_id") != parent_id
            or reference.get("parent_job_sha256") != request.get("parent_job_sha256")
            or digest(parent) != request.get("parent_job_sha256")
            or reference.get("parent_workflow_sha256") != request.get("parent_workflow_sha256")
            or digest(store.workflow_steps(parent_id)) != request.get("parent_workflow_sha256")
            or parent.get("lease_owner") or parent.get("state") not in {"review_required","rejected","failed","blocked"}
            or reference.get("intent") != request.get("intent")
            or reference.get("changed_parts") != request.get("changed_parts")
            or reference.get("parent_quality_inherited") is not False):
        raise ValueError("quality_revision_verified_parent_changed")
    if "production_topic" in reference:
        if (reference["production_topic"] != job["topic"]
                or reference.get("editorial_input_sha256") != digest(editorial)
                or any((job.get("brief") or {}).get(key) != value for key, value in editorial.items())
                or reference.get("topic_request_contract_sha256") != digest((job.get("brief") or {}).get("topic_request_contract"))):
            raise ValueError("quality_revision_current_editorial_input_changed")
        from .topic_request_contract import resolve_request_contract
        contract = resolve_request_contract(job, store)
        if contract.get("producer") != "quality_revision.create":
            raise ValueError("quality_revision_actual_creation_provenance_required")
    elif any(key in editorial for key in ("production_intent", "content_mode", "original_method_source_ref")):
        raise ValueError("quality_revision_current_editorial_receipt_required")
    records = [json.loads(r["detail_json"]) for r in store.events(job["id"])
               if r["event"] == "quality_revision_created"]
    if len(records) != 1 or records[0] != reference:
        raise ValueError("quality_revision_actual_create_receipt_required")
    return parent, reference

def verified_revision_family(store, job):
    """Only actual Root-requested quality-revision creation can exempt ancestors."""
    family = set()
    seen = {job["id"]}
    current = job
    while isinstance((current.get("brief") or {}).get("quality_revision"), dict):
        parent, _ = verified_quality_revision(store, current)
        if parent["id"] in seen:
            raise ValueError("quality_revision_family_cycle")
        family.add(parent["id"])
        seen.add(parent["id"])
        current = parent
    return family
