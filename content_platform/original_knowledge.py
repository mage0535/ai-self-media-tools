"""同任务原创事实依据；官方文档不成为商业复用素材，签章不是第三方版权许可。"""
import csv
from collections import Counter
import difflib
import hashlib
import io
import json
import os
import re
import stat
import time
import base64
import hmac
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
import uuid
from pathlib import Path

from .review import ReviewTokens

MODE = "original_knowledge"
EVENT = "native_original_knowledge_inputs_bound"
REVISION_EXECUTION_EVENT = 'native_original_revision_generated'
OFFICIAL_URLS = {
    "https://docs.python.org/3.12/library/csv.html",
    "https://docs.python.org/3.12/library/decimal.html",
}
ORDER_URLS={"https://docs.python.org/3.12/library/csv.html","https://docs.python.org/3.12/library/collections.html"}
PROTECTED_JOBS = {"7b12e9aae980484b", "f8bb617683914cbe"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _bytes(path, pin=None, *, private=False):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("original_file_path_untrusted")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 4 * 1024 * 1024:
        raise ValueError("original_file_type_or_size_invalid")
    if private and os.name != "nt" and (before.st_uid != 0 or stat.S_IMODE(before.st_mode) != 0o600):
        raise ValueError("original_root_private_file_required")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(4 * 1024 * 1024 + 1)
        after_fd = os.fstat(stream.fileno())
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if (identity(before) != identity(opened) or identity(opened) != identity(after_fd)
            or identity(after_fd) != identity(after) or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("original_file_changed_during_read")
    if pin is not None and hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError("original_file_sha_untrusted")
    return raw


def _write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("original_output_symlink_forbidden")
    if path.exists():
        if _bytes(path) != raw:
            raise ValueError("original_immutable_file_conflict")
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def _text(raw):
    parser = _Text(); parser.feed(raw.decode("utf-8"))
    return " ".join(parser.parts)


def _lease(store, job):
    current = store.get_job(job["id"])
    if (job["id"] in PROTECTED_JOBS or not re.fullmatch("[0-9a-f]{16}", job["id"])
            or current.get("state") != "generating" or not current.get("lease_owner")
            or current.get("lease_owner") != job.get("lease_owner")
            or datetime.fromisoformat(current["lease_expires_at"]) <= datetime.now(timezone.utc)):
        raise ValueError("original_same_job_active_lease_required")
    return current


def _failed_before_content_without_output(store, row):
    """Only actual failed source attempts with no content or business effects are non-works."""
    if row.get('state') not in {'blocked','failed'} or not row.get('id'):
        return False
    actual=store.get_job(row['id'])
    if (actual.get('state') not in {'blocked','failed'} or actual.get('lease_owner')
            or actual.get('title') or actual.get('body') or actual.get('draft_meta')):
        return False
    steps=store.workflow_steps(row['id'])
    source=[r for r in steps if r.get('step_name')=='collect_native_source_inputs']
    if len(source)!=1 or source[0].get('status') not in {'BLOCKED','FAILED_FINAL'}:
        return False
    if any(r.get('step_name') not in {'initialize_task','load_platform_workflow_context',
            'validate_content_policy_inputs','collect_native_source_inputs'} for r in steps):
        return False
    with store.connect() as conn:
        for table in ('draft_versions','artifacts','deliveries','platform_outputs','topic_history'):
            if conn.execute('SELECT 1 FROM '+table+' WHERE job_id=? LIMIT 1',(row['id'],)).fetchone():
                return False
    events=store.events(row['id'])
    if any(r.get('event') in {EVENT,'native_original_revision_generated','draft_saved',
            'native_mandatory_quality_attempt','native_mandatory_quality_result'} for r in events):
        return False
    generated=store.path.parent/'jobs'/row['id']/'video-preflight'/'native-script-v2'
    # A completed native generation remains a real candidate, even before the draft is saved.
    if any(generated.glob('*.actual-model-result.json')):
        return False
    return True


def _dedupe(store, job, script):
    from .trends import normalize_topic
    from .content_hygiene import audit_topic
    family = verified_revision_family(store, job) if (job.get('brief') or {}).get('quality_revision') else set()
    if family:
        from .history_reader import read_history
        with read_history(store.path, ('topic_history',)) as (db, prefix):
            cutoff_iso = (datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='seconds')
            used = {r[0] for r in db.execute(prefix + 'SELECT fingerprint,job_id FROM read_topic_history WHERE datetime(used_at)>=datetime(?)', (cutoff_iso,)) if r[1] not in family}
    else:
        used = store.used_topics(lookback_days=7)
    if normalize_topic(job["topic"]) in used:
        raise ValueError("original_recent_topic_duplicate")
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = []
    candidates=store.content_candidates(limit=10000, states=("review_required","approved","published","partial","created","generating","blocked","failed"), exclude_job_id=job["id"])
    if len(candidates)>=10000:
        raise ValueError("original_7day_history_capacity_incomplete")
    for row in candidates:
        if row.get('id') in family:
            continue
        if family and _failed_before_content_without_output(store,row):
            continue
        when = datetime.fromisoformat(row.get("updated_at") or row["created_at"])
        if when.tzinfo is None or when < cutoff:
            continue
        recent.append(row)
        previous = str((row.get("draft_meta") or {}).get("video_script") or row.get("body") or "")
        if previous and difflib.SequenceMatcher(None, script, previous).ratio() >= 0.8:
            raise ValueError("original_recent_copy_duplicate")
    report = audit_topic(job["topic"], recent)
    if report["status"] != "pass":
        raise ValueError("original_recent_topic_or_copy_overlap")
    result = {"lookback_days": 7, "scope": "all_channels", "history_sha256": digest(recent),
              "candidate_count": len(recent), "topic_report": report}
    if family:
        result['verified_revision_ancestor_ids'] = sorted(family)
    return result


def is_original_editorial(job):
    brief = job.get("brief") or {}
    return brief.get("selection_mode") == "editorial_calendar" and bool(brief.get("original_knowledge_intent"))


def collect_original_inputs(store, config, job):
    """只读取Root封存实物；不HTTP、不执行调用者的脚本或命令。"""
    started = time.monotonic()
    _lease(store, job)
    if getattr(os, "geteuid", lambda: -1)() != 0 or not is_original_editorial(job):
        raise ValueError("original_root_editorial_scope_required")
    if (job.get('brief') or {}).get('quality_revision'):
        return collect_revision_original_inputs(store, config, job)
    settings = config.get("workflow_sources") or {}
    recipe_pin = settings.get("original_knowledge_recipe_sha256")
    raw = _bytes(settings.get("original_knowledge_recipe") or "", recipe_pin, private=True)
    recipe = json.loads(raw)
    token = _bytes(settings.get("original_knowledge_source_token_path") or "", private=True).decode().strip()
    # The signing key already belongs to this Store; this action cannot approve or publish.
    key = store.path.parent / "review.key"
    _bytes(key, private=True)
    seal = ReviewTokens(key).verify(token, MODE)
    brief = job["brief"]; editorial = brief.get("editorial_evidence") or {}
    if (not recipe_pin or seal.get("job_id") != job["id"] or seal.get("continuation_sha256") != recipe_pin
            or not seal.get("nonce") or recipe.get("version") != "original_knowledge_recipe_v1"
            or recipe.get("job_id") != job["id"] or recipe.get("topic") != job["topic"]
            or recipe.get("platform") != "kuaishou" or job["platforms"] != ["kuaishou"]
            or recipe.get("intent") != brief.get("original_knowledge_intent")
            or recipe.get("editorial_evidence") != editorial or recipe.get("script_origin") != "self_written"):
        raise ValueError("original_signed_recipe_scope_mismatch")
    if (not all(str(editorial.get(k) or "").strip() for k in ("strategy_source", "calendar_column", "planned_for"))
            or editorial.get("dedupe_passed") is not True):
        raise ValueError("original_editorial_evidence_incomplete")
    budget = recipe.get("execution_budget_seconds")
    source_budget = recipe.get("source_budget_seconds")
    if (type(budget) is not int or not 0 < budget <= 1800 or type(source_budget) is not int
            or not 0 < source_budget <= min(120, budget) or not 0 < seal["exp"] - time.time() <= budget):
        raise ValueError("original_scope_budget_invalid")
    beats = recipe.get("beats") or []
    script = "\n\n".join(beats)
    if len(beats) != 8 or any(not isinstance(b, str) or not 8 <= len(b) <= 40 for b in beats) or not 280 <= len(script) <= 420:
        raise ValueError("original_eight_beat_script_invalid")
    dedup = _dedupe(store, job, script)
    manifest_path = Path(recipe.get("factual_sources_manifest") or "")
    manifest_raw = _bytes(manifest_path, recipe.get("factual_sources_manifest_sha256"), private=True)
    manifest = json.loads(manifest_raw)
    root = store.path.parent / "jobs" / job["id"] / "video-preflight" / "original-sources"
    documents = []; texts = {}
    expected = {row["id"]: row["url"] for row in recipe.get("documents") or []}
    demo_kind=recipe.get('demo_kind','arithmetic')
    allowed=ORDER_URLS if demo_kind=='orders_id_check' else OFFICIAL_URLS
    if demo_kind not in {'arithmetic','orders_id_check'} or set(expected.values()) != allowed or len(expected) != 2:
        raise ValueError("original_two_official_primary_documents_required")
    for row in manifest.get("documents") or []:
        identity = row.get("id"); url = row.get("url")
        if (expected.get(identity) != url or url not in allowed or row.get("resolved_url") != url
                or row.get("status_code") != 200 or row.get("source_type") != "official_documentation"
                or row.get("usage") != "factual_reference_only" or row.get("commercial_asset_reuse") is not False):
            raise ValueError("original_document_is_not_fact_only_primary")
        observed = datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 86400:
            raise ValueError("original_factual_snapshot_stale")
        source_name = row["response_file"]
        if Path(source_name).name != source_name:
            raise ValueError("original_source_filename_invalid")
        body = _bytes(manifest_path.parent / source_name, row["response_sha256"])
        if len(body) != row.get("bytes"):
            raise ValueError("original_document_size_changed")
        ref = _write(root / source_name, body); texts[identity] = _text(body)
        documents.append({"id": identity, "url": url, "usage": "factual_reference", "commercial_asset_reuse": False,
                          "retrieved_at": row["retrieved_at"], "response": ref})
    if set(texts) != set(expected):
        raise ValueError("original_official_documents_incomplete")
    demonstration = manifest.get("demonstration") or {}
    if (demonstration.get("source_type") != "self_created" or demonstration.get("example_data") is not True
            or demonstration.get("source_platform_material") is not False or demonstration.get("business_data") is not False
            or demonstration.get("exit_code") != 0):
        raise ValueError("original_self_created_execution_required")
    files = {}; contents = {}
    for name in ("demo.csv", "verify_demo.py", "demo.stdout.json"):
        row = (demonstration.get("files") or {}).get(name) or {}
        body = _bytes(manifest_path.parent / name, row.get("sha256"))
        if not row.get("sha256") or len(body) != row.get("bytes"):
            raise ValueError("original_demo_file_or_execution_sha_missing")
        files[name] = _write(root / name, body); contents[name] = body
    rows = list(csv.DictReader(io.StringIO(contents["demo.csv"].decode("utf-8"))))
    result = json.loads(contents["demo.stdout.json"])
    if demo_kind=='orders_id_check':
        identifiers=[str(row['order_id']) for row in rows]
        baseline=demonstration.get('expected_order_ids')
        if not isinstance(baseline,list) or len(baseline)!=4 or len(set(baseline))!=4:
            raise ValueError('original_orders_baseline_invalid')
        counts=Counter(identifiers)
        missing=sorted(set(baseline)-set(identifiers));duplicates=sorted(k for k,v in counts.items() if v>1)
        if (not 3<=len(rows)<=4 or result.get('rows')!=len(rows) or result.get('missing_ids')!=missing
                or result.get('duplicate_ids')!=duplicates or result.get('purpose')!='self_created_order_id_demonstration'):
            raise ValueError('original_orders_execution_result_mismatch')
    else:
        computed = sum((Decimal(r["quantity"]) * Decimal(r["unit_price"]) for r in rows), Decimal("0"))
        if (len(rows) != 3 or result.get("rows") != 3 or Decimal(result["verified_total"]) != computed
                or Decimal(result["example_wrong_total"]) == computed or result.get("wrong_total_rejected") is not True
                or result.get("purpose") != "self_created_arithmetic_demonstration"):
            raise ValueError("original_demo_execution_result_mismatch")
    texts["demo"] = contents["demo.stdout.json"].decode()
    citations = recipe.get("beat_sources") or []
    if len(citations) != 8 or {row.get("beat_id") for row in citations} != {f"s{i:02}" for i in range(1, 9)}:
        raise ValueError("original_all_beats_require_fact_citations")
    for row in citations:
        quote = row.get("quote")
        if not isinstance(quote, str) or not 1 <= len(quote) <= 160 or quote not in texts.get(row.get("source_id"), ""):
            raise ValueError("original_fact_quote_not_observed")
    if time.monotonic() - started > source_budget:
        raise ValueError("original_source_scope_budget_exceeded")
    payload = {"version": "original_knowledge_inputs_v1", "content_mode": MODE, "job_id": job["id"],
               "topic": job["topic"], "platform": "kuaishou", "intent": recipe["intent"],
               "recipe_sha256": recipe_pin, "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
               "editorial_evidence": editorial, "script_origin": "self_written", "beats": beats,
               "beat_sources": citations, "documents": documents,
               "demo": {"kind":demo_kind,"source_type": "self_created", "example_data": True, "files": files, "result": result},
               "topic_dedup_report": dedup, "authority": {"actor_uid": 0, "action": MODE, "nonce": seal["nonce"],
                   "expires_at": seal["exp"], "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                   "execution_budget_seconds": budget, "source_budget_seconds": source_budget}}
    record = _write(root.parent / "original_knowledge_inputs.json", encoded(payload))
    ref = {"job_id": job["id"], "path": record["path"], "sha256": record["sha256"],
           "producer": "native.original_knowledge", "store_path": str(store.path.resolve())}
    store.record_event(job["id"], EVENT, ref)
    return ref


def read_original_inputs(store, job_id, ref):
    from .video_preflight_inputs import read_bound_file
    if not isinstance(ref, dict) or ref.get("store_path") != str(store.path.resolve()):
        raise ValueError("original_store_reference_required")
    supplement = ref.get("producer") == "native.original_qualified_supplement"
    payload = read_bound_file(store, job_id, ref,
        "native_original_qualified_supplement_bound" if supplement else EVENT, "kuaishou")
    if supplement:
        recipe_ref = payload.get("supplement") or {}
        raw = _bytes(recipe_ref.get("recipe_path") or "", recipe_ref.get("recipe_sha256"), private=True)
        recipe = json.loads(raw)
        token = _bytes(recipe_ref.get("token_path") or "", private=True).decode().strip()
        key = store.path.parent / "review.key"; _bytes(key, private=True)
        seal = ReviewTokens(key).verify(token, MODE)
        current = store.get_job(job_id)
        operation=recipe.get("operation")
        expected_budget={"first_uneffected_render_recovery":1200,"two_changed_pixels_quality_repair":600,"first_uneffected_render_only":900,"derived_order_id_render_after_visual_rejection":900}.get(operation)
        if (seal.get("job_id") != job_id or seal.get("continuation_sha256") != hashlib.sha256(raw).hexdigest()
                or not seal.get("nonce") or recipe.get("version") != "original_render_recovery_v1"
                or recipe.get("job_id") != job_id or expected_budget is None
                or recipe.get("no_publish_no_approval") is not True or recipe.get("original_job_failed_preserved") is not True
                or current.get("state") != "failed" or current.get("lease_owner")
                or recipe.get("parent_job_sha256") != digest(current)
                or recipe.get("parent_workflow_sha256") != digest(store.workflow_steps(job_id))
                or not 0 < recipe.get("absolute_deadline_unix", 0) - time.time() <= expected_budget
                or recipe.get("budget_seconds") != expected_budget or recipe.get("render_max_seconds") != (0 if operation=="two_changed_pixels_quality_repair" else 900)):
            raise ValueError("original_supplement_scope_or_parent_changed")
        parent_ref = recipe.get("parent_original_knowledge_ref")
        parent = read_bound_file(store, job_id, parent_ref, EVENT, "kuaishou")
        compare = dict(payload); compare.pop("supplement", None); compare["authority"] = parent["authority"]
        if compare != parent:
            raise ValueError("original_supplement_fact_payload_changed")
        if payload["authority"] != {"actor_uid": 0, "action": MODE, "nonce": seal["nonce"],
                "expires_at": seal["exp"], "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "execution_budget_seconds": expected_budget, "source_budget_seconds": min(300, expected_budget)}:
            raise ValueError("original_supplement_authority_changed")
        for member in recipe.get("prior_artifacts") or []:
            _bytes(member["path"], member["sha256"])
        if len(recipe.get("prior_artifacts") or []) < 4:
            raise ValueError("original_supplement_prior_receipts_required")
    authority = payload.get("authority") or {}
    if payload.get('version') == 'original_knowledge_inputs_v2':
        parent, reference, facts, context = revision_source_context(store, store.get_job(job_id))
        if (payload.get('quality_revision') != reference or payload.get('parent_facts_sha256') != digest(facts)
                or payload.get('generation_context') != context or payload.get('script_origin') != 'native_generated'):
            raise ValueError('original_revision_current_source_changed')
        generated = verify_revision_generation(payload.get('generation_session'), context)
        validate_revision_script(generated,digest(context),facts['texts'])
        if (payload.get('beats') != generated['beats'] or payload.get('beat_sources') != generated['beat_sources']
                or payload.get('voice_plan') != generated['voice_plan']):
            raise ValueError('original_revision_generated_script_changed')
        token_ref=payload.get('current_scope_token')or{}
        token=_bytes(token_ref.get('path')or'',token_ref.get('sha256'),private=True).decode()
        seal=verify_historical_original_token(store,token)
        if (seal.get('job_id')!=job_id or seal.get('continuation_sha256')!=payload.get('recipe_sha256')
                or seal.get('nonce')!=authority.get('nonce') or seal.get('exp')!=authority.get('expires_at')
                or hashlib.sha256(token.encode()).hexdigest()!=authority.get('token_sha256')):
            raise ValueError('original_revision_current_scope_token_changed')
        verify_original_revision_history(store,job_id,ref,payload)
    if (store.get_job(job_id).get('brief') or {}).get('media_revision'):
        from .media_revision import resume_original_authority
        authority = resume_original_authority(store, job_id, ref, authority)
    if (payload.get("content_mode") != MODE or job_id in PROTECTED_JOBS
            or authority.get("actor_uid") != 0 or authority.get("action") != MODE
            or not authority.get("nonce") or (payload.get('version')!='original_knowledge_inputs_v2'
                and not 0 < authority.get("expires_at", 0) - time.time() <= 1800)):
        raise ValueError("original_actor_scope_expired_or_invalid")
    for row in payload["documents"]:
        if row.get("usage") != "factual_reference" or row.get("commercial_asset_reuse") is not False:
            raise ValueError("original_document_commercial_reuse_forbidden")
        _bytes(row["response"]["path"], row["response"]["sha256"])
    for row in payload["demo"]["files"].values():
        _bytes(row["path"], row["sha256"])
    return payload


def original_from_plan(plan):
    from .store import Store
    ref = plan.get("original_knowledge_ref")
    canonical = os.environ.get("NATIVE_VIDEO_STORE_PATH")
    if (not canonical or not isinstance(ref, dict) or ref.get("store_path") != str(Path(canonical).resolve())
            or ref.get("job_id") != plan.get("job_id") or plan.get("platforms") != ["kuaishou"]
            or any(plan.get(k) for k in ("allow_degraded_render", "allow_degraded_hot_intelligence", "degraded_source"))
            or plan.get("hot_viral_samples")):
        raise ValueError("original_native_store_scope_required")
    return read_original_inputs(Store(canonical), plan["job_id"], ref)


def validate_original_asset_inputs(payload):
    """原创教程没有旧视频/封面/输入图的复用入口。"""
    for data in (payload,payload.get("brief") or {},payload.get("draft_meta") or {}):
        if any(data.get(k) for k in ("source_video_path","source_video_url","image_reference","input_image")):
            raise ValueError("original_external_media_reuse_forbidden")
        if data.get("selected_pipeline")=="localized_repost_video":
            raise ValueError("original_repost_pipeline_forbidden")


def validate_original_copy(store,job,text):
    ref=(job.get("brief") or {}).get("original_knowledge_ref")
    read_original_inputs(store,job["id"],ref)
    return _dedupe(store,job,text)


def original_intelligence(plan):
    proof = original_from_plan(plan)
    return {"status": "original_fact_ready", "native_ready": False, "native_verified": False,
            "commercial_reuse": False, "topic": proof["topic"], "source_ref": plan["original_knowledge_ref"],
            "claims_forbidden": ["platform native ranking", "viral guarantee", "real customer AI error"]}


def historical_revision_facts(store, job_id, ref):
    """核原Store事实事件和原件；旧authority仅作历史记录，绝不授权新执行。"""
    from .video_preflight_inputs import read_bound_file
    if not isinstance(ref,dict) or ref.get('store_path') != str(store.path.resolve()):
        raise ValueError('revision_actual_fact_store_required')
    proof = read_bound_file(store,job_id,ref,EVENT,'kuaishou')
    if proof.get('content_mode') != MODE or proof.get('demo',{}).get('source_type') != 'self_created' or proof['demo'].get('example_data') is not True:
        raise ValueError('revision_original_fact_kind_invalid')
    texts = {}; documents = proof.get('documents') or []
    allowed = ORDER_URLS if proof['demo'].get('kind') == 'orders_id_check' else OFFICIAL_URLS
    if len(documents)!=2 or {r.get('url') for r in documents} != allowed:
        raise ValueError('revision_original_official_facts_incomplete')
    for row in documents:
        if row.get('usage') != 'factual_reference' or row.get('commercial_asset_reuse') is not False:
            raise ValueError('revision_fact_commercial_asset_forbidden')
        texts[row['id']] = _text(_bytes(row['response']['path'],row['response']['sha256']))
    files = proof['demo'].get('files') or {}
    if set(files) != {'demo.csv','verify_demo.py','demo.stdout.json'}:
        raise ValueError('revision_original_demo_files_incomplete')
    contents = {name:_bytes(pin['path'],pin['sha256']) for name,pin in files.items()}
    rows = list(csv.DictReader(io.StringIO(contents['demo.csv'].decode())))
    result = json.loads(contents['demo.stdout.json'])
    if result != proof['demo'].get('result') or result.get('rows') != len(rows):
        raise ValueError('revision_original_demo_result_changed')
    if proof['demo'].get('kind') == 'orders_id_check':
        counts = Counter(str(r['order_id']) for r in rows)
        if (result.get('purpose') != 'self_created_order_id_demonstration'
                or result.get('duplicate_ids') != sorted(k for k,v in counts.items() if v>1)):
            raise ValueError('revision_original_order_facts_changed')
    else:
        computed=sum((Decimal(r['quantity'])*Decimal(r['unit_price']) for r in rows),Decimal('0'))
        if Decimal(result['verified_total'])!=computed or Decimal(result['example_wrong_total'])==computed or result.get('wrong_total_rejected') is not True:
            raise ValueError('revision_original_arithmetic_facts_changed')
    texts['demo']=contents['demo.stdout.json'].decode()
    return {'documents':documents,'demo':proof['demo'],'texts':texts}


def revision_source_context(store, job):
    from .quality_revision import verified_quality_revision
    parent,reference=verified_quality_revision(store,job)
    ref=reference.get('parent_original_knowledge_ref')
    if ref != (parent.get('brief') or {}).get('original_knowledge_ref'):
        raise ValueError('revision_parent_original_source_changed')
    facts=historical_revision_facts(store,parent['id'],ref)
    if digest(facts)!=reference.get('parent_facts_sha256'):
        raise ValueError('revision_parent_facts_pin_changed')
    context={'version':'original_quality_revision_generation_v2','job_id':job['id'],
        'topic':job['topic'],'platforms':job['platforms'],'quality_revision':reference,
        'parent_facts_sha256':digest(facts),'script_origin':'native_generated',
        'certainty':'self_created_demonstration_only','source_texts_sha256':digest(facts['texts'])}
    return parent,reference,facts,context


def validate_revision_script(value, context_sha, texts):
    if (not isinstance(value,dict) or set(value) != {'context_sha256','beats','beat_sources','certainty','voice_plan'}
            or value.get('context_sha256')!=context_sha or value.get('certainty')!='self_created_demonstration_only'):
        raise ValueError('revision_native_script_context_or_certainty_invalid')
    beats=value.get('beats'); citations=value.get('beat_sources')
    if (not isinstance(beats,list) or len(beats)!=8
            or any(not isinstance(b,str) or not 2<=len(b.strip())<=40 for b in beats)
            or len('\n\n'.join(beats))>320):
        raise ValueError('revision_native_eight_beat_script_invalid')
    if (not isinstance(citations,list) or len(citations)!=8
            or [r.get('beat_id') for r in citations] != [f's{i:02}' for i in range(1,9)]):
        raise ValueError('revision_native_every_beat_fact_source_required')
    for row in citations:
        quote=row.get('quote')
        if not isinstance(quote,str) or not 1<=len(quote)<=160 or quote not in texts.get(row.get('source_id'),''):
            raise ValueError('revision_native_fact_quote_not_observed')
    plan=value.get('voice_plan')
    if not isinstance(plan,list) or len(plan)!=len(beats):raise ValueError('revision_native_voice_plan_required')
    for index,row in enumerate(plan):
        if (not isinstance(row,dict) or set(row)!={'index','text','style','semantic_direction','rate','pitch','pause_after_ms'}
                or type(row.get('index'))is not int or row['index']!=index or row.get('text')!=beats[index]
                or not isinstance(row.get('style'),str) or not row['style'].strip()
                or not isinstance(row.get('semantic_direction'),str) or not row['semantic_direction'].strip()
                or not re.fullmatch(r'[+-]\d+%',str(row.get('rate')or''))
                or not re.fullmatch(r'[+-]\d+Hz',str(row.get('pitch')or''))
                or type(row.get('pause_after_ms'))is not int or not 0<=row['pause_after_ms']<=5000):
            raise ValueError('revision_native_semantic_voice_plan_invalid')
    return value


def verify_revision_generation(session, context):
    import sqlite3
    from .mandatory_quality_context import _native_task_home
    if not isinstance(session,dict):raise ValueError('revision_native_generation_session_required')
    home,route,provenance=_native_task_home(session.get('task_job_id'))
    if session.get('route')!=route:raise ValueError('revision_native_generation_route_changed')
    raw=_bytes(session['raw_result']['path'],session['raw_result']['sha256']).decode()
    with sqlite3.connect((home/'state.db').resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        r=db.execute('SELECT source,model,billing_provider,api_call_count,ended_at FROM sessions WHERE id=?',(session.get('session_id'),)).fetchone()
        if not r or r[0]!='oneshot' or r[1]!=route['model'] or r[2]!=provenance.get('provider') or not r[3] or r[4] is None:
            raise ValueError('revision_native_generation_actual_session_missing')
        prompts=[r[0]or'' for r in db.execute("SELECT content FROM messages WHERE session_id=? AND role='user'",(session['session_id'],))]
        if not any(digest(context)in p for p in prompts):raise ValueError('revision_native_generation_query_context_missing')
        row=db.execute("SELECT content FROM messages WHERE session_id=? AND id=? AND role='assistant'",(session['session_id'],session.get('result_message_id'))).fetchone()
        if not row or json.loads(row[0])!=json.loads(raw):raise ValueError('revision_native_generation_actual_result_changed')
    return json.loads(raw)


def verify_historical_original_token(store,token):
    """只验原签章真实性；历史证据不恢复已过期签章的执行能力。"""
    body,signature=token.split('.',1)
    tokens=ReviewTokens(store.path.parent/'review.key')
    expected=base64.urlsafe_b64encode(hmac.new(tokens._key(),body.encode(),hashlib.sha256).digest()).rstrip(b'=').decode()
    if not hmac.compare_digest(signature,expected):raise ValueError('original_revision_historical_token_signature_invalid')
    value=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
    if value.get('action')!=MODE or not value.get('nonce'):raise ValueError('original_revision_historical_token_action_invalid')
    return value


def verify_native_execution_window(store,job_id,owner,lease_expiry,task_id,session_id):
    """生成与素材消费共享当初真实lease/SDK/API时间验证，不发模型调用。"""
    from .mandatory_quality_context import _native_task_home
    claims=[]
    for row in store.events(job_id):
        if row['event']!='job_claimed':continue
        claim=json.loads(row['detail_json'])
        if claim.get('owner')==owner and claim.get('expires_at')==lease_expiry:claims.append(row)
    if len(claims)!=1:raise ValueError('native_historical_actual_lease_missing_or_ambiguous')
    home,route,provenance=_native_task_home(task_id)
    authority=json.loads((home/'old-runtime-authority.private.json').read_bytes())
    with sqlite3.connect((home/'state.db').resolve().as_uri()+'?mode=ro',uri=True,timeout=2)as db:
        db.execute('PRAGMA query_only=ON')
        row=db.execute('SELECT source,model,billing_provider,api_call_count,started_at,ended_at FROM sessions WHERE id=?',(session_id,)).fetchone()
    if (not row or row[0]!='oneshot' or row[1]!=route['model']or row[2]!=provenance.get('provider')
            or not row[3]or row[5]is None):raise ValueError('native_historical_actual_session_missing')
    lower=datetime.fromisoformat(claims[0]['created_at'].replace('Z','+00:00')).timestamp()
    upper=datetime.fromisoformat(lease_expiry.replace('Z','+00:00')).timestamp()
    expiry=authority.get('expires_at_unix')
    if (not lower<=float(row[4])<=float(row[5])<=upper
            or not isinstance(expiry,(int,float))or float(row[5])>expiry):
        raise ValueError('native_historical_execution_outside_authorized_window')
    return home,route,{'started_at':row[4],'ended_at':row[5],'authority_expires_at':expiry}


def verify_original_revision_history(store,job_id,ref,payload):
    current=store.get_job(job_id)
    actual_ref=(current.get('brief')or{}).get('original_knowledge_ref')
    if actual_ref is not None and actual_ref!=ref:raise ValueError('original_revision_history_current_ref_changed')
    records=[json.loads(row['detail_json'])for row in store.events(job_id)if row['event']==REVISION_EXECUTION_EVENT]
    matches=[r for r in records if r.get('original_knowledge_ref')==ref]
    if len(matches)!=1:raise ValueError('original_revision_history_actual_execution_event_required')
    record=matches[0];session=payload['generation_session']
    if (record.get('generation_session')!=session or record.get('generation_context_sha256')!=digest(payload['generation_context'])
            or record.get('scope_token_sha256')!=payload['authority']['token_sha256']):
        raise ValueError('original_revision_history_execution_changed')
    verify_native_execution_window(store,job_id,record['lease_owner'],record['lease_expires_at'],session['task_job_id'],session['session_id'])
    _bytes(record['generation_query']['path'],record['generation_query']['sha256'])
    if record['generation_query']!=session.get('query'):raise ValueError('original_revision_history_actual_query_changed')
    return record


def verified_revision_family(store, job):
    """仅当前正式修订的已核祖先；不排除兄弟稿、普通follow_up或其它同题。"""
    parent,reference,facts,context=revision_source_context(store,job)
    family=set();current=parent
    while True:
        if current['id'] in family:raise ValueError('revision_ancestor_chain_cycle')
        family.add(current['id'])
        brief=current.get('brief')or{}
        if brief.get('quality_revision'):
            from .quality_revision import verified_quality_revision
            current,_=verified_quality_revision(store,current)
        elif brief.get('media_revision'):
            ref=brief['media_revision'];manifest=json.loads(_bytes(ref['manifest_path'],ref['manifest_sha256'],private=True))
            events=[json.loads(r['detail_json'])for r in store.events(current['id'])if r['event']=='media_revision_created']
            if len(events)!=1 or events[0]!=ref:raise ValueError('revision_ancestor_actual_event_required')
            ancestor=store.get_job(ref['parent_job_id'])
            if (manifest.get('parent_job_id')!=ancestor['id'] or manifest.get('parent_job_sha256')!=digest(ancestor)
                    or manifest.get('parent_workflow_sha256')!=digest(store.workflow_steps(ancestor['id']))):
                raise ValueError('revision_ancestor_original_snapshot_changed')
            current=ancestor
        else:break
        if len(family)>32:raise ValueError('revision_ancestor_chain_too_large')
        old=historical_revision_facts(store,current['id'],(current.get('brief')or{}).get('original_knowledge_ref'))
        fingerprint=lambda f:({r['id']:r['response']['sha256']for r in f['documents']}, {k:v['sha256']for k,v in f['demo']['files'].items()},f['demo']['result'])
        if fingerprint(old)!=fingerprint(facts):raise ValueError('revision_ancestor_fact_family_changed')
    return family


def collect_revision_original_inputs(store, config, job, *, _checkpoint=None):
    from .native_quality_runner import current_active_role,native_session_review,write_original
    _lease(store,job)
    parent,reference,facts,context=revision_source_context(store,job)
    if job['platforms']!=['kuaishou']:raise ValueError('revision_original_platform_invalid')
    root=store.path.parent/'jobs'/job['id']/'video-preflight'
    attempt=root/('native-script-v2' if _checkpoint is None else 'native-checkpoint-'+uuid.uuid4().hex);attempt.mkdir(parents=True,exist_ok=False,mode=0o700)
    home,task,route=current_active_role(600)
    prompt=('你是本轮正常原创修订生成者。下面事实仅为公开自制演示，不是客户案例。按当前纠正目标重新写8段自然中文口播，'
        '目标180–210字、语气轻松直接；事实和人工核对边界保留，避免术语堆砌。最终真实配音须自然且<=60秒，不能靠加速。'
        '每段s01至s08给一个实际来源文本中的逐字quote及source_id，不得编造事实、授权、审核通过。'
        '同时实际按每句含义产voice_plan八条，index0..7、text严格对应beats原文、style及semantic_direction解释本句语气，'
        'rate使用正负整数百分比如+0%、pitch使用正负整数Hz如+0Hz、pause_after_ms整数0..5000。'
        'Edge仅支持这些控制，不产SSML或自由instructions；不要按index套固定模板，也不能靠压快满足时长。'
        '禁止发布、读auth/env/cookie、改数据库、模型或配置。仅回复JSON无围栏：'
        '{"context_sha256":"当前SHA","beats":["8段"],"beat_sources":[{"beat_id":"s01","source_id":"实际id","quote":"原文"}],'
        '"voice_plan":[{"index":0,"text":"原段","style":"本句语气","semantic_direction":"实际语义","rate":"+0%","pitch":"+0Hz","pause_after_ms":300}],'
        '"certainty":"self_created_demonstration_only"}.\n'
        +json.dumps({'context_sha256':digest(context),'context':context,'facts':facts,'revision_intent':reference['intent']},ensure_ascii=False))
    if _checkpoint is None:
        result=native_session_review(home,task,route,attempt,{'context':context},'generation',600,
            prompt_override=prompt,result_validator=lambda value:validate_revision_script(value,digest(context),facts['texts']))
        session={k:result[k]for k in ('task_job_id','session_id','route','raw_result','query','result_message_id')}
        generation_lease={'owner':job['lease_owner'],'expires_at':job['lease_expires_at']}
    else:
        session=_checkpoint['generation_session']
        generation_lease=_checkpoint['generation_lease']
    generated=verify_revision_generation(session,context)
    validate_revision_script(generated,digest(context),facts['texts'])
    _lease(store,job);dedup=_dedupe(store,job,'\n\n'.join(generated['beats']))
    bound_documents=[];bound_files={}
    for row in facts['documents']:
        bound=dict(row);bound['response']=_write(root/'original-sources'/Path(row['response']['path']).name,_bytes(row['response']['path'],row['response']['sha256']));bound_documents.append(bound)
    for name,pin in facts['demo']['files'].items():bound_files[name]=_write(root/'original-sources'/name,_bytes(pin['path'],pin['sha256']))
    recipe_pin=digest({'context':context,'generation_session':session})
    tokens=ReviewTokens(store.path.parent/'review.key');token=tokens.issue(job['id'],MODE,ttl=1800,continuation_sha256=recipe_pin);seal=tokens.verify(token,MODE)
    token_pin=write_original(attempt/'current-original-scope.token',token.encode())
    payload={'version':'original_knowledge_inputs_v2','content_mode':MODE,'job_id':job['id'],'topic':job['topic'],'platform':'kuaishou',
        'intent':job['brief']['original_knowledge_intent'],'recipe_sha256':recipe_pin,'manifest_sha256':digest(facts),
        'quality_revision':reference,'parent_facts_sha256':digest(facts),'generation_context':context,'generation_session':session,
        'editorial_evidence':job['brief'].get('editorial_evidence')or{},'script_origin':'native_generated',
        'beats':generated['beats'],'beat_sources':generated['beat_sources'],'voice_plan':generated['voice_plan'],'documents':bound_documents,
        'current_scope_token':token_pin,
        'demo':dict(facts['demo'],files=bound_files),'topic_dedup_report':dedup,
        'quality_inherited':False,'factual_snapshot_refreshed':False,
        'authority':{'actor_uid':0,'action':MODE,'nonce':seal['nonce'],'expires_at':seal['exp'],
            'token_sha256':token_pin['sha256'],'execution_budget_seconds':1800,'source_budget_seconds':120}}
    record=_write(root/'original_knowledge_inputs.json',encoded(payload))
    ref={'job_id':job['id'],'path':record['path'],'sha256':record['sha256'],'producer':'native.original_knowledge','store_path':str(store.path.resolve())}
    store.record_event(job['id'],EVENT,ref)
    store.record_event(job['id'],REVISION_EXECUTION_EVENT,{'job_id':job['id'],'original_knowledge_ref':ref,
        'lease_owner':generation_lease['owner'],'lease_expires_at':generation_lease['expires_at'],
        'checkpoint_consumption':None if _checkpoint is None else {'current_task_id':task,'current_lease_owner':job['lease_owner'],
            'current_lease_expires_at':job['lease_expires_at'],'source_checkpoint':_checkpoint['checkpoint_ref'],
            'original_generated_at':_checkpoint['original_generation_window']['ended_at'],
            'original_generation_api_call_count':_checkpoint['original_generation_window']['api_call_count'],
            'consumed_at':datetime.now(timezone.utc).isoformat(),'current_scope_generation_model_calls':0},
        'generation_session':session,'generation_query':session['query'],
        'generation_context_sha256':digest(context),'scope_token_sha256':token_pin['sha256']})
    if _checkpoint is not None:
        store.record_event(job['id'],'native_original_generation_checkpoint_consumed',{
            'source_checkpoint':_checkpoint['checkpoint_ref'],'original_generation_session':session,
            'current_task_id':task,'current_lease_owner':job['lease_owner'],
            'current_lease_expires_at':job['lease_expires_at'],'original_knowledge_ref':ref,
            'new_model_calls':0,'historical_generation_replayed':False})
    return ref


def read_revision_source_checkpoint(store,job,checkpoint_ref):
    """Read Root's sealed index and re-verify original native DB evidence; no execution grant."""
    if not isinstance(checkpoint_ref,dict) or set(checkpoint_ref)!={'path','sha256'}:
        raise ValueError('original_checkpoint_ref_required')
    raw=_bytes(checkpoint_ref['path'],checkpoint_ref['sha256'],private=True)
    pin=Path(checkpoint_ref['path'])
    if pin.parent!=store.path.parent/'quality_runtime':raise ValueError('original_checkpoint_canonical_root_required')
    value=json.loads(raw)
    parent,reference,facts,context=revision_source_context(store,job)
    if (value.get('version')!='original_generation_checkpoint_v1' or value.get('job_id')!=job['id']
            or value.get('store_path')!=str(store.path.resolve())
            or value.get('quality_revision_request_sha256')!=reference['request_sha256']
            or value.get('context_sha256')!=digest(context)):
        raise ValueError('original_checkpoint_current_source_mismatch')
    session=value.get('generation_session')or{};lease=value.get('generation_lease')or{}
    root=store.path.parent/'jobs'/job['id']/'video-preflight'/'native-script-v2'
    for key,name in (('raw_result','generation.actual-model-result.json'),('query','generation.query.txt')):
        actual=session.get(key)or{}
        if actual.get('path')!=str(root/name):raise ValueError('original_checkpoint_source_path_mismatch')
        _bytes(actual['path'],actual.get('sha256'))
    home,route,window=verify_native_execution_window(store,job['id'],lease.get('owner'),lease.get('expires_at'),
        session.get('task_job_id'),session.get('session_id'))
    generated=verify_revision_generation(session,context)
    validate_revision_script(generated,digest(context),facts['texts'])
    query=_bytes(session['query']['path'],session['query']['sha256']).decode()
    with sqlite3.connect((home/'state.db').resolve().as_uri()+'?mode=ro',uri=True)as db:
        prompts=[r[0]or''for r in db.execute("SELECT content FROM messages WHERE session_id=? AND role='user'",(session['session_id'],))]
        api_calls=db.execute('SELECT api_call_count FROM sessions WHERE id=?',(session['session_id'],)).fetchone()[0]
    if not any(p.rstrip('\n')==query.rstrip('\n')for p in prompts):raise ValueError('original_checkpoint_actual_query_mismatch')
    try:material=json.loads(query.split('\n',1)[1])
    except (ValueError,IndexError)as e:raise ValueError('original_checkpoint_actual_query_material_missing')from e
    if material.get('context')!=context or material.get('facts')!=facts or material.get('revision_intent')!=reference['intent']:
        raise ValueError('original_checkpoint_actual_material_changed')
    return dict(value,checkpoint_ref=dict(checkpoint_ref),original_generation_window=dict(window,api_call_count=api_calls))


def consume_revision_source_checkpoint(store,config,job,checkpoint_ref):
    """Current normal lease binds already executed source raw, then runs current dedup; zero new model calls."""
    _lease(store,job)
    verified=read_revision_source_checkpoint(store,job,checkpoint_ref)
    return collect_revision_original_inputs(store,config,job,_checkpoint=verified)
