import hashlib
import copy
import json
import os
import re
import time
import uuid
from pathlib import Path

from .compliance import ComplianceChecker
from .claim_ledger import sanitize_unsupported_claims, strip_numeric_claims, validate_claims
from .content_depth import validate_content_depth_plan
from .content_hygiene import audit_topic
from .content_policy import SHORT_VIDEO_PLATFORMS, generated_media_kinds_for_job
from .delivery_health import delivery_health_decision
from .formatters import format_for_platform
from .generator import DraftGenerator
from .humanize import naturalize_copy
from .intelligence import GLOBAL_EN_PLATFORMS, build_generation_context
from .media import MediaBridge
from .media_quality import (
    _real_scene_background_gate,
    _scene_real_scene_mapping_gate,
    validate_bilibili_auto_packet,
    validate_douyin_auto_packet,
    validate_douyin_tiktok_repost_packet,
    validate_kuaishou_auto_packet,
    validate_platform_article_packet,
    validate_shipinhao_auto_packet,
    validate_wechat_auto_packet,
    validate_xiaohongshu_auto_packet,
)
from .models import ContentPackage, DeliveryResult, PublishReceipt, new_content_package_id
from .notify import Notifier
from .performance_collector import register_review_tasks
from .profiles import resolve_profile
from .publishers import build_publisher
from .resource import ResourceGuard
from .real_world_ai_policy import validate_real_world_ai_package
from .review import ReviewTokens
from .run_contract import build_run_contract
from .stage_input_refs import bind_stage_payload, has_stage_refs
from .risk import RiskFilter, redact_secrets
from .store import sha256_file
from .growth_recipe import validate_growth_recipe
from .seo import geo_check
from .wechat_toolchain import prepare_wechat_professional_draft, requires_wechat_toolchain, writer_evidence_accepted
from .workflow_runtime import (
    WorkflowBlocked,
    WorkflowStepRunner,
    strict_workflow_lock,
    write_platform_report,
)
from .platform_workflow_context import load_platform_workflow_context


def _bounded_ai_positioning(positioning):
    """Keep model input policy-complete without copying search taxonomies."""
    if not isinstance(positioning, dict):
        return {}
    pillars = positioning.get("pillars") or {}
    return {
        "policy_profile": positioning.get("policy_profile"),
        "policy_revision": positioning.get("policy_revision"),
        "definition": positioning.get("positioning") or positioning.get("name"),
        "pillars": list(pillars) if isinstance(pillars, dict) else list(pillars or []),
        "excluded_terms": list(positioning.get("excluded_terms") or []),
        "content_contract": positioning.get("content_contract") or {},
    }


def _draft_script_text(draft):
    """Include every platform narration before any media execution."""
    meta=draft.get('draft_meta') or {}
    variants=[draft]+list((meta.get('platform_drafts') or {}).values())
    scripts=[str((variant.get('draft_meta') or {}).get(field) or '')
        for variant in variants for field in ('video_script','narration_script')]
    return '\n'.join(dict.fromkeys(scripts)).strip()


class Pipeline:
    def __init__(self, store, config=None):
        self.store = store
        self.config = config or {}
        self.data_dir = Path(self.config.get("data_dir", store.path.parent))
        self.generator = DraftGenerator(self.config.get("generator", {}), stage_store=self.store)
        self.compliance = ComplianceChecker()
        risk_cfg = self.config.get("risk", {})
        self.risk = RiskFilter(
            risk_cfg.get("block_words"), risk_cfg.get("review_words"), risk_cfg.get("legacy_script", ""), risk_cfg.get("timeout", 20)
        )
        self.guard = ResourceGuard(self.data_dir, self.config.get("resources", {}))
        self.media = MediaBridge(self.config.get("media", {}), self.data_dir, self.guard,stage_store=self.store)
        review_cfg = self.config.get("review", {})
        self.review_tokens = ReviewTokens(review_cfg.get("key_path", self.data_dir / "review.key"))
        self.review_ttl = int(review_cfg.get("token_ttl_seconds", 86400))
        notify_cfg = dict(self.config.get("notifications", {}))
        notify_cfg.setdefault("log_path", str(self.data_dir / "notifications.jsonl"))
        self.notifier = Notifier(notify_cfg)
        self.content_hygiene_cfg = dict(self.config.get("content_hygiene", {}))
        self.content_hygiene_cfg.setdefault("enabled", True)
        execution_cfg = self.config.get("workflow_execution", self.config.get("execution", {}))
        self.strict_serial = execution_cfg.get("concurrency_mode", execution_cfg.get("mode", "strict_serial")) == "strict_serial"
        self.lock_timeout_seconds = int(execution_cfg.get("lock_timeout_seconds", execution_cfg.get("stale_task_timeout_seconds", 1800)))
        workflow_cfg = self.config.get("workflow", {})
        flags = self.config.get("feature_flags", {})
        # Fail closed when the workflow or production feature flag declares the
        # channel quality gate as required; local test/default configs may still
        # run review-only gates without becoming hard blockers.
        self.require_gate_pass = bool(workflow_cfg.get("require_gate_pass")) or flags.get("channel_auto_workflow_gate") == "enforce"
        learning_cfg = dict(self.config.get("owned_learning", {}) or {})
        self.owned_learning_enabled = bool(learning_cfg.get("enabled")) and flags.get("owned_learning_control") == "enforce"
        self.owned_learning = None
        if self.owned_learning_enabled:
            from .owned_learning import OwnedLearningStore
            self.owned_learning = OwnedLearningStore(
                self.store.path,
                automation_enabled=bool(learning_cfg.get("apply_treatment") is True),
            )

    def create(self, topic, platforms, brief=None, profile="default", topic_fingerprint=""):
        revision=(brief or {}).get("media_revision_request")
        if revision is not None:
            import re
            if (not isinstance(revision,dict) or set(revision)!={"parent_media_id","input_manifest_sha256"}
                    or not re.fullmatch('[a-f0-9]{16}',str(revision['parent_media_id']))
                    or not re.fullmatch('[a-f0-9]{64}',str(revision['input_manifest_sha256']))):
                raise ValueError('invalid_media_revision_request')
            parent=self.store.get_job(revision['parent_media_id'])
            if topic.strip()!=parent['topic'] or list(platforms)!=parent['platforms'] or profile!='default':
                raise ValueError('media_revision_requested_identity_changed')
            path=self.data_dir/'media-revisions'/(revision['input_manifest_sha256']+'.json')
            return self.create_media_revision(parent['id'],str(path),revision['input_manifest_sha256'])
        platforms = list(dict.fromkeys(str(p).strip() for p in platforms if str(p).strip()))
        explicit_brief = brief or {}
        resolved = resolve_profile(self.config.get("profiles", {}), profile, explicit_brief)
        resolved["platforms"] = platforms
        if len(platforms) == 1:
            resolved.setdefault("platform", platforms[0])
            # 正常调用方从实际渠道配置绑定账号与规则版本，不从模型报告补身份。
            platform = platforms[0]
            selector = (self.config.get('publishers', {}).get('platforms', {}).get(platform) or {})
            account = selector.get('account') or selector.get('account_name')
            contract = build_run_contract(platform)
            lane = (contract.get('channel_rules') or {}).get('lane')
            if isinstance(account, str) and account.strip() and isinstance(lane, str) and lane.strip():
                resolved.setdefault('account_id', account)
                resolved['account_lane'] = lane
                resolved['lane'] = lane
                resolved['account_context'] = {
                    'account_id': resolved['account_id'], 'account_lane': lane, 'platform': platform,
                    'publisher_account': account, 'source': 'native_runtime_publisher_selector',
                    'selector_sha256': hashlib.sha256(json.dumps({
                        'platform': platform, 'account': account, 'publisher_type': selector.get('type')},
                        ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                    'rulebook_sha256': contract['rulebook']['sha256'],
                }
        explicit_language = any(key in explicit_brief for key in ("language", "locale", "language_locked"))
        if platforms and all(str(p).casefold() in GLOBAL_EN_PLATFORMS for p in platforms) and not explicit_language:
            resolved["language"] = "en"
        decision_builder = None
        if self.owned_learning_enabled:
            if len(platforms) != 1:
                raise ValueError("owned_learning_single_platform_required")
            scope = (platforms[0], str(resolved.get("account_id") or ""), str(resolved.get("lane") or ""), str(resolved.get("content_form") or ""))
            if not all(scope):
                raise ValueError("owned_learning_scope_required")
            decision_builder = lambda job_id, conn: self.owned_learning.decide_in_transaction(conn, job_id=job_id, scope=scope)
        return self.store.create_job(topic, platforms, resolved, profile, topic_fingerprint, decision_builder=decision_builder)

    def _bounded_owned_decision(self, brief):
        """Expose only frozen attribution data; strategy vector stays server-side."""
        decision = dict((brief or {}).get("owned_decision") or {})
        allowed = {"assignment_id", "experiment_id", "policy_id", "approval_id", "arm", "created_at"}
        return {key: decision[key] for key in allowed if key in decision}

    def create_media_revision(self, parent_job_id, manifest_path, manifest_sha256):
        from .media_revision import create_revision
        return create_revision(self, parent_job_id, manifest_path, manifest_sha256)

    def run(self, job_id, force=False):
        job = self.store.get_job(job_id)
        if job["state"] != "created" and not force:
            return self._hydrate(job)
        if force and job["state"] not in {"created", "failed", "blocked", "rejected"}:
            raise ValueError(f"cannot force generation from state: {job['state']}")
        owner = self._worker_id()
        workflow_id = f"wf_{job_id}"
        with strict_workflow_lock(self.store, owner, workflow_id, self.lock_timeout_seconds, self.strict_serial):
            from .normal_execution_lease import normal_job_claim_seconds
            claim_ttl = normal_job_claim_seconds(self.store, job_id)
            if not self.store.claim(job_id, {job["state"]}, owner, claim_ttl, "generating"):
                raise RuntimeError("job is already claimed by another worker")
            runner = WorkflowStepRunner(self.store, workflow_id, job_id, notifier=self.notifier)
            try:
                job = self.store.get_job(job_id)
                runner.succeeded("initialize_task", {"platforms": job["platforms"], "profile": job.get("profile", "")})
                platform_contexts = {}
                for platform in job["platforms"]:
                    platform_contexts[platform] = load_platform_workflow_context(platform, plan=job.get("brief") or {})
                runner.succeeded(
                    "load_platform_workflow_context",
                    {"platforms": platform_contexts},
                    depends_on=["initialize_task"],
                    message="platform rules, strategy, skills, publish mode, and tool selection loaded",
                )
                from .visual_policy_gate import validate_content_policy_inputs
                policy_inputs = validate_content_policy_inputs(job, platform_contexts, store=self.store)
                if not policy_inputs.get("passed"):
                    runner.block(
                        "validate_content_policy_inputs", "content_policy_inputs_invalid",
                        "current platform policy, skill execution, or strategy evidence is missing or changed",
                        policy_inputs, depends_on=["load_platform_workflow_context"],
                    )
                runner.succeeded("validate_content_policy_inputs", policy_inputs,
                    depends_on=["load_platform_workflow_context"])
                if (job.get("brief") or {}).get("media_revision"):
                    from .media_revision import run_revision
                    return run_revision(self, job_id, owner, workflow_id, runner)
                return self._continue_native_generation(job_id, owner, workflow_id, runner, platform_contexts, force=force)
            except WorkflowBlocked as exc:
                current = self.store.get_job(job_id)
                if current.get("lease_owner") == owner:
                    blocked = self.store.release_claim(job_id, owner, "blocked", "workflow_blocked", exc, detail={"step": exc.step, "reason_code": exc.reason_code})
                    report = write_platform_report(self.store, self.data_dir, workflow_id, blocked, "", "blocked", error=str(exc))
                    report_payload = dict(blocked)
                    report_payload["report_path"] = report.get("path", "")
                    self.notifier.send("blocked", report_payload)
                    return self._hydrate(blocked)
                raise
            except Exception as exc:
                current = self.store.get_job(job_id)
                if current.get("lease_owner") == owner:
                    self.store.release_claim(job_id, owner, "failed", "generation_failed", redact_secrets(exc))
                raise

    def _continue_native_generation(self, job_id, owner, workflow_id, runner, platform_contexts, force=False, prepared_stage=None):
        job = self.store.get_job(job_id)
        from .original_knowledge import is_original_editorial
        if prepared_stage is None and (not (job.get('brief') or {}).get('run_contract')
                or (job.get('brief') or {}).get('source_collection_required') is True or is_original_editorial(job)):
            from .task_source_inputs import collect_task_source_inputs,persist_task_source_inputs,refresh_task_source_contexts,SourceInputsBlocked
            def collect_inputs():
                try:return collect_task_source_inputs(self.store,self.config,job,platform_contexts)
                except SourceInputsBlocked as error:
                    runner.block('collect_native_source_inputs',error.code,
                        'Native source/planning inputs are incomplete; source-analysis model calls may already have run; media generation has not started',
                        error.detail,depends_on=['load_platform_workflow_context'])
            source_brief=runner.run('collect_native_source_inputs',collect_inputs,
                depends_on=['load_platform_workflow_context'],require_output=True)
            job=persist_task_source_inputs(self.store,job,owner,source_brief)
            platform_contexts=refresh_task_source_contexts(platform_contexts,source_brief)
            runner.succeeded('refresh_task_source_contexts',{'platforms':platform_contexts},
                depends_on=['collect_native_source_inputs'])
        if prepared_stage is not None:
            from .native_stage_resume import require_active_stage_grant
            grant = require_active_stage_grant(self.store, job_id, owner)
            if prepared_stage is not grant['prepared_stage']:
                raise PermissionError('native_stage_prepared_context_not_same_grant')
            job = self.store.get_job(job_id)
            brief = prepared_stage['brief']
            platform_briefs = prepared_stage['platform_briefs']
        else:
            hygiene = self._content_hygiene(job)
            if hygiene["status"] == "blocked" and not force:
                self.store.record_event(job_id, "content_hygiene_blocked", {"content_hygiene": hygiene})
                runner.block(
                    "run_content_hygiene",
                    "content_hygiene_blocked",
                    "topic duplicates or overlaps recent channel history",
                    {"content_hygiene": hygiene},
                    depends_on=["initialize_task"],
                )
            runner.succeeded("run_content_hygiene", hygiene, depends_on=["initialize_task"])
            brief = runner.run("load_content_strategy", lambda: self._enrich_brief(job, hygiene), depends_on=["run_content_hygiene"], require_output=True)
            if self.owned_learning_enabled and len(job["platforms"]) == 1:
                decision = dict((job.get("brief") or {}).get("owned_decision") or {})
                source_brief = job.get("brief") or {}
                scope = (str(job["platforms"][0]), str(source_brief.get("account_id") or ""), str(source_brief.get("lane") or ""), str(source_brief.get("content_form") or ""))
                resolution = self.owned_learning.resolve_treatment(
                    assignment_id=str(decision.get("assignment_id") or ""),
                    scope=scope,
                    explicit_enable=bool((self.config.get("owned_learning") or {}).get("apply_treatment") is True),
                )
                brief["owned_learning_treatment"] = resolution
                self.store.record_event(job_id, "owned_learning_treatment_resolved", {"arm": resolution.get("arm"), "reason": resolution.get("reason", "")})
            from .task_source_inputs import project_task_source_brief,persist_task_source_inputs
            from .intelligence import prepare_generation_strategy_inputs
            platform_briefs={platform:self._bind_platform_source_inputs(job_id,
                prepare_generation_strategy_inputs(job['topic'],project_task_source_brief(brief,platform)),platform,context,owner)
                for platform,context in platform_contexts.items()}
            for platform,scoped in platform_briefs.items():
                # Kuaishou resolves its BGM with its source inputs; the pet lane embeds a licensed library track.
                if platform=='douyin_pet' and not scoped.get('audio_plan'):
                    from .audio_plan_resolver import resolve_audio_plan
                    audio=resolve_audio_plan(self.config,dict(job,platforms=[platform]),self.store.path.parent)
                    self.store.record_event(job_id,'audio_plan_resolved',{'platform':platform,'status':audio.get('status'),'failures':audio.get('failures') or []})
                    if audio.get('status')=='resolved':scoped['audio_plan']=audio
            if len(platform_briefs)==1:brief=dict(next(iter(platform_briefs.values())))
            brief['platform_workflow_inputs']=copy.deepcopy(platform_briefs)
            if brief.get('source_collection_audit'):
                job=persist_task_source_inputs(self.store,job,owner,brief)
            runner.succeeded("run_operation_strategy", {"historical_feedback": bool(brief.get("historical_feedback")),
                "platform_strategy_evidence":{platform:scoped['strategy_evidence_gate'] for platform,scoped in platform_briefs.items()}}, depends_on=["load_content_strategy"])
        # Check if job has pre-populated body content (manually written, not a stub)
        existing_body = (job.get("body") or "").strip()
        if len(existing_body) > 100:
            # Use pre-populated content directly; run naturalize_copy for quality scoring
            # Authored content does not invoke a generation prompt. The
            # original brief remains intact for the final AI package gate.
            context_brief = dict(brief)
            for key in ("lane", "policy_profile", "positioning", "real_world_ai_positioning", "workflow_context"):
                context_brief.pop(key, None)
            ctx = build_generation_context(job["topic"], context_brief)
            rewrite = naturalize_copy(existing_body, ctx)
            if "```" in existing_body:
                # Markdown/code articles are authored artifacts. The
                # prose humanizer flattens code indentation and tables,
                # so preserve the original body while retaining its
                # diagnostic scores and notes.
                rewrite["body"] = existing_body
                rewrite.setdefault("rewrite_notes", []).append("preserved fenced code and markdown structure")
            draft = {
                "title": job.get("title") or job["topic"],
                "body": rewrite["body"],
                "provider": "pre_populated",
                "prompt_version": self.generator.PROMPT_VERSION,
                "draft_meta": {
                    k: v for k, v in ctx.items()
                    if k in {"trend_stage", "trend_angle", "reference_titles", "style",
                              "source_summary", "source_catalog", "topic_clusters",
                              "niche_report", "viral_score", "viral_growth_report", "strategy",
                              "image_prompt", "video_prompt", "hashtags", "narration_guide",
                              "open_notebook_research", "content_hygiene",
                              "geo_score", "geo_details"}
                },
            }
            user_brief = job.get("brief") or {}
            for _field in [
                "strategy_brief", "operations_workflow", "content_workflow_inputs",
                "content_blueprint", "content_depth_plan", "source_status", "trend_evidence", "platform_source_matrix",
                "growth_recipe", "tool_selection_plan", "topic_decision", "process_evidence", "cta_evidence",
                "asset_mix_plan", "humanization_plan",
                "opening_hook", "hook_type", "sections", "section_image_map",
                "visual_template_selection", "real_scene_backgrounds", "section_real_scene_mapping",
                "knowledge_card_plan", "embedded_knowledge_cards", "cover_design",
                "differentiation_dimensions", "reader_payoff", "concrete_case", "actionable_checklist",
                "growth_plan", "platform_identity", "platform_strategy", "platform_adaptation",
                "visual_content_policy", "preflight_manifest", "publishing_plan",
            ]:
                if user_brief.get(_field):
                    draft["draft_meta"][_field] = user_brief[_field]
            draft["draft_meta"]["quality_scores"] = rewrite["quality_scores"]
            draft["draft_meta"]["quality_gate"] = rewrite["quality_gate"]
            draft["draft_meta"]["rewrite_notes"] = rewrite["rewrite_notes"]
            draft["draft_meta"]["content_form"] = brief.get("content_form") or ctx.get("strategy", {}).get("content_form", "long_article")
            draft["draft_meta"]["media_plan"] = ctx.get("strategy", {}).get("asset_plan", [])
            draft["draft_meta"]["video_toolchain_plan"] = ctx.get("strategy", {}).get("video_toolchain_plan", {})
            # Record generate_content step for audit completeness
            runner.succeeded("generate_content", {
                "provider": "pre_populated",
                "body_chars": len(draft["body"]),
                "title": draft["title"],
                "quality_gate_passed": rewrite["quality_gate"]["passed"],
            }, depends_on=["run_operation_strategy"])
        else:
            draft = runner.run("generate_content", lambda: self._generate_scoped_drafts(job_id,job["topic"],platform_briefs), depends_on=["run_operation_strategy"], require_output=True)
        return self._continue_generated_draft(job_id, owner, workflow_id, runner,
                                              platform_contexts, job, brief, platform_briefs, draft)

    def _continue_generated_draft(self, job_id, owner, workflow_id, runner,
                                  platform_contexts, job, brief, platform_briefs, draft):
        # Shared suffix callers do not carry the original function's local variables.
        # Read the actual current same-job/all-channel dedup result; never synthesize it.
        hygiene = self._content_hygiene(job)
        if hygiene.get("status") == "blocked":
            self.store.record_event(job_id, "content_hygiene_blocked", {"content_hygiene": hygiene})
            runner.block("validate_current_suffix_hygiene", "content_hygiene_blocked",
                         "current topic duplicates or overlaps recent channel history",
                         {"content_hygiene": hygiene}, depends_on=["generate_content"])
        runner.succeeded("validate_current_suffix_hygiene", hygiene, depends_on=["generate_content"])
        if draft.get('provider')=='pre_populated':
            variants={}
            for platform,scoped_brief in platform_briefs.items():
                variant=copy.deepcopy(draft)
                from .video_toolchain import build_video_toolchain_plan
                strategy=dict(variant['draft_meta'].get('strategy') or {},primary_platforms=[platform])
                variant['draft_meta']['strategy']=strategy
                variant['draft_meta']['video_toolchain_plan']=build_video_toolchain_plan(strategy,scoped_brief)
                self.generator._inherit_workflow_inputs(scoped_brief,variant['draft_meta'],stage_store=self.store,stage_job_id=job_id)
                variants[platform]=variant
            if len(variants)>1:draft['draft_meta']['platform_drafts']=variants
            else:draft=next(iter(variants.values()))
        if requires_wechat_toolchain(self.config, job["platforms"]):
            from .task_source_inputs import project_task_source_job
            variants=(draft.get('draft_meta') or {}).get('platform_drafts') or {}
            writer_draft=copy.deepcopy(variants.get('wechat') or draft)
            writer_job=project_task_source_job(dict(job,title=draft['title'],body=draft['body'],draft_meta=draft['draft_meta']),'wechat')
            writer_result = runner.run(
                "prepare_wechat_professional_toolchain",
                lambda: prepare_wechat_professional_draft(job_id, writer_job, writer_draft, self.config, self.data_dir),
                depends_on=["generate_content"],
                require_output=True,
            )
            if not writer_evidence_accepted(self.config, writer_result):
                runner.block(
                    "prepare_wechat_professional_toolchain",
                    "wechat_toolchain_unavailable",
                    "WeChat production workflow requires successful selected-writer evidence",
                    (writer_result.get("draft_meta") or {}).get("tool_invocations") or {},
                    depends_on=["generate_content"],
                )
            if variants:
                variants['wechat']=writer_result
                if job['platforms'][0]=='wechat':draft=copy.deepcopy(writer_result)
                draft.setdefault('draft_meta',{})['platform_drafts']=variants
            else:draft=writer_result
        self._freeze_pet_video_beats(draft,platform_briefs)
        self._validate_scoped_narrations(job_id,draft,platform_briefs,runner)
        if self.config.get('humanizer', {}).get('enabled', True):
            self._humanize_draft(job_id, draft)
        self._validate_draft_structure(draft)
        draft.setdefault("draft_meta", {}).setdefault("strategy", {}).setdefault("primary_platforms", job["platforms"])
        if brief.get('content_mode')=='original_knowledge':
            from .original_knowledge import validate_original_copy
            copy_report=validate_original_copy(self.store,job,str(draft.get('body') or '')+'\n'+_draft_script_text(draft))
            runner.succeeded('original_copy_dedup',copy_report,depends_on=['generate_content'])
        runner.succeeded("validate_content_structure", {"title_present": bool(draft.get("title")), "body_chars": len(str(draft.get("body", "")))}, depends_on=["generate_content"])
        self._validate_real_world_ai_package(job, brief, draft, runner)
        self._persist_intelligence(job_id, draft.get("draft_meta", {}))
        script_text=_draft_script_text(draft)
        text = draft["title"] + "\n" + draft["body"] + ('\n'+script_text if script_text else '')
        claim_ledger = (draft.get("draft_meta") or {}).get("claim_ledger") or brief.get("claim_ledger") or []
        claim_gate = validate_claims(text, claim_ledger)
        draft.setdefault("draft_meta", {})["claim_gate"] = claim_gate
        strict_claims = bool((job.get("brief") or {}).get("run_contract")) or str((job.get("brief") or {}).get("selection_mode") or "") == "editorial_calendar"
        if not claim_gate.get("passed") and strict_claims:
            cleaned_title = (sanitize_unsupported_claims(draft["title"], claim_gate.get("findings"))
                             or strip_numeric_claims(draft["title"]) or str(job.get("topic") or "Verified workflow"))
            cleaned_body = sanitize_unsupported_claims(draft["body"], claim_gate.get("findings"))
            cleaned_gate = validate_claims(cleaned_title + "\n" + cleaned_body + ('\n'+script_text if script_text else ''), claim_ledger)
            if len(cleaned_body) >= 80 and cleaned_gate.get("passed"):
                draft["title"] = cleaned_title
                draft["body"] = cleaned_body
                text = cleaned_title + "\n" + cleaned_body + ('\n'+script_text if script_text else '')
                draft["draft_meta"]["claim_sanitization"] = {
                    "removed_count": len([row for row in claim_gate.get("findings") or [] if not row.get("covered")]),
                    "original_gate": claim_gate,
                    "passed": True,
                }
                claim_gate = cleaned_gate
                draft["draft_meta"]["claim_gate"] = claim_gate
            else:
                runner.block(
                    "validate_factual_claims",
                    "factual_claim_evidence_missing",
                    "numeric or first-person operational claims require verifiable evidence",
                    claim_gate,
                    depends_on=["validate_content_structure"],
                )
        runner.succeeded("validate_factual_claims", claim_gate, depends_on=["validate_content_structure"], message="legacy review-only claim findings" if not claim_gate.get("passed") else "")
        if (job.get("brief") or {}).get("run_contract"):
            # Ensure depth plan exists even for pre-populated path
            if not (draft.get("draft_meta") or {}).get("content_depth_plan"):
                from .content_depth import build_content_depth_plan
                # build from current body if generator missed it
                _evidence = []
                try:
                    _evidence = (draft.get("draft_meta") or {}).get("evidence") or []
                    if not _evidence:
                        mtx = (job.get("brief") or {}).get("platform_source_matrix", {})
                        samples = (mtx.get("trend_evidence") or {}).get("samples") or []
                        urls = [str(s.get("url") or "").strip() for s in samples if str(s.get("url") or "").strip()]
                        if urls:
                            _evidence = urls
                        else:
                            # fallback to any attempted_sources url
                            attempted = mtx.get("attempted_sources") or []
                            urls2 = [str(s.get("url") or "").strip() for s in attempted if str(s.get("url") or "").strip()]
                            _evidence = urls2[:3] or [str((job.get("brief") or {}).get("platform_source_matrix", {}).get("trend_evidence", {}).get("source", "") or "")]
                except Exception:
                    _evidence = []
                draft.setdefault("draft_meta", {})["content_depth_plan"] = build_content_depth_plan(
                    str(draft.get("title") or job.get("topic") or ""),
                    str(draft.get("body") or ""),
                    evidence=_evidence,
                    platform=str((job.get("platforms") or [""])[0]),
                )
            depth_plan = (draft.get("draft_meta") or {}).get("content_depth_plan")
            series = (depth_plan.get("series_plan") if isinstance(depth_plan, dict) else None) or {}
            if (isinstance(depth_plan, dict) and depth_plan.get("continuation_claimed")
                    and not (str(series.get("next_topic") or "").strip() and str(series.get("delivery_window") or "").strip())):
                # A single post without a series plan must not promise another release; drop those sentences.
                from .content_depth import claims_continuation, strip_continuation_claims
                holders = [draft] + list(((draft.get("draft_meta") or {}).get("platform_drafts") or {}).values())
                before = sum(len(str(item.get("body") or "")) for item in holders if isinstance(item, dict))
                for item in holders:
                    if isinstance(item, dict) and isinstance(item.get("body"), str):
                        item["body"] = strip_continuation_claims(item["body"])
                if not any(isinstance(item, dict) and claims_continuation(item.get("body") or "") for item in holders):
                    depth_plan["continuation_claimed"] = False
                    after = sum(len(str(item.get("body") or "")) for item in holders if isinstance(item, dict))
                    self.store.record_event(job_id, "continuation_claims_removed", {"body_chars": {"before": before, "after": after}})
            depth_gate = validate_content_depth_plan((draft.get("draft_meta") or {}).get("content_depth_plan"))
            draft["draft_meta"]["content_depth_gate"] = depth_gate
            if not depth_gate.get("passed"):
                runner.block(
                    "validate_content_depth",
                    "content_depth_contract_failed",
                    "scheduled content lacks evidence, knowledge depth, actions, or a valid series plan",
                    depth_gate,
                    depends_on=["validate_factual_claims"],
                )
            runner.succeeded("validate_content_depth", depth_gate, depends_on=["validate_factual_claims"])
        else:
            runner.skipped("validate_content_depth", "legacy_job_without_run_contract", "depth enforcement applies to compiled scheduled runs", depends_on=["validate_factual_claims"])
        geo = runner.run("run_fact_check", lambda: geo_check(text), depends_on=["validate_content_depth"], require_output=True)
        self.store.save_geo_score(job_id, geo)
        risk = runner.run("run_safety_gate", lambda: self.risk.evaluate(text), depends_on=["run_fact_check"], require_output=True)
        risk["content_hygiene"] = hygiene
        compliance = self.compliance.evaluate(text, job["brief"], job["platforms"])
        risk["compliance"] = compliance
        blocking_claim_codes = {
            str(item.get("code") or "")
            for item in compliance.get("findings", [])
            if isinstance(item, dict)
        }
        strict_compliance = bool((job.get("brief") or {}).get("run_contract")) or str((job.get("brief") or {}).get("selection_mode") or "") == "editorial_calendar"
        if strict_compliance and blocking_claim_codes & {"numeric_claim_without_source", "attribution_without_source"}:
            runner.block(
                "run_safety_gate",
                "unsupported_factual_claims",
                "unsourced numeric or attribution claims cannot proceed to media generation",
                compliance,
                depends_on=["run_fact_check"],
            )
        if risk["level"] == "pass" and compliance["level"] == "review":
            risk["level"] = "review"
        if risk["level"] == "block":
            runner.block("run_safety_gate", "safety_gate_blocked", "content safety gate blocked this job", risk)
        if any(str(platform).casefold() in {"twitter", "x"} for platform in job["platforms"]):
            from .target_adaptation import generate_target_adaptation
            variants=(draft.get('draft_meta') or {}).get('platform_drafts') or {}
            for platform in job["platforms"]:
                if str(platform).casefold() not in {"twitter", "x"}:
                    continue
                variant=variants.get(platform) or draft
                scoped=platform_briefs.get(platform) or brief
                meta=variant.setdefault('draft_meta',{})
                if not meta.get('target_adaptation_ref') and meta.get('normal_generation_source_ref'):
                    step='adapt_twitter_target_copy' if len(variants)<=1 else 'adapt_twitter_target_copy_'+platform
                    meta['target_adaptation_ref']=runner.run(step,
                        lambda variant=variant,scoped=scoped:generate_target_adaptation(self,job,variant,scoped,runner),
                        depends_on=['run_safety_gate'],require_output=True)
                if job_id == "25110343c3354385" or meta.get('target_adaptation_ref'):
                    self._validate_target_publication_copy(job_id, dict(job,brief=scoped,platforms=[platform]), scoped, variant, scoped.get("claim_ledger",claim_ledger), runner)
        self._bind_video_asset_semantics(job_id,draft,platform_briefs,owner)
        brief['platform_workflow_inputs']=copy.deepcopy(platform_briefs)
        if brief.get('source_collection_audit'):
            from .task_source_inputs import persist_task_source_inputs
            job=persist_task_source_inputs(self.store,job,owner,brief)
        gate = self._quality_gate(job_id, draft, risk, geo, phase="generation")
        draft["draft_meta"]["geo_score"] = geo["score"]
        draft["draft_meta"]["geo_details"] = geo
        draft["draft_meta"]["quality_gate"] = gate
        if gate.get("passed") is not True:
            risk["level"] = "review"
            runner.block("run_quality_gate", "quality_gate_failed", "required quality gate failed", gate, depends_on=["run_safety_gate"])
        runner.succeeded("run_quality_gate", gate, depends_on=["run_safety_gate"])
        if self.config.get("feature_flags", {}).get("content_package_v1"):
            for platform in job["platforms"]:
                package = ContentPackage(
                    content_package_id=new_content_package_id(platform, ""),
                    status="created",
                    platform=platform,
                    account_id="",
                    content_type=draft.get("draft_meta", {}).get("content_form", "article"),
                    topic=job["topic"],
                    title=draft["title"],
                ).to_dict()
                package["job_id"] = job_id
                self.store.save_content_package(package, job_id=job_id)
    # 归藏材质插画：为文章内容生成带中文标签的解释图
        runner.succeeded("collect_or_prepare_materials", {"content_package_v1": bool(self.config.get("feature_flags", {}).get("content_package_v1"))}, depends_on=["run_quality_gate"])
        illustration_enabled = self.config.get("media", {}).get("illustration", {}).get("enabled", False)
        if illustration_enabled:
            self._generate_optional_media(job_id, "illustration", runner, ["collect_or_prepare_materials"],draft=draft)
    # gzh-design：Markdown → 公众号 HTML 格式转换
        gzh_enabled = self.config.get("media", {}).get("wechat_format", {}).get("enabled", False)
        if gzh_enabled and any("wechat" in p.lower() for p in job.get("brief", {}).get("platforms", job.get("platforms", []))):
            self._generate_optional_media(job_id, "wechat_format", runner, ["collect_or_prepare_materials"],draft=draft)
    # magazine-layout：Markdown → 杂志风格 HTML（独立文章页）
        magazine_enabled = self.config.get("media", {}).get("magazine_format", {}).get("enabled", False)
        if magazine_enabled and any(p not in ("wechat", "weixin") for p in job.get("brief", {}).get("platforms", job.get("platforms", []))):
            self._generate_optional_media(job_id, "magazine_format", runner, ["collect_or_prepare_materials"],draft=draft)
        if self._strict_article_job(job_id):
            # Strict article jobs are handled per-job by _media_required;
            # do not mutate shared pipeline/media configuration.
            pass
        if (job['platforms']==['twitter'] and (draft.get('draft_meta')or{}).get('content_form') in {'image_text','image_text_post'}
                and not (draft.get('draft_meta')or{}).get('current_visual_plan_ref')):
            from .current_twitter_visual_plan_producer import prepare_current_twitter_visual_plan
            draft['draft_meta']['current_visual_plan_ref']=runner.run('prepare_current_twitter_visual_plan',
                lambda:prepare_current_twitter_visual_plan(self,self._media_generation_job(job_id,draft),draft),
                depends_on=['run_quality_gate'],require_output=True)
        generated_image = self._generate_optional_media(job_id, "image", runner, ["collect_or_prepare_materials"], step_name="generate_or_collect_images",draft=draft)
        self._validate_image_requirements(job_id, runner, generated_image)
        self._validate_strict_article_completion(job_id, draft, runner)
        platform_videos = {}
        shared_media = []
        media_job = self._media_generation_job(job_id,draft)
        generated_kinds = self._execution_media_kinds(generated_media_kinds_for_job(media_job, self.config),media_job,self.config)
        generated_kinds.discard("image")
        for kind in generated_kinds:
            if kind == 'cover':
                reused=runner.run('generate_cover',lambda:self._reuse_registered_cover(job_id,generated_image,self._media_generation_job(job_id,draft)),
                    depends_on=['validate_image_requirements'],require_output=True)
                image_rows=list((generated_image or {}).get('images') or [])
                if (generated_image or {}).get('kind')=='cover':image_rows.append(generated_image)
                if not any(str(row.get('role') or row.get('kind') or '').casefold()=='cover'
                           and str(row.get('path'))==reused['path'] for row in image_rows):
                    shared_media.append(('cover',reused))
            elif kind == "video":
                artifacts = self._generate_video_per_platform(job_id, runner, ["validate_image_requirements"],draft=draft,owner=owner)
                for platform, artifact in artifacts:
                    platform_videos[platform] = artifact
                    scoped = {"draft_meta": {}}
                    self._attach_video_render_evidence(scoped, artifact)
                    draft["draft_meta"].setdefault("platform_render_evidence", {})[platform] = scoped["draft_meta"]
                    if len(job["platforms"]) == 1:
                        draft["draft_meta"].update(scoped["draft_meta"])
            else:
                generated = self._generate_optional_media(job_id, kind, runner, ["validate_image_requirements"],draft=draft)
                if isinstance(generated, dict) and generated.get("path"):
                    shared_media.append((kind, generated))
        if 'wechat' in job['platforms']:
            self._render_wechat_scoped(job_id,draft,runner)
        else:self._write_article_artifact_manifest(job_id, draft)
        # 未审核的真实草稿和实物先登记，供正常审核读取；合格输出须在终门之后。
        self.store.save_draft(job_id, draft["title"], draft["body"], "unreviewed", risk,
                              draft.get("prompt_version", ""), draft.get("draft_meta", {}))
        return self.continue_rendered_candidate(job_id, owner, runner, generated_image,
                                                platform_videos, shared_media)

    def continue_rendered_candidate(self, job_id, owner, runner, generated_image,
                                    platform_videos, shared_media=None):
        """复用已保存当前稿和真实素材的完整审核、输出及交付尾段。"""
        job=self.store.get_job(job_id)
        draft={field:copy.deepcopy(job[field]) for field in ('title','body','draft_meta','prompt_version')}
        from datetime import datetime,timezone
        if (job.get('state') != 'generating' or job.get('lease_owner') != owner
                or not job.get('lease_expires_at')
                or job['lease_expires_at'] <= datetime.now(timezone.utc).isoformat(timespec='seconds')):
            raise RuntimeError('current_rendered_candidate_generation_lease_required')
        versions=self.store.draft_versions(job_id)
        if (not versions or not str(draft['title']).strip() or not str(draft['body']).strip()
                or not isinstance(draft['draft_meta'],dict)):
            raise RuntimeError('current_saved_rendered_candidate_required')
        latest=versions[-1]
        if (latest.get('title') != draft['title'] or latest.get('body') != draft['body']
                or latest.get('draft_meta') != draft['draft_meta']):
            raise RuntimeError('current_saved_rendered_candidate_version_mismatch')
        risk=copy.deepcopy(job.get('risk'))
        geo=copy.deepcopy(draft['draft_meta'].get('geo_details'))
        if (not isinstance(risk,dict) or risk.get('level') not in {'pass','review'}
                or not isinstance(geo,dict) or not isinstance(geo.get('score'),(int,float))):
            raise RuntimeError('current_saved_candidate_actual_gate_results_required')
        prepared_outputs = self._prepare_platform_output_sources(job_id, generated_image, platform_videos, shared_media)
        self._execute_current_native_quality(job_id, runner)
        final_gate = self._quality_gate(job_id, draft, risk, geo, phase="rendered")
        draft["draft_meta"]["quality_gate"] = final_gate
        if not final_gate.get("passed", False):
            runner.block(
                "run_final_platform_quality_gate",
                "final_platform_quality_gate_failed",
                "rendered media did not satisfy required platform quality gate",
                final_gate,
                depends_on=["validate_image_requirements"],
            )
        runner.succeeded("run_final_platform_quality_gate", final_gate, depends_on=["validate_image_requirements"])
        self._validate_strict_article_completion(job_id, draft, runner)
        self._record_platform_outputs(job_id, final_gate, generated_image, platform_videos, shared_media,
                                      prepared_outputs=prepared_outputs)
        reviewed = self.store.release_claim(job_id, owner, "review_required", "review_requested", detail={"risk": risk["level"]})
        if self.config.get("delivery", {}).get("auto_stage_review_required"):
            reviewed = self.stage_drafts(job_id, owner=owner, already_locked=True)
        # Approval tokens are issued only by the authenticated review
        # command. They must never be written to logs or notifications.
        self.notifier.send("review_required", reviewed)
        return self._hydrate(reviewed)

    def _validate_target_publication_copy(self, job_id, job, brief, draft, claim_ledger, runner):
        from .target_adaptation import read_target_adaptation
        target = read_target_adaptation(dict(job, title=draft["title"], body=draft["body"],
                                             draft_meta=draft.get("draft_meta") or {}), "twitter")
        caption = target["caption"]
        target_claims = validate_claims(caption, claim_ledger)
        target_compliance = self.compliance.evaluate(caption, job["brief"], ["twitter"])
        target_risk = self.risk.evaluate(caption)
        from .content_depth import build_content_depth_plan
        contract = brief.get('run_contract') or {}
        channel = contract.get('channel_rules') or {}
        short_image_caption = (contract.get('version') == 'run_contract_v1' and contract.get('platform') == 'twitter'
            and 'image_text_post' in (channel.get('primary_types') or [])
            and 'concise_hook_under_280' in (channel.get('quality_gates') or [])
            and (draft.get('draft_meta') or {}).get('content_form') in {'image_text', 'image_text_post'})
        if short_image_caption:
            # A caption is not the article/video knowledge plan. The current source
            # still needs its actual prior depth gate, and the rendered cards still
            # require full native content/visual review before final output.
            source_depth = validate_content_depth_plan((draft.get('draft_meta') or {}).get('content_depth_plan'))
            target_depth = {'passed': None, 'applicable': False, 'status': 'not_applicable_to_short_caption',
                'source_depth_gate': source_depth, 'source_rulebook': contract.get('rulebook'),
                'rendered_publication_depth_review_required': True}
        else:
            target_depth_plan = build_content_depth_plan(
                job['topic'], caption, evidence=self.generator._depth_evidence(brief, draft.get('draft_meta') or {}),
                actions=[], series_plan={}, platform='twitter')
            target_depth = validate_content_depth_plan(target_depth_plan)
        target_candidates=self.store.content_candidates(
            limit=int(self.content_hygiene_cfg.get('candidate_limit', 200)),exclude_job_id=job_id)
        if (job.get('brief')or{}).get('caption_revision_ref'):
            from .native_stage_resume import caption_revision_ancestor
            family=caption_revision_ancestor(self.store,job)
            target_candidates=[r for r in target_candidates if r.get('id')not in family]
        target_dedup = audit_topic(caption,target_candidates,self.content_hygiene_cfg)
        target_tags = target.get("hashtags") or []
        target_cta = target.get("cta")
        failures = []
        if not 8 <= len(caption) <= 275:
            failures.append("x_text_length")
        if not isinstance(target_cta, str) or not target_cta.strip() or target_cta not in caption:
            failures.append("target_cta_missing")
        if (not isinstance(target_tags, list) or not 1 <= len(target_tags) <= 2
                or any(not isinstance(tag, str) or not tag.startswith("#") or tag not in caption
                       for tag in target_tags)):
            failures.append("target_hashtags_invalid")
        if target_claims.get("passed") is not True:
            failures.append("target_factual_claims")
        if target_compliance.get("level") == "block" or any(
                item.get("code") in {"numeric_claim_without_source", "attribution_without_source"}
                for item in target_compliance.get("findings") or []):
            failures.append("target_compliance")
        if ((target_depth.get('applicable') is False and (target_depth.get('source_depth_gate') or {}).get('passed') is not True)
                or (target_depth.get('applicable') is not False and target_depth.get('passed') is not True)):
            failures.append('target_content_depth')
        if target_dedup.get('status') == 'blocked':
            failures.append('target_seven_day_dedup')
        if target_risk.get("level") == "block":
            failures.append("target_safety")
        # Depth/scene/dedup of the original actual card content remains the normal prior gates.
        # The short target's distinct semantics/intent/content match is required in the normal
        # current-source/native AUTO review; this receipt is not a semantic quality verdict.
        target_gate = {"passed": not failures, "failures": failures,
                       "caption_sha256": target["caption_sha256"],
                       "target_copy_ref": target["target_copy_ref"],
                       "claim_gate": target_claims, "compliance": target_compliance,
                       "risk": target_risk, "content_depth_gate": target_depth,
                       "content_hygiene": target_dedup, "semantic_review_required": True}
        if failures:
            runner.block("validate_target_publication_copy", "target_publication_copy_invalid",
                         "actual target caption failed current factual, safety or platform rules",
                         target_gate, depends_on=["run_safety_gate"])
        runner.succeeded("validate_target_publication_copy", target_gate,
                         depends_on=["run_safety_gate"])

    def continue_revised_draft(self, job_id, owner, workflow_id, runner,
                               platform_contexts, prepared_brief, platform_briefs, draft):
        """事实修订独立资格；复用普通生成后全部门与实物后缀。"""
        from .factual_candidate_revision import require_active_factual_revision
        grant = require_active_factual_revision(self.store, job_id, owner)
        if (prepared_brief is not grant['prepared_brief']
                or platform_briefs is not grant['platform_briefs'] or draft is not grant['draft']):
            raise PermissionError('factual_revision_same_active_candidate_required')
        job = self.store.get_job(job_id)
        if job.get('state') != 'generating' or job.get('lease_owner') != owner:
            raise PermissionError('factual_revision_actual_current_lease_required')
        return self._continue_generated_draft(job_id, owner, workflow_id, runner,
            platform_contexts, job, prepared_brief, platform_briefs, draft)

    def resume_failed_stage(self, job_id, evidence_path, evidence_sha256):
        """同一原任务的有限未执行后缀；旧Source/成功前缀只引用。"""
        from .native_stage_resume import execute_native_stage_resume
        return execute_native_stage_resume(self, job_id, evidence_path, evidence_sha256)

    def resume_source_checkpoint(self, job_id, evidence_path, evidence_sha256):
        """正常resume入口：历史原生raw只读消费，当前新Scope完整下游；原失败不覆。"""
        import json, math, time, urllib.request
        from .media_revision import validate_source_checkpoint_resume, source_checkpoint_local_audio_inputs, digest
        from .native_quality_runner import current_active_role
        from .task_source_inputs import _collect_original_task_sources
        from .original_knowledge import consume_revision_source_checkpoint
        proof = validate_source_checkpoint_resume(self.store, evidence_path, evidence_sha256)
        local_audio_inputs = source_checkpoint_local_audio_inputs(proof)
        if proof['job_id'] != job_id or os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
            raise PermissionError('source_checkpoint_normal_no_publish_scope_required')
        home, task_id, route = current_active_role(1800)
        if task_id == proof['origin_run_id']:
            raise PermissionError('source_checkpoint_fresh_active_role_required')
        base = os.environ.get('HERMES_WORKER_CONTROL_URL')
        worker = os.environ.get('HERMES_WORKER_ID')
        token = os.environ.get('HERMES_WORKER_CONTROL_TOKEN')
        if base != 'http://127.0.0.1:22120' or not worker or not token:
            raise PermissionError('source_checkpoint_actual_control_required')
        request = urllib.request.Request(base + '/v1/jobs/' + task_id, headers={'X-Hermes-Worker-Token':token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise PermissionError('source_checkpoint_control_redirect_forbidden')
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(65537)
        if not 0 < len(raw) <= 65536:
            raise PermissionError('source_checkpoint_control_response_invalid')
        control = json.loads(raw)
        expected = {'create_control_job_id': proof['create_control_job_id'], 'resume': {
            'origin_run_id':proof['origin_run_id'], 'media_id':job_id, 'evidence_sha256':evidence_sha256}}
        if (control.get('job_id') != task_id or control.get('task_type') != 'media_run'
                or control.get('status') != 'running' or control.get('worker_id') != worker
                or control.get('claim_lane') != 'media' or control.get('payload') != expected
                or not isinstance(control.get('lease_until'), (int, float)) or control['lease_until'] <= time.time()):
            raise PermissionError('source_checkpoint_fresh_control_resume_binding_changed')
        stage = Path('/srv/hermes-worker-media/jobs') / task_id
        boundary_path = stage / 'media-authority-native-invocation.private.json'
        info = boundary_path.stat(); boundary = json.loads(boundary_path.read_bytes())
        if (boundary_path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o077
                or boundary.get('approved_budget_seconds') != 1800 or boundary.get('native_run_invoked') is not True
                or boundary.get('home') != str(home)):
            raise PermissionError('source_checkpoint_native_1800_boundary_required')
        deadline = info.st_mtime + 1800
        remaining = math.floor(deadline - time.time())
        if not 0 < remaining <= 1800:
            raise PermissionError('source_checkpoint_new_scope_deadline_exhausted')
        owner = self._worker_id(); workflow_id = 'wf_' + job_id
        original_steps = proof['original_steps']; original_events = proof['original_events']
        alias = 'collect_native_source_inputs__source_checkpoint_' + proof['origin_run_id']
        pipeline = self
        class CheckpointRunner(WorkflowStepRunner):
            @staticmethod
            def _dependencies(kwargs):
                kwargs = dict(kwargs)
                if kwargs.get('depends_on'):
                    kwargs['depends_on'] = [alias if value == 'collect_native_source_inputs' else value for value in kwargs['depends_on']]
                return kwargs
            def run(self, name, func, **kwargs):
                kwargs = self._dependencies(kwargs)
                if name == 'collect_native_source_inputs':
                    def consume():
                        current = pipeline.store.get_job(job_id)
                        ref = consume_revision_source_checkpoint(pipeline.store, pipeline.config, current, proof['source_checkpoint_ref'])
                        return _collect_original_task_sources(pipeline.store, pipeline.config, current, platform_contexts, original_ref=ref)
                    return super().run(alias, consume, **kwargs)
                return super().run(name, func, **kwargs)
            def block(self, name, *args, **kwargs):
                return super().block(alias if name == 'collect_native_source_inputs' else name, *args, **self._dependencies(kwargs))
            def succeeded(self, name, *args, **kwargs):
                return super().succeeded(name, *args, **self._dependencies(kwargs))
            def skipped(self, name, *args, **kwargs):
                return super().skipped(name, *args, **self._dependencies(kwargs))
        with strict_workflow_lock(self.store, owner, workflow_id, min(self.lock_timeout_seconds, remaining), self.strict_serial):
            proof = validate_source_checkpoint_resume(self.store, evidence_path, evidence_sha256)
            remaining = math.floor(deadline - time.time())
            if remaining <= 0 or not self.store.claim(job_id, {'blocked', 'failed'}, owner, remaining, 'generating'):
                raise RuntimeError('source_checkpoint_new_scope_claim_unavailable')
            original_config = self.config
            try:
                if local_audio_inputs is not None:
                    self.config = copy.deepcopy(original_config)
                    self.config['audio_plan_resolver'] = local_audio_inputs
                self.store.record_event(job_id, 'media_source_checkpoint_resume_started', {
                    'origin_run_id':proof['origin_run_id'], 'task_job_id':task_id, 'evidence_sha256':evidence_sha256,
                    'source_checkpoint_ref':proof['source_checkpoint_ref'], 'alias':alias, 'budget_seconds':1800,
                    'deadline_unix':deadline, 'source_generation_model_calls':0, 'no_publish_no_approval':True,
                    'original_steps_sha256':digest(original_steps), 'original_events_sha256':digest(original_events)})
                platform_contexts = {p:load_platform_workflow_context(p, plan=self.store.get_job(job_id).get('brief') or {})
                                     for p in self.store.get_job(job_id)['platforms']}
                from .visual_policy_gate import validate_content_policy_inputs
                policy = validate_content_policy_inputs(self.store.get_job(job_id), platform_contexts, store=self.store)
                runner = CheckpointRunner(self.store, workflow_id, job_id, notifier=self.notifier)
                if not policy.get('passed'):
                    runner.block('validate_source_checkpoint_current_policy', 'content_policy_inputs_invalid',
                                 'current normal policy inputs changed', policy)
                result = self._continue_native_generation(job_id, owner, workflow_id, runner, platform_contexts, force=False)
                return result
            except WorkflowBlocked as exc:
                current = self.store.get_job(job_id)
                if current.get('lease_owner') == owner:
                    return self._hydrate(self.store.release_claim(job_id, owner, 'blocked', 'workflow_blocked', exc,
                        detail={'step':exc.step, 'reason_code':exc.reason_code, 'source_checkpoint_resume':True}))
                raise
            except Exception as exc:
                current = self.store.get_job(job_id)
                if current.get('lease_owner') == owner:
                    self.store.release_claim(job_id, owner, 'failed', 'generation_failed', redact_secrets(exc))
                raise
            finally:
                self.config = original_config
                current_steps = {row['id']:row for row in self.store.workflow_steps(job_id)}
                current_events = {row['id']:row for row in self.store.events(job_id)}
                if (any(current_steps.get(row['id']) != row for row in original_steps)
                        or any(current_events.get(row['id']) != row for row in original_events)):
                    raise RuntimeError('source_checkpoint_original_history_changed')
    def resume_source_blocked(self, job_id, evidence_path, evidence_sha256, token):
        from .source_repair_runtime import JOB, WF, load_evidence, authorized_source_repair
        from .workflow_runtime import SourceRepairStepRunner
        if job_id != JOB or os.environ.get("CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH") != "0" or os.environ.get("AI_SELF_MEDIA_HERMES_TARGET") != "":
            raise PermissionError("fixed_internal_source_repair_no_publish_required")
        evidence = load_evidence(self.store, evidence_path, evidence_sha256)
        owner = self._worker_id()
        workflow_id = WF
        remaining = evidence["remaining_budget_seconds"]
        rows = [row for row in self.store.workflow_steps(job_id) if row["id"] == 5213]
        if len(rows) != 1 or not isinstance(rows[0].get("output"), dict) or not isinstance(rows[0]["output"].get("platforms"), dict):
            raise PermissionError("actual_original_public_platform_context_required")
        platform_contexts = copy.deepcopy(rows[0]["output"]["platforms"])
        with strict_workflow_lock(self.store, owner, workflow_id, min(self.lock_timeout_seconds, remaining), self.strict_serial):
            with authorized_source_repair(self.store, self.review_tokens, token, evidence_path, evidence_sha256, owner):
                original_delivery = self.config.get("delivery")
                try:
                    runner = SourceRepairStepRunner(self.store, workflow_id, job_id, notifier=self.notifier)
                    self.config["delivery"] = dict(original_delivery or {}, auto_stage_review_required=False)
                    return self._continue_native_generation(job_id, owner, workflow_id, runner, platform_contexts, force=False)
                except WorkflowBlocked as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        blocked = self.store.release_claim(job_id, owner, "blocked", "workflow_blocked", exc, detail={"step": exc.step, "reason_code": exc.reason_code})
                        # 原BLOCKED报告不覆盖，本次repair报告仅记append-only事件。
                        self.store.record_event(job_id, "root_source_repair_blocked", {"step": exc.step, "reason_code": exc.reason_code, "original_failure_preserved": True})
                        return self._hydrate(blocked)
                    raise
                except Exception as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        self.store.release_claim(job_id, owner, "failed", "generation_failed", redact_secrets(exc))
                    raise
                finally:
                    if original_delivery is None: self.config.pop("delivery", None)
                    else: self.config["delivery"] = original_delivery

    def resume_source_continuation(self, job_id, evidence_path, evidence_sha256, proof_path, proof_sha256, token):
        from .source_repair_runtime import JOB, WF, check_pre_source_continuation, authorized_source_continuation
        from .workflow_runtime import SourceRepairStepRunner
        if job_id != JOB or os.environ.get("CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH") != "0" or os.environ.get("AI_SELF_MEDIA_HERMES_TARGET") != "":
            raise PermissionError("fixed_internal_source_repair_no_publish_required")
        evidence, proof = check_pre_source_continuation(self.store, self.review_tokens, evidence_path, evidence_sha256, proof_path, proof_sha256)
        owner = self._worker_id()
        workflow_id = WF
        remaining = proof["remaining_budget_seconds"]
        rows = [row for row in self.store.workflow_steps(job_id) if row["id"] == 5213]
        if len(rows) != 1 or not isinstance(rows[0].get("output"), dict) or not isinstance(rows[0]["output"].get("platforms"), dict):
            raise PermissionError("actual_original_public_platform_context_required")
        platform_contexts = copy.deepcopy(rows[0]["output"]["platforms"])
        with strict_workflow_lock(self.store, owner, workflow_id, min(self.lock_timeout_seconds, remaining), self.strict_serial):
            with authorized_source_continuation(self.store, self.review_tokens, token, evidence_path, evidence_sha256, proof_path, proof_sha256, owner):
                original_delivery = self.config.get("delivery")
                try:
                    runner = SourceRepairStepRunner(self.store, workflow_id, job_id, notifier=self.notifier)
                    self.config["delivery"] = dict(original_delivery or {}, auto_stage_review_required=False)
                    return self._continue_native_generation(job_id, owner, workflow_id, runner, platform_contexts, force=False)
                except WorkflowBlocked as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        blocked = self.store.release_claim(job_id, owner, "blocked", "workflow_blocked", exc, detail={"step": exc.step, "reason_code": exc.reason_code})
                        # 原BLOCKED报告不覆盖，本次repair报告仅记append-only事件。
                        self.store.record_event(job_id, "root_source_repair_blocked", {"step": exc.step, "reason_code": exc.reason_code, "original_failure_preserved": True})
                        return self._hydrate(blocked)
                    raise
                except Exception as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        self.store.release_claim(job_id, owner, "failed", "generation_failed", redact_secrets(exc))
                    raise
                finally:
                    if original_delivery is None: self.config.pop("delivery", None)
                    else: self.config["delivery"] = original_delivery

    def resume_source_history_reobserve(self, job_id, evidence_path, evidence_sha256, proof_path, proof_sha256, token):
        from .source_history_reobserve import JOB, WF, validate, authorized
        from .workflow_runtime import SourceRepairStepRunner
        if job_id != JOB or os.environ.get("CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH") != "0" or os.environ.get("AI_SELF_MEDIA_HERMES_TARGET") != "":
            raise PermissionError("fixed_internal_source_repair_no_publish_required")
        evidence, proof = validate(self.store, self.review_tokens, evidence_path, evidence_sha256, proof_path, proof_sha256)
        owner = self._worker_id()
        workflow_id = WF
        remaining = proof["remaining_budget_seconds"]
        rows = [row for row in self.store.workflow_steps(job_id) if row["id"] == 5213]
        if len(rows) != 1 or not isinstance(rows[0].get("output"), dict) or not isinstance(rows[0]["output"].get("platforms"), dict):
            raise PermissionError("actual_original_public_platform_context_required")
        platform_contexts = copy.deepcopy(rows[0]["output"]["platforms"])
        with strict_workflow_lock(self.store, owner, workflow_id, min(self.lock_timeout_seconds, remaining), self.strict_serial):
            with authorized(self.store, self.review_tokens, token, evidence_path, evidence_sha256, proof_path, proof_sha256, owner):
                original_delivery = self.config.get("delivery")
                try:
                    runner = SourceRepairStepRunner(self.store, workflow_id, job_id, notifier=self.notifier)
                    self.config["delivery"] = dict(original_delivery or {}, auto_stage_review_required=False)
                    return self._continue_native_generation(job_id, owner, workflow_id, runner, platform_contexts, force=False)
                except WorkflowBlocked as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        blocked = self.store.release_claim(job_id, owner, "blocked", "workflow_blocked", exc, detail={"step": exc.step, "reason_code": exc.reason_code})
                        # 原BLOCKED报告不覆盖，本次repair报告仅记append-only事件。
                        self.store.record_event(job_id, "root_source_repair_blocked", {"step": exc.step, "reason_code": exc.reason_code, "original_failure_preserved": True})
                        return self._hydrate(blocked)
                    raise
                except Exception as exc:
                    current = self.store.get_job(job_id)
                    if current.get("lease_owner") == owner:
                        self.store.release_claim(job_id, owner, "failed", "generation_failed", redact_secrets(exc))
                    raise
                finally:
                    if original_delivery is None: self.config.pop("delivery", None)
                    else: self.config["delivery"] = original_delivery

    def approve(self, job_id, actor, note=""):
        job = self.store.get_job(job_id)
        if job["state"] != "review_required":
            raise ValueError(f"only review_required jobs can be approved, got: {job['state']}")
        self.store.record_approval(job_id, actor, "approved", note)
        approved = self.store.transition(job_id, {"review_required"}, "approved", "human_approved", {"actor": actor})
        self.notifier.send("approved", approved)
        return self._hydrate(approved)

    def reject(self, job_id, actor, note=""):
        job = self.store.get_job(job_id)
        if job["state"] != "review_required":
            raise ValueError(f"only review_required jobs can be rejected, got: {job['state']}")
        self.store.record_approval(job_id, actor, "rejected", note)
        rejected = self.store.transition(job_id, {"review_required"}, "rejected", "human_rejected", {"actor": actor})
        self.notifier.send("rejected", rejected)
        return self._hydrate(rejected)

    def publish(self, job_id, platform=None, expected_content_revision=None):
        job = self._hydrate(self.store.get_job(job_id))
        if platform is not None and platform not in job["platforms"]:
            raise ValueError("platform_not_in_job")
        scoped = len(job["platforms"]) > 1
        if scoped and (not platform or not expected_content_revision):
            raise PermissionError("multi_platform_publish_requires_scoped_signed_authorization")
        targets = [platform] if scoped else job["platforms"]
        compiled_run = bool((job.get("brief") or {}).get("run_contract"))
        if (compiled_run or self.config.get("workflow", {}).get("require_unified_acceptance")) and not bool(job.get("acceptance", {}).get("passed")):
            raise PermissionError("job has no passing unified workflow acceptance")
        if job["state"] == "published":
            return job
        if job["state"] not in {"approved", "partial"}:
            raise PermissionError(f"job must be approved before delivery, got: {job['state']}")
        owner = self._worker_id()
        workflow_id = f"wf_{job_id}"
        with strict_workflow_lock(self.store, owner, workflow_id, self.lock_timeout_seconds, self.strict_serial):
            if not self.store.claim(job_id, {job["state"]}, owner, 300, "publishing"):
                raise RuntimeError("job is already claimed by another worker")
            try:
                scope = None
                if scoped:
                    current = self._hydrate(self.store.get_job(job_id))
                    bundle = self.store.platform_output_bundle(job_id, platform)
                    if (not bundle["ready"] or bundle["content_revision"] != expected_content_revision
                            or bundle["copy"]["content"] != format_for_platform(current, platform)):
                        raise PermissionError("platform_output_unowned_or_stale")
                    scope = (job_id, platform, expected_content_revision)
                for target in targets:
                    payload = {"state": job["state"]}
                    if scoped:
                        payload["expected_content_revision"] = expected_content_revision
                    self.store.enqueue_delivery(job_id, target, "publish_scoped" if scoped else "publish", payload)
                processed = sum(
                    self.process_delivery_queue(owner=owner, already_locked=True, limit=1,
                                                job_id=job_id, platform=target,
                                                action="publish_scoped" if scoped else "publish",
                                                _publish_scope=scope)
                    for target in targets
                )
                hydrated = self._hydrate(self.store.get_job(job_id))
                completed = sum(1 for delivery in hydrated["deliveries"] if delivery["status"] == "published")
                pending = sum(1 for delivery in hydrated["deliveries"] if delivery["status"] == "handoff_pending")
                drafted = sum(1 for delivery in hydrated["deliveries"] if delivery["status"] == "drafted")
                successes = completed + pending + drafted
                final_state = "published" if completed == len(job["platforms"]) else "partial"
                final = self.store.release_claim(job_id, owner, final_state, "delivery_completed", detail={"success": successes, "processed": processed})
                self.notifier.send(final_state, final)
                return self._hydrate(final)
            except Exception as exc:
                current = self.store.get_job(job_id)
                if current.get("lease_owner") == owner:
                    self.store.release_claim(job_id, owner, "partial", "delivery_interrupted", redact_secrets(exc))
                raise

    def status(self, job_id):
        return self._hydrate(self.store.get_job(job_id))

    def _persist_intelligence(self, job_id, draft_meta):
        source_catalog = list(draft_meta.get("source_catalog", []))
        if source_catalog:
            self.store.save_source_items(job_id, source_catalog)
        niche_report = draft_meta.get("niche_report", {})
        accounts = []
        for handle in niche_report.get("top_accounts", []):
            accounts.append(
                {
                    "account_handle": handle,
                    "platform": next(iter(niche_report.get("platform_distribution", {}).keys()), ""),
                    "display_name": handle,
                    "sample_count": niche_report.get("account_sample_count", {}).get(handle, niche_report.get("sample_count", 0)),
                    "roles": niche_report.get("account_roles", {}).get(handle, ""),
                }
            )
        if accounts:
            self.store.save_account_snapshots(job_id, accounts)
        strategy = draft_meta.get("strategy", {})
        viral_score = draft_meta.get("viral_score", {})
        if strategy or viral_score:
            self.store.save_idea_candidates(
                job_id,
                [
                    {
                        "topic": strategy.get("topic", ""),
                        "score": viral_score.get("total_score", 0),
                        "content_form": strategy.get("content_form", ""),
                        "platforms": strategy.get("primary_platforms", []),
                        "secondary_platforms": strategy.get("secondary_platforms", []),
                        "reason": strategy.get("reason", {}),
                        "confidence": strategy.get("confidence", 0),
                        "warnings": strategy.get("warnings", []),
                        "recommendation": viral_score.get("recommendation", "test"),
                    }
                ],
            )
        clusters = list(draft_meta.get("topic_clusters", []))
        if clusters:
            self.store.save_topic_clusters(job_id, clusters)

    def stage_drafts(self, job_id, owner=None, already_locked=False):
        job = self._hydrate(self.store.get_job(job_id))
        if job["state"] not in {"review_required", "approved", "partial", "published"}:
            raise PermissionError(f"job must be reviewable before draft staging, got: {job['state']}")
        for platform in job["platforms"]:
            self.store.enqueue_delivery(job_id, platform, "stage", {"state": job["state"]})
            self.process_delivery_queue(owner=owner, already_locked=already_locked, limit=1,
                                        job_id=job_id, platform=platform, action="stage")
        return self._hydrate(self.store.get_job(job_id))

    def process_delivery_queue(self, limit=1, owner=None, already_locked=False, job_id=None, platform=None, action=None,
                               _publish_scope=None):
        if action == "publish_scoped" and (
            not _publish_scope or _publish_scope[:2] != (job_id, platform)
        ):
            raise PermissionError("publish_scope_or_approval_missing")
        processed = 0
        owner = owner or self._worker_id()
        workflow_id = "wf_delivery_queue"
        with strict_workflow_lock(self.store, owner, workflow_id, self.lock_timeout_seconds, self.strict_serial and not already_locked):
            while processed < int(limit):
                item = self.store.claim_delivery(owner, 300, job_id=job_id, platform=platform, action=action)
                if not item:
                    break
                job = self._hydrate(self.store.get_job(item["job_id"]))
                platform = item["platform"]
                queue_action = item.get("action", "publish")
                action = "publish" if queue_action == "publish_scoped" else queue_action
                scoped = len(job["platforms"]) > 1
                if action == "publish" and (
                    job["state"] not in {"approved", "partial", "publishing"}
                    or platform not in job["platforms"]
                    or (scoped and (
                        queue_action != "publish_scoped"
                        or not _publish_scope
                        or not item["payload"].get("expected_content_revision")
                        or _publish_scope != (
                            item["job_id"], platform, item["payload"]["expected_content_revision"]
                        )
                    ))
                    or (queue_action == "publish_scoped" and not scoped)
                ):
                    self.store.complete_delivery(item["id"], owner, "failed", "publish_scope_or_approval_missing")
                    raise PermissionError("publish_scope_or_approval_missing")
                owned_copy = None
                if scoped:
                    bundle = self.store.platform_output_bundle(item["job_id"], platform)
                    if (not bundle["ready"] or bundle["copy"]["content"] != format_for_platform(job, platform)
                            or (action == "publish" and bundle["content_revision"] != item["payload"].get("expected_content_revision"))):
                        self.store.complete_delivery(item["id"], owner, "failed", "platform_output_unowned_or_stale")
                        raise PermissionError("platform_output_unowned_or_stale")
                    owned_copy = bundle["copy"]["content"]
                runner = WorkflowStepRunner(self.store, f"wf_{item['job_id']}", item["job_id"], platform=platform, notifier=self.notifier)
                prior = next((delivery for delivery in job["deliveries"] if delivery["platform"] == platform), None)
                if scoped and action == "publish" and prior and prior["status"] == "submission_uncertain":
                    self.store.complete_delivery(item["id"], owner, "failed", "prior_submission_uncertain")
                    raise PermissionError("prior_submission_uncertain")
                if prior and prior["status"] in {"drafted", "published", "handoff_pending"}:
                    prior_quality = self._mandatory_release_gate(item['job_id'], platform=platform, phase='deliver')
                    prior_bundle = self.store.platform_output_bundle(item['job_id'], platform)
                    if prior_quality.get('passed') is not True or prior_bundle.get('ready') is not True:
                        self.store.record_event(item['job_id'], 'prior_delivery_current_quality_unverified', prior_quality)
                        self.store.complete_delivery(item['id'], owner, 'failed', 'prior_delivery_current_quality_unverified')
                        processed += 1
                        continue
                    expected_prior_key = self._delivery_binding_key(item['job_id'], platform,
                                                                    prior['external_id'], prior['status'])
                    if not expected_prior_key or prior.get('idempotency_key') != expected_prior_key:
                        self.store.record_event(item['job_id'], 'previous_delivery_revision_unproven',
                                                {'platform': platform, 'prior_delivery_id': prior.get('id')})
                        self.store.complete_delivery(item['id'], owner, 'failed', 'previous_delivery_revision_unproven')
                        processed += 1
                        continue
                    runner.skipped("publish_or_create_draft", "idempotent_delivery_exists", "existing delivery receipt prevents duplicate publish", required=True)
                    report = write_platform_report(self.store, self.data_dir, f"wf_{item['job_id']}", job, platform, "partial", prior)
                    runner.succeeded("generate_platform_report", report, depends_on=["publish_or_create_draft"])
                    self._send_platform_report(job, platform, report)
                    runner.succeeded("send_completion_report", {"report_path": report["path"]}, depends_on=["generate_platform_report"])
                    self.store.complete_delivery(item["id"], owner, "handoff_ready" if prior["status"] == "handoff_pending" else "completed")
                    processed += 1
                    continue
                delivery_job = dict(job)
                delivery_job["platform_payload"] = runner.run(
                    "render_platform_content",
                    lambda: owned_copy if owned_copy is not None else format_for_platform(job, platform),
                    depends_on=[],
                    require_output=True,
                )
                pre_submit_blocked = False
                try:
                    try:
                        pre_submit_health = delivery_health_decision(platform, self.config, action)
                    except Exception as exc:
                        pre_submit_blocked = True
                        runner.block("run_platform_pre_publish_gate", "delivery_health_unavailable",
                                     redact_secrets(exc))
                    pre_submit_blocked = not pre_submit_health.ok
                    result = self._deliver(platform, delivery_job, action,
                                           health_decision=pre_submit_health)
                    if result.ok and result.status in {"drafted", "published"} and not (
                        isinstance(result.external_id, str)
                        and result.external_id
                        and Path(result.external_id).is_file()
                    ):
                        gate = self._run_final_delivery_gate(job, platform, result)
                        if not gate.get("passed"):
                            result = DeliveryResult(False, "blocked", result.external_id, error="final delivery gate failed: " + ";".join(gate.get("failures", [])))
                    if result.status == "blocked":
                        self._save_delivery_result(item["job_id"], platform, result)
                        runner.block("run_platform_pre_publish_gate", "delivery_health_blocked", result.error or "delivery health blocked", {"status": result.status})
                    runner.succeeded("run_platform_pre_publish_gate", {"action": action}, depends_on=["render_platform_content"])
                    if not result.ok:
                        self._save_delivery_result(item["job_id"], platform, result)
                        runner.store.save_workflow_step(
                            runner.workflow_id,
                            runner.job_id,
                            runner.platform,
                            "publish_or_create_draft",
                            "FAILED_TERMINAL" if result.status == "submission_uncertain" else "FAILED_RETRYABLE",
                            required=True,
                            depends_on=["run_platform_pre_publish_gate"],
                            reason_code=result.status or "publish_failed",
                            message=redact_secrets(result.error or "publisher returned a failed result"),
                            output_payload={"status": result.status, "external_id_present": bool(result.external_id)},
                        )
                        report = write_platform_report(self.store, self.data_dir, f"wf_{item['job_id']}", job, platform, "partial", result.__dict__, result.error)
                        runner.succeeded("generate_platform_report", report)
                        self._send_platform_report(job, platform, report)
                        runner.succeeded("send_completion_report", {"report_path": report["path"]}, depends_on=["generate_platform_report"])
                        self.store.complete_delivery(item["id"], owner,
                                                     "failed" if scoped or result.status == "submission_uncertain" else "queued",
                                                     result.error)
                        processed += 1
                        continue
                    runner.succeeded("publish_or_create_draft", {"status": result.status, "external_id_present": bool(result.external_id)}, depends_on=["run_platform_pre_publish_gate"])
                    self._save_delivery_result(item["job_id"], platform, result)
                    runner.succeeded("verify_publish_result", {"status": result.status, "requires_postcheck": result.status in {"drafted", "handoff_pending"}}, depends_on=["publish_or_create_draft"])
                    runner.succeeded("record_publish_receipt", {"status": result.status}, depends_on=["verify_publish_result"])
                    if result.status == "handoff_pending":
                        queue_state = "handoff_ready"
                    elif result.ok or result.status in {"blocked", "drafted", "published"}:
                        queue_state = "completed"
                    else:
                        queue_state = "queued"
                    report_status = "published" if result.status == "published" else ("blocked" if result.status == "blocked" else "partial")
                    report = write_platform_report(self.store, self.data_dir, f"wf_{item['job_id']}", job, platform, report_status, result.__dict__, result.error)
                    runner.succeeded("generate_platform_report", report, depends_on=["record_publish_receipt"])
                    self._send_platform_report(job, platform, report)
                    runner.succeeded("send_completion_report", {"report_path": report["path"]}, depends_on=["generate_platform_report"])
                    self.store.complete_delivery(item["id"], owner, queue_state, result.error)
                except WorkflowBlocked as exc:
                    report = write_platform_report(self.store, self.data_dir, f"wf_{item['job_id']}", job, platform, "blocked", error=str(exc))
                    runner.succeeded("generate_platform_report", report)
                    self._send_platform_report(job, platform, report)
                    runner.succeeded("send_completion_report", {"report_path": report["path"]}, depends_on=["generate_platform_report"])
                    self.store.complete_delivery(item["id"], owner,
                                                 "blocked" if pre_submit_blocked else "completed", str(exc))
                except Exception as exc:
                    # The external call may have succeeded before local post-processing failed.
                    self.store.complete_delivery(item["id"], owner, "failed", redact_secrets(exc))
                    raise
                processed += 1
        return processed

    def process_delivery_queue_forever(self, poll_interval=3, batch_size=20):
        processed = 0
        while True:
            count = self.process_delivery_queue(limit=batch_size)
            processed += count
            time.sleep(max(1, int(poll_interval)))

    def process_generation_queue(self, limit=100, include_failed=False):
        processed = 0
        states = {"created"}
        if include_failed:
            states.update({"failed", "blocked", "rejected"})
        for state in states:
            jobs = self.store.automatic_jobs(limit=limit, state=state)
            for job in jobs:
                self.run(job["id"], force=(state != "created"))
                processed += 1
                if processed >= limit:
                    return processed
        return processed

    def process_generation_queue_forever(self, poll_interval=3, batch_size=20, include_failed=False):
        processed = 0
        while True:
            count = self.process_generation_queue(batch_size, include_failed)
            processed += count
            time.sleep(max(1, int(poll_interval)))

    def _hydrate(self, job):
        result = dict(job)
        result["artifacts"] = self.store.artifacts(job["id"])
        result["deliveries"] = self.store.deliveries(job["id"])
        return result

    def _generate_scoped_drafts(self,job_id,topic,briefs):
        from .target_adaptation import generate_normal_twitter_draft
        variants={platform:(generate_normal_twitter_draft(self,job_id,topic,platform,scoped)
            if str(platform).casefold() in {'twitter','x'} else self.generator.generate(topic,scoped,stage_job_id=job_id))
            for platform,scoped in briefs.items()}
        draft=copy.deepcopy(next(iter(variants.values())))
        if len(variants)>1:draft.setdefault('draft_meta',{})['platform_drafts']=variants
        return draft

    def _validate_scoped_narrations(self,job_id,draft,briefs,runner):
        variants=(draft.get('draft_meta') or {}).get('platform_drafts') or {}
        ledgers=[];results={}
        for platform,brief in briefs.items():
            variant=variants.get(platform) or draft
            text=str(variant.get('title') or '')+'\n'+str(variant.get('body') or '')+'\n'+_draft_script_text(variant)
            ledger=list(brief.get('claim_ledger') or [])
            claim=validate_claims(text,ledger)
            if brief.get('run_contract') and not claim.get('passed'):
                # Same rule as the main claim gate: drop unsupported sentences, keep only a clean, non-trivial body.
                # r59: a Zhihu title was one numeric sentence; falling back to it re-failed the gate.
                cleaned_title=(sanitize_unsupported_claims(variant.get('title') or '',claim.get('findings'))
                               or strip_numeric_claims(variant.get('title') or '') or str(variant.get('title') or ''))
                cleaned_body=sanitize_unsupported_claims(variant.get('body') or '',claim.get('findings'))
                cleaned_text=cleaned_title+'\n'+cleaned_body+'\n'+_draft_script_text(variant)
                cleaned_claim=validate_claims(cleaned_text,ledger)
                if len(cleaned_body)>=80 and cleaned_claim.get('passed'):
                    variant['title'],variant['body'],text=cleaned_title,cleaned_body,cleaned_text
                    variant.setdefault('draft_meta',{})['claim_sanitization']={'removed_count':len([row for row in claim.get('findings') or [] if not row.get('covered')]),
                        'original_gate':claim,'passed':True}
                    claim=cleaned_claim
            risk=self.risk.evaluate(text)
            compliance=self.compliance.evaluate(text,brief,[platform])
            results[platform]={'claims':claim,'geo':geo_check(text),'risk':risk,'compliance':compliance,
                'script_sha256':hashlib.sha256(_draft_script_text(variant).encode()).hexdigest()}
            if brief.get('run_contract') and not claim.get('passed'):
                runner.block('validate_factual_claims','factual_claim_evidence_missing',
                    'platform draft or narration lacks factual evidence',{'platform':platform,**claim},depends_on=['generate_content'])
            codes={str(row.get('code') or '') for row in compliance.get('findings') or []}
            if risk.get('level')=='block' or (brief.get('run_contract') and codes & {'numeric_claim_without_source','attribution_without_source'}):
                runner.block('run_safety_gate','platform_narration_rejected',
                    'platform draft or narration failed native safety/compliance',{'platform':platform,'risk':risk,'compliance':compliance},depends_on=['generate_content'])
            for row in ledger:
                if row not in ledgers:ledgers.append(row)
        draft.setdefault('draft_meta',{})['claim_ledger']=ledgers
        self.store.record_event(job_id,'native_platform_narrations_validated',results)

    @staticmethod
    def _freeze_pet_video_beats(draft,briefs):
        """Fix the pet narration to the 8 rendered beats before the factual/safety receipt covers it."""
        if 'douyin_pet' not in briefs:return
        variant=((draft.get('draft_meta') or {}).get('platform_drafts') or {}).get('douyin_pet') or draft
        meta=variant.setdefault('draft_meta',{})
        if not (meta.get('video_toolchain_plan') or {}).get('required'):return
        script=MediaBridge.compile_video_script(variant)['script']
        meta['video_script']=meta['narration_script']=script

    def _bind_video_asset_semantics(self,job_id,draft,briefs,owner):
        from .video_asset_semantics import bind_requirements,requirement_tag
        variants=(draft.get('draft_meta') or {}).get('platform_drafts') or {}
        for platform,brief in briefs.items():
            if brief.get('lane')!='real_world_ai_implementation' and platform!='douyin_pet':continue
            variant=variants.get(platform) or draft;meta=variant.get('draft_meta') or {}
            plan=meta.get('video_toolchain_plan') or {}
            if not plan.get('required') or not meta.get('video_script'):continue
            requirements=bind_requirements(self.store,job_id,brief,meta['video_script'],plan['visual_contract'],platform,owner)
            scenes=[]
            for scene,requirement in zip(plan['visual_contract'],requirements):
                scenes.append(dict(scene,semantic_requirement=requirement,required_semantic_tag=requirement_tag(requirement)))
            plan=dict(plan,visual_contract=scenes,video_asset_requirements=requirements,
                asset_semantic_contract=[{**{key:req['intent'][key] for key in
                    ('beat_id','claim','asset_role','semantic_subject','content_match_reason')},'verification_status':'pending_validation'} for req in requirements])
            meta['video_toolchain_plan']=plan

    def _bind_platform_source_inputs(self,job_id,brief,platform,platform_context,owner):
        """Bind the same native Store job, independently for each platform."""
        brief["platform"] = platform
        if platform_context.get("viral_breakdown"):
            brief["viral_breakdown"] = platform_context["viral_breakdown"]
        compiled = platform_context.get("strategy", {}).get("compiled")
        if isinstance(compiled, dict):
            research_events=[row for row in self.store.events(job_id) if row['event']=='native_video_research_snapshot_bound']
            if research_events:
                from .video_preflight_inputs import read_bound_file
                research_ref=json.loads(research_events[-1]['detail_json'])
                read_bound_file(self.store,job_id,research_ref,'native_video_research_snapshot_bound')
                brief['content_blueprint']=dict(brief.get('content_blueprint') or {},native_video_research_ref=research_ref)
            brief["strategy_compiled"] = compiled
            brief["strategy"] = compiled
            contract = brief.get("run_contract")
            if isinstance(contract,dict) and contract.get('platform')!=platform:
                raise ValueError('source_platform_contract_mismatch:'+platform)
            if not isinstance(contract, dict):
                contract = build_run_contract(platform)
                brief["run_contract"] = contract
            if isinstance(contract, dict):
                from .run_contract import bound_stage_payload
                from .content_quality_reference import load_content_quality_reference_pack

                quality_reference = platform_context.get("content_quality_reference_pack")
                if not isinstance(quality_reference, dict) or quality_reference.get("loaded") is not True:
                    quality_reference = load_content_quality_reference_pack(
                        platform,
                        content_form=str((brief.get("content_blueprint") or {}).get("content_form") or brief.get("content_form") or ""),
                    )
                brief["bounded_model_input"] = bind_stage_payload(
                    self.store, job_id, contract,
                    "generate",
                    {
                        "content_blueprint": brief.get("content_blueprint") or {},
                        "claim_ledger": list(brief.get("claim_ledger") or []),
                        "audio_plan": brief.get("audio_plan") or {},
                        "tool_selection_plan": dict(brief.get("tool_selection_plan") or {}),
                        "strategy": compiled,
                        "positioning": _bounded_ai_positioning(platform_context.get("positioning")),
                        "platform_intelligence_constraints": platform_context.get("platform_intelligence_constraints") or {},
                        "external_discovery_candidates": platform_context.get("external_discovery_candidates") or {},
                        "content_quality_reference_pack": quality_reference,
                        "runtime_capabilities": platform_context.get("runtime_capabilities") or {},
                        "viral_breakdown": platform_context.get("viral_breakdown") or {},
                        "hot_work_parameter_pack": platform_context.get("hot_work_parameter_pack") or {},
                        "same_lane_intelligence": platform_context.get("same_lane_intelligence") or {},
                        "wechat_blowup_intelligence": platform_context.get("wechat_blowup_intelligence") or {},
                    "owned_learning_decision": self._bounded_owned_decision(brief),
                        "owned_learning_treatment": dict((brief or {}).get("owned_learning_treatment") or {"arm": "control", "reason": "not_configured"}),
                    },
                   lease_owner=owner,
                    force_reference=bool((brief.get("content_blueprint") or {}).get("video_source_planning")),
                )
        return brief

    def _enrich_brief(self, job, hygiene=None):
        brief = dict(job.get("brief", {}))
        platforms = list(job.get("platforms", []))
        brief["platforms"] = list(platforms)
        if len(platforms) == 1:
            brief["platform"] = platforms[0]
        else:
            brief.pop("platform", None)
        topic = job.get("topic", "")
        canonical_store = Path(__file__).resolve().parents[1] / "data" / "state.db"
        canonical_active = self.store.path.resolve() == canonical_store.resolve()
        legacy = {"platform_history": self.store.historical_performance(platforms, "") if canonical_active else {},
                  "topic_history": self.store.historical_performance(platforms, topic) if canonical_active else {},
                  "incoming_historical_feedback": brief.get("historical_feedback"),
                  "incoming_cluster_memory": brief.get("cluster_memory")}
        brief["legacy_feedback_reference"] = {"status": "legacy_unverified_reference_only", "data": legacy}
        feedback = {"schema": "owned_feedback_v1", "status": "unavailable", "scope": {},
                    "sample_count": 0, "observation_ids": [], "observation_refs": [], "rows": [],
                    "reason": "verified_account_window_scope_missing"}
        account_id = str(brief.get("account_id") or "").strip()
        alias = str(brief.get("internal_account_alias") or brief.get("account") or "").strip()
        hours = brief.get("review_window_hours")
        if not canonical_active:
            feedback["reason"] = "active_store_not_canonical_owned_metrics"
        elif len(platforms) == 1 and account_id and alias and hours in {1, 24, 72, 168}:
            platform = "twitter" if platforms[0] == "x" else platforms[0]
            actual = self.store.account_window_metrics(platform, account_id, alias, hours)
            rows = actual.get("rows") or []
            if actual.get("status") == "verified" and rows:
                feedback = {"schema": "owned_feedback_v1", "status": "verified",
                    "scope": {"platform": platform, "account_id": account_id,
                        "internal_account_alias": alias, "window_hours": hours},
                    "sample_count": len(rows), "observation_ids": [row["id"] for row in rows],
                    "observation_refs": [{"id": row["id"], "raw_ref": row["source"]["raw_ref"]} for row in rows],
                    "rows": rows, "reason": ""}
        # Always replace incoming self-reported feedback; never inherit a fake available flag.
        brief["historical_feedback"] = feedback
        brief["platform_historical_feedback"] = feedback
        brief["topic_historical_feedback"] = feedback
        brief["cluster_memory"] = []
        if hygiene:
            brief["content_hygiene"] = hygiene
        return brief

    def _content_hygiene(self, job):
        if not self.content_hygiene_cfg.get("enabled", True):
            return {"status": "pass", "recommended_action": "proceed", "best_score": 0.0, "matches": []}
        candidates = self.store.content_candidates(
            limit=int(self.content_hygiene_cfg.get("candidate_limit", 200)),
            exclude_job_id=job["id"],
        )
        family = set()
        if (job.get('brief')or{}).get('caption_revision_ref'):
            from .native_stage_resume import caption_revision_ancestor
            family=caption_revision_ancestor(self.store,job)
            candidates=[r for r in candidates if r.get('id')not in family]
        if (job.get("brief") or {}).get("quality_revision"):
            reference = job['brief']['quality_revision']
            if reference.get('parent_original_knowledge_ref') or job['brief'].get('original_knowledge_ref'):
                from .original_knowledge import verified_revision_family
            else:
                from .quality_revision import verified_revision_family
            family = verified_revision_family(self.store, job)
            candidates = [row for row in candidates if row.get("id") not in family]
        hygiene = audit_topic(job.get("topic", ""), candidates, self.content_hygiene_cfg)
        self.store.record_event(job["id"], "content_hygiene_checked",
            {"content_hygiene": hygiene, "verified_revision_ancestors": sorted(family)})
        return hygiene

    def _mandatory_release_gate(self, job_id, *, platform=None, phase="release"):
        from .mandatory_release_gate import mandatory_release_gate
        job = self.store.get_job(job_id)
        targets = [platform] if platform is not None else list(job.get("platforms") or [])
        if not targets or any(target not in job.get("platforms", []) for target in targets):
            return {"passed": False, "failures": ["current_release_platform_missing"]}
        results = {target: mandatory_release_gate(self.store, self.data_dir, job_id, target, phase=phase)
                   for target in targets}
        return {"passed": all(result.get("passed") is True for result in results.values()),
                "phase": phase, "results": results}

    def internal_handoff(self, job_id, platform):
        """Prepare a current qualified local package; this is never delivery ACK."""
        if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
            return DeliveryResult(False, 'blocked', error='internal_handoff_no_publication_required')
        import re
        if (not re.fullmatch('[a-f0-9]{16,32}', str(job_id))
                or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', str(platform))):
            return DeliveryResult(False, 'blocked', error='internal_handoff_path_identity_invalid')
        owner = self._worker_id()
        with strict_workflow_lock(self.store, owner, 'wf_internal_handoff_' + job_id,
                                  min(self.lock_timeout_seconds, 300), True):
            job = self.store.get_job(job_id)
            if platform not in (job.get('platforms') or []):
                return DeliveryResult(False, 'blocked', error='internal_handoff_platform_not_current')
            if (job.get('state') not in {'review_required', 'approved', 'partial', 'published'}
                    or job.get('lease_owner') or job.get('lease_expires_at')):
                return DeliveryResult(False, 'blocked', error='internal_handoff_current_job_not_idle_reviewable')
            from .task_source_inputs import project_task_source_job
            job=dict(job,platform_payload=format_for_platform(project_task_source_job(job,platform),platform))
            return self._deliver(platform, job, action='internal_handoff')

    def revise_rendered_quality(self, proof_path, proof_sha256):
        from .native_quality_resume import run_rendered_quality_revision
        return run_rendered_quality_revision(self, proof_path, proof_sha256)

    def _deliver(self, platform, job, action="publish", health_decision=None):
        mandatory = self._mandatory_release_gate(job['id'], platform=platform, phase='deliver')
        if mandatory.get('passed') is not True:
            self.store.record_event(job['id'], 'mandatory_delivery_quality_blocked', mandatory)
            return DeliveryResult(False, 'blocked', error='mandatory_final_quality_not_qualified')
        multiple_targets=len(job.get('platforms') or [])>1
        from .task_source_inputs import project_task_source_job
        job=project_task_source_job(job,platform)
        bundle = self.store.platform_output_bundle(job['id'], platform)
        if bundle.get('ready') is not True:
            return DeliveryResult(False, 'blocked', error='qualified_platform_outputs_missing_or_changed')
        original_artifacts = {row['id']: row for row in self.store.artifacts(job['id'])}
        current_artifacts = []
        for row in bundle.get('artifacts') or []:
            actual = original_artifacts.get(row.get('artifact_id'))
            if not actual or actual['path'] != row['path'] or actual['checksum'] != row['checksum']:
                return DeliveryResult(False, 'blocked', error='qualified_delivery_artifact_changed')
            current_artifacts.append(actual)
        job['artifacts'] = current_artifacts
        if job.get('platform_payload') != (bundle.get('copy') or {}).get('content'):
            return DeliveryResult(False, 'blocked', error='qualified_delivery_copy_changed')
        # Validate before even constructing a publisher: a file preview,
        # handoff and a platform draft have the same content obligations.
        quality = self._generation_platform_quality_gate(job['id'], job, [platform], phase='rendered')
        if not isinstance(quality,dict) or not quality.get('passed'):
            return DeliveryResult(False, 'blocked', error='mandatory_delivery_content_policy_failed')
        if action == 'internal_handoff':
            if os.environ.get('CONTENT_PLATFORM_ENABLE_LIVE_PUBLISH') != '0':
                return DeliveryResult(False, 'blocked', error='internal_handoff_no_publication_required')
            from .publishers import ManualHandoffPublisher, _bind_adapter_quality_source
            revision = str(bundle.get('content_revision') or '')
            if not revision:
                return DeliveryResult(False, 'blocked', error='internal_handoff_content_revision_required')
            binding = {'job_id': job['id'], 'platform': platform, 'content_revision': revision,
                'draft_version_id': bundle.get('draft_version_id'),
                'copy_sha256': hashlib.sha256(json.dumps(bundle['copy']['content'], ensure_ascii=False,
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                'artifacts': [{'artifact_id': r['artifact_id'], 'path': r['path'], 'checksum': r['checksum']}
                    for r in bundle.get('artifacts') or []]}
            key = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            directory = self.data_dir / 'internal-handoff' / job['id'] / key
            if any(p.is_symlink() for p in (directory, *directory.parents)):
                return DeliveryResult(False, 'blocked', error='internal_handoff_symlink_forbidden')
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            job['_internal_handoff_binding'] = binding
            adapter = ManualHandoffPublisher(directory, reason='qualified internal handoff awaiting native delivery ACK', internal_only=True)
            _bind_adapter_quality_source(adapter, self.store, self.data_dir)
            return adapter.deliver(job, platform)
        decision = health_decision if health_decision is not None else delivery_health_decision(platform, self.config, action)
        if not decision.ok:
            return DeliveryResult(False, "blocked", error=decision.error())
        cfg = self.config.get("delivery", {})
        max_attempts = 1 if multiple_targets and action == "publish" else max(1, int(cfg.get("max_attempts", 1)))
        backoff = float(cfg.get("backoff_seconds", 0.2))
        result = DeliveryResult(False, "failed", error="delivery not attempted")
        for attempt in range(max_attempts):
            try:
                result = build_publisher(platform, self.config, self.data_dir, store=self.store).deliver(job, platform)
                if platform == 'wechat' and result.ok and result.status in {'drafted','handoff_pending'}:
                    from .quality_gates import measure_wechat_local_assets, read_wechat_delivery_evidence
                    packet = self._generation_platform_packet(job['id'],job,job.get('platforms') or ['wechat'],'wechat')
                    checked = validate_wechat_auto_packet(packet,phase='delivery',
                        native_task_scope=self._wechat_native_task_scope(job['id']),
                        local_evidence=measure_wechat_local_assets(self.store,self.data_dir,job['id'],job),
                        delivery_evidence=read_wechat_delivery_evidence(self.data_dir,job['id'],result.external_id))
                    if not checked['passed']:
                        return DeliveryResult(False,'submission_uncertain',result.external_id,error='wechat_delivery_quality_or_postcheck_failed')
            except Exception as exc:
                return DeliveryResult(False, "submission_uncertain", error=redact_secrets(exc))
            if not result.ok and result.status == "failed":
                return DeliveryResult(False, "submission_uncertain", result.external_id, error=result.error)
            if not result.ok and multiple_targets and action == "publish" and result.status != "blocked":
                return DeliveryResult(False, "submission_uncertain", result.external_id, error=result.error)
            if result.ok or result.status in {"blocked", "submission_uncertain"}:
                return result
            if attempt + 1 < max_attempts and backoff:
                time.sleep(backoff * (2**attempt))
        return result

    def _render_wechat_scoped(self,job_id,draft,runner):
        from .quality_gates import render_wechat_local_article,render_wechat_knowledge_cards
        from .task_source_inputs import project_task_source_job
        job=self.store.get_job(job_id)
        scoped=project_task_source_job(dict(job,title=draft['title'],body=draft['body'],draft_meta=draft['draft_meta']),'wechat')
        runner.run('render_wechat_knowledge_cards',
            lambda:render_wechat_knowledge_cards(self.store,self.data_dir,job_id,scoped,self.config),
            depends_on=['validate_image_requirements'],require_output=True)
        runner.run('render_wechat_local_article',
            lambda:render_wechat_local_article(self.store,self.data_dir,job_id,scoped,self.config),
            depends_on=['validate_image_requirements'],require_output=True)
        mapping_path=Path(self.data_dir)/'artifacts'/str(job_id)/'section_image_map.json'
        if not mapping_path.is_file():mapping_path=mapping_path.parent/'cards/section_image_map.json'
        self._register_auxiliary_artifact(job_id,'section_image_map',mapping_path,rewritten=True)
        self._write_article_artifact_manifest(job_id,scoped)
        variants=(draft.get('draft_meta') or {}).get('platform_drafts')
        if isinstance(variants,dict):
            variants['wechat']={field:copy.deepcopy(scoped[field]) for field in ('title','body','draft_meta')}
        else:draft['draft_meta']=scoped['draft_meta']

    def _write_article_artifact_manifest(self, job_id, draft):
        """Bind the generated packet, cover, and section images to one readable manifest."""
        meta = draft.get("draft_meta") or {}
        platforms = (meta.get("strategy") or {}).get("primary_platforms") or []
        if not any(str(item).casefold() in {"zhihu", "juejin", "wechat", "xiaohongshu", "rednote"} for item in platforms):
            return None
        output_dir = Path(self.data_dir) / "artifacts" / str(job_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        packet_hash = hashlib.sha256(json.dumps({"title": draft.get("title"), "body": draft.get("body")}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        cover = meta.get("cover_design") or {}
        mappings = meta.get("section_image_map") or []
        artifact_rows = []
        provenance_path = output_dir / "asset_provenance.json"
        provenance = {}
        if provenance_path.is_file():
            try:
                provenance = {str(item.get("path")): item for item in json.loads(provenance_path.read_text(encoding="utf-8")).get("assets", []) if isinstance(item, dict)}
            except (OSError, ValueError):
                provenance = {}
        for row in self.store.artifacts(job_id):
            if row.get("kind") not in {"cover", "image"}:
                continue
            evidence = provenance.get(str(row.get("path")), {})
            artifact_rows.append({
                "kind": row.get("kind"), "path": row.get("path"),
                "source": evidence.get("source_url", ""), "rights": evidence.get("license", ""),
                "asset_hash": row.get("checksum", ""),
                "semantic_evidence": {"score": evidence.get("semantic_match_score", 0), "reason": evidence.get("match_reason", "")},
            })
        if not mappings:
            mapping_path = output_dir / "section_image_map.json"
            if mapping_path.is_file():
                try:
                    mappings = json.loads(mapping_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    mappings = []
        cover_record = next((row for row in artifact_rows if row["kind"] == "cover"), None)
        if cover_record:
            cover = {**cover, **{key: cover_record[key] for key in ("source", "rights", "asset_hash", "semantic_evidence")}}
        manifest = {
            "version": "article_artifact_manifest_v1",
            "job_id": str(job_id),
            "draft_artifact": {"title": draft.get("title", ""), "packet_hash": packet_hash},
            "platforms": [str(item) for item in platforms],
            "cover": {key: cover.get(key) for key in ("source", "rights", "asset_hash", "semantic_match", "semantic_match_score", "visual_subject")},
            "section_image_map": mappings,
            "artifacts": artifact_rows,
            "binding": {"packet_hash": packet_hash, "cover_hash": cover.get("asset_hash", ""), "section_hashes": [item.get("asset_hash", "") for item in mappings if isinstance(item, dict)]},
        }
        path = output_dir / "article_artifact_manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        readback = json.loads(path.read_text(encoding="utf-8"))
        if readback.get("binding", {}).get("packet_hash") != packet_hash:
            raise RuntimeError("article artifact manifest readback mismatch")
        self._register_auxiliary_artifact(job_id, "article_artifact_manifest", path)
        return str(path)

    def _run_final_delivery_gate(self, job, platform, result):
        """Run the fail-closed evidence gate before recording delivery success."""
        import sys
        gate_root = Path(self.data_dir) / "artifacts" / str(job["id"])
        gate_root.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for item in job.get("artifacts", []):
            if not isinstance(item, dict):
                continue
            path = Path(str(item.get("path") or ""))
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append({
                "path": str(path), "role": item.get("kind") or item.get("role") or "asset",
                "source": item.get("source") or item.get("url") or "pipeline_artifact",
                "rights": item.get("rights") or item.get("license") or "",
                "match_reason": item.get("match_reason") or item.get("purpose") or "",
                "semantic_match": item.get("semantic_match") is True,
                "semantic_evidence": item.get("semantic_evidence") or {},
                "sha256": digest,
            })
        package_id = str((job.get("content_package_id") or f"cp_{platform}_{job['id']}"))
        assets_path = gate_root / f"{platform}_final_assets.json"
        assets_path.write_text(json.dumps({"job_id": str(job["id"]), "platform": platform, "content_package_id": package_id, "assets": artifacts}, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path = gate_root / f"{platform}_final.html"
        image_tags = "".join(f'<img data-src="{a["path"]}" alt="{a["role"]}">' for a in artifacts if a["role"] in {"cover", "image", "illustration", "visual"})
        html_path.write_text(f"<html><body>{image_tags}<p>{job.get('body', '')}</p></body></html>", encoding="utf-8")
        evidence_path = gate_root / f"{platform}_delivery_evidence.json"
        evidence_path.write_text(json.dumps({"job_id": str(job["id"]), "platform": platform, "content_package_id": package_id, "external_id": result.external_id}, ensure_ascii=False, indent=2), encoding="utf-8")
        state_path = gate_root / f"{platform}_publish_state.json"
        state_path.write_text(json.dumps({"job_id": str(job["id"]), "platform": platform, "content_package_id": package_id, "status": result.status, "publish_verified": bool(result.external_id), "evidence": str(evidence_path)}, ensure_ascii=False, indent=2), encoding="utf-8")
        scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from final_delivery_gate import run_gate
        return run_gate(gate_root, platform=platform, job_id=str(job["id"]), content_package_id=package_id, html=html_path, assets=assets_path, state=state_path)

    def _delivery_binding_key(self, job_id, platform, external_id, status):
        mandatory = self._mandatory_release_gate(job_id, platform=platform, phase='deliver')
        bundle = self.store.platform_output_bundle(job_id, platform)
        if mandatory.get('passed') is not True or bundle.get('ready') is not True:
            return ''
        context_sha = (mandatory.get('results', {}).get(platform) or {}).get('context_sha256')
        if not context_sha or not bundle.get('content_revision'):
            return ''
        payload = {'version': 'mandatory_delivery_binding_v1', 'job_id': job_id, 'platform': platform,
                   'context_sha256': context_sha, 'content_revision': bundle['content_revision'],
                   'external_id': external_id, 'status': status}
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()

    def _save_delivery_result(self, job_id, platform, result):
        key = self._delivery_binding_key(job_id, platform, result.external_id, result.status)
        self.store.save_delivery(job_id, platform, result.status, result.external_id, redact_secrets(result.error), key)
        if self.config.get("feature_flags", {}).get("content_package_v1"):
            packages = self.store.content_packages(job_id=job_id, platform=platform, limit=1)
            if packages:
                package_id = packages[0]["content_package_id"]
                receipt_status = "created" if result.status in {"drafted", "handoff_pending"} else result.status
                self.store.save_publish_receipt(
                    package_id,
                    platform,
                    PublishReceipt(
                        status=receipt_status,
                        verification_level="postcheck_required",
                        platform_content_id=result.external_id,
                        job_id=str(job_id),
                        platform=platform,
                        content_package_id=package_id,
                        content_hash=hashlib.sha256(f"{job_id}:{platform}".encode()).hexdigest(),
                        postcheck_verified=False,
                        live_publish=False,
                    ),
                    job_id=job_id,
                )
                if result.status in {"handoff_pending", "drafted"}:
                    register_review_tasks(self.store, package_id, platform, job_id=job_id)

    def _send_platform_report(self, job, platform, report):
        payload = dict(job)
        payload["state"] = report.get("summary", {}).get("status", job.get("state", ""))
        payload["report_path"] = report.get("path", "")
        payload["title"] = f"{job.get('title') or job.get('topic', '')} [{platform}]"
        self.notifier.send("platform_report", payload)

    def _validate_draft_structure(self, draft):
        if not isinstance(draft, dict):
            raise RuntimeError("content generator did not return a structured draft")
        if not str(draft.get("title", "")).strip():
            raise RuntimeError("content generator produced no title")
        if not str(draft.get("body", "")).strip():
            raise RuntimeError("content generator produced no body")

    def _humanize_draft(self, job_id, draft):
        from .humanizer import _hermes_llm_call, humanize_text
        # The 60 s helper default is shorter than one Hermes call; use the generator's budget.
        timeout=int((self.config.get('generator') or {}).get('timeout') or 600)
        llm_call=lambda prompt,system:_hermes_llm_call(prompt,system,timeout=timeout)
        variants=[draft]+list((draft.get('draft_meta',{}).get('platform_drafts') or {}).values())
        visited=set()
        for item in variants:
            if id(item) in visited:continue
            visited.add(id(item))
            style_hint=item.get('draft_meta',{}).get('strategy',{}).get('tone','')
            result=humanize_text(item['title'],item['body'],style_hint=style_hint,llm_call=llm_call)
            if result.get('ok') is not True or result.get('error'):
                # Owner-delegated policy 10-29: a failed rewrite call (~2/9 runs: timeout, unparseable reply)
                # keeps the original draft; the later quality gates (authenticity, burstiness...) judge it. No retry.
                self.store.record_event(job_id,'humanize_failed',{'error':str(result.get('error') or 'invalid_response'),
                    'kept_original':True})
                continue
            before_chars=len(re.sub(r'\s+','',str(item.get('body') or '')))
            content_form=str(((item.get('draft_meta') or {}).get('strategy') or {}).get('content_form') or '')
            after_chars=len(re.sub(r'\s+','',str(result['body'])))
            # A rewrite that drops most of an article (r30: 2554 -> 811) loses content, not just AI tone;
            # keep the original and let the later gates judge it.
            if 'article' in content_form and (after_chars<before_chars*0.7 or (before_chars>=1200>after_chars)):
                self.store.record_event(job_id,'humanize_rejected_short',{'body_chars':{'before':before_chars,'after':after_chars}})
                continue
            # Video narration is gated on short paragraphs (G2); r58: the rewrite merged a pet script into long lines.
            platforms={str(p).casefold() for p in ((item.get('draft_meta') or {}).get('strategy') or {}).get('primary_platforms') or []}
            if platforms&SHORT_VIDEO_PLATFORMS and geo_check(str(item.get('body') or ''))['checks'].get('short_paragraphs') \
                    and not geo_check(str(result['body']))['checks'].get('short_paragraphs'):
                self.store.record_event(job_id,'humanize_rejected_structure',{'body_chars':{'before':before_chars,'after':after_chars}})
                continue
            item['title']=result['title'];item['body']=result['body']
            # The rewrite has no length bound; apply the generator's article fit again.
            item['body']=DraftGenerator._fit_article_length(item['body'],{'strategy':{'content_form':content_form}})
            self._validate_draft_structure(item)
            if result.get('patterns_detected'):
                self.store.record_event(job_id,'humanized',{'patterns_found':list(result['patterns_detected']),'score':result['score'],
                    'body_chars':{'before':before_chars,'after':len(re.sub(r'\s+','',item['body']))},
                    'revalidation_required':True,'output_sha256':hashlib.sha256((item['title']+'\n'+item['body']).encode()).hexdigest()})

    def _media_generation_job(self,job_id,draft=None):
        """Fresh reviewed content, without publishing or mutating the leased Store row."""
        job=copy.deepcopy(self.store.get_job(job_id))
        if draft is not None:
            for field in ('title','body','draft_meta','prompt_version'):
                if field in draft:job[field]=copy.deepcopy(draft[field])
        return job

    def _register_auxiliary_artifact(self, job_id, kind, path, *, rewritten=False):
        root=Path(self.data_dir)/'artifacts'/str(job_id)
        file=Path(path)
        if not str(path) or file.is_symlink() or any(parent.is_symlink() for parent in file.parents):
            raise RuntimeError('auxiliary_artifact_path_untrusted')
        if not file.is_file() or not file.resolve().is_relative_to(root.resolve()):
            raise RuntimeError('auxiliary_artifact_missing_or_outside_job')
        checksum=sha256_file(file)
        existing=[row for row in self.store.artifacts(job_id) if row['kind']==kind and row['path']==str(file)]
        if existing and existing[0]['checksum']!=checksum:
            if not rewritten or kind!='section_image_map':raise RuntimeError('auxiliary_artifact_changed')
            with self.store.connect() as conn:
                from datetime import datetime,timezone
                conn.execute('BEGIN IMMEDIATE')
                job=conn.execute('SELECT state,lease_owner,lease_expires_at FROM jobs WHERE id=?',(job_id,)).fetchone()
                if not job or job['state']!='generating' or job['lease_owner']!=self._worker_id() or not job['lease_expires_at'] or job['lease_expires_at']<=datetime.now(timezone.utc).isoformat(timespec='seconds'):
                    raise RuntimeError('auxiliary_artifact_generation_lease_required')
                if conn.execute('SELECT 1 FROM approvals WHERE job_id=? LIMIT 1',(job_id,)).fetchone() or conn.execute('SELECT 1 FROM platform_outputs WHERE job_id=? LIMIT 1',(job_id,)).fetchone():
                    raise RuntimeError('auxiliary_artifact_already_bound')
                conn.execute('UPDATE artifacts SET checksum=? WHERE id=? AND job_id=?',
                             (checksum,existing[0]['id'],job_id))
        else:self.store.add_artifact(job_id,kind,file,checksum)
        return checksum

    def _generate_optional_media(self, job_id, kind, runner, depends_on, step_name=None, *, draft=None):
        cfg = dict(self.config.get("media", {}).get(kind, {}) or {})
        step = step_name or f"generate_{kind}"
        job = self._media_generation_job(job_id,draft)
        if kind in {'wechat_format','image'} and 'wechat' in job.get('platforms',[]):
            from .task_source_inputs import project_task_source_job
            job=project_task_source_job(job,'wechat')
        strict_article = kind == "image" and self._strict_article_job(job_id)
        if strict_article:
            cfg.update({"enabled": True, "required": True, "min_count": max(4, int(cfg.get("min_count", 0) or 0))})
        required = self._media_required(kind, cfg, job)
        if kind == "image" and cfg.get("enabled", False) and set(str(item).casefold() for item in job.get("platforms", [])) & SHORT_VIDEO_PLATFORMS:
            # Video scenes cannot safely fall back to stale/empty visual assets.
            required = True
        if not cfg.get("enabled", False):
            if required:
                runner.block(step, f"{kind}_required_but_not_enabled", f"{kind} generation is required by platform strategy but not enabled", depends_on=depends_on)
            runner.skipped(step, f"{kind}_not_enabled", f"{kind} generation is not enabled by config", required=False, depends_on=depends_on)
            return None
        try:
            previous_media_cfg = self.media.config.get(kind)
            if strict_article:
                self.media.config[kind] = dict(cfg)
            try:
                artifact = runner.run(step, lambda: self.media.generate(kind,copy.deepcopy(job)), required=required, depends_on=depends_on)
            finally:
                if strict_article:
                    if previous_media_cfg is None:
                        self.media.config.pop(kind, None)
                    else:
                        self.media.config[kind] = previous_media_cfg
        except Exception:
            if required:
                raise
            self.store.record_event(job_id, "media_failed", {"kind": kind, "error": "optional media generation failed"})
            return None
        if not artifact:
            if required:
                runner.block(step, f"{kind}_missing_required_output", f"{kind} generation produced no artifact", depends_on=depends_on)
            return None
        if kind == "illustration":
            for art in artifact.get("artifacts", []):
                self._register_auxiliary_artifact(job_id, "illustration", art.get("prompt_path", ""))
            return artifact
        if kind == "wechat_format":
            self._register_auxiliary_artifact(job_id, "wechat_format", artifact.get("html_path", ""))
            self.store.record_event(job_id, "wechat_formatted", {"theme": artifact.get("theme", ""), "validated": artifact.get("validated", False)})
            return artifact
        if kind == "magazine_format":
            self._register_auxiliary_artifact(job_id, "magazine_format", artifact.get("html_path", ""))
            self.store.record_event(job_id, "magazine_formatted", {"style": artifact.get("style", "")})
            return artifact
        if kind == "image" and artifact.get("images"):
            auxiliary=artifact.get('auxiliary_artifacts') or []
            if auxiliary:
                if {x.get('kind')for x in auxiliary}!={'rights','render_manifest'} or len(auxiliary)!=2:
                    raise RuntimeError('current_image_text_auxiliary_set_invalid')
                for row in auxiliary:
                    actual=self._register_auxiliary_artifact(job_id,row['kind'],row.get('path'))
                    if actual!=row.get('checksum'):raise RuntimeError('current_image_text_auxiliary_checksum_changed')
            if artifact.get('measured_cover_design') is not None:
                if draft is None or not isinstance(artifact['measured_cover_design'], dict):
                    raise RuntimeError('measured_cover_requires_current_draft')
                draft.setdefault('draft_meta', {})['cover_design'] = copy.deepcopy(artifact['measured_cover_design'])
            for item in artifact.get("images", []):
                artifact_kind = "cover" if str(item.get("role") or "").casefold() == "cover" else "image"
                self.store.add_artifact(job_id, artifact_kind, item.get("path", ""), item.get("checksum", ""))
            mapping_path = Path(artifact["path"]).parent / "section_image_map.json"
            if not mapping_path.is_file() and self._strict_article_job(job_id):
                provenance_path = mapping_path.parent / "asset_provenance.json"
                try:
                    provenance = json.loads(provenance_path.read_text(encoding="utf-8")).get("assets", []) if provenance_path.is_file() else []
                except (OSError, ValueError):
                    provenance = []
                rows = []
                for index, item in enumerate(artifact.get("images", []), start=1):
                    if str(item.get("role") or "").casefold() == "cover":
                        continue
                    if len(rows) >= 3:
                        break
                    path = str(item.get("path") or "")
                    evidence = next((row for row in provenance if str(row.get("path") or "") == path), {})
                    rows.append({
                        "section": f"section_{len(rows)+1}",
                        "image": Path(path).name,
                        "asset_id": f"section_{len(rows)+1}",
                        "asset_hash": str(item.get("checksum") or ""),
                        "purpose": str(evidence.get("match_reason") or f"section-matched visual {len(rows)+1}"),
                        "adjacent_to_text": f"article section {len(rows)+1}",
                        "source": str(evidence.get("source_url") or ""),
                        "rights": str(evidence.get("license") or ""),
                        "semantic_match": bool(float(evidence.get("semantic_match_score") or 0) >= 0.72),
                        "semantic_match_score": float(evidence.get("semantic_match_score") or 0),
                        "match_reason": str(evidence.get("match_reason") or ""),
                    })
                if len(rows) >= 3:
                    mapping_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            if mapping_path.is_file():
                self._register_auxiliary_artifact(job_id, "section_image_map", mapping_path)
            # Generated article images carry their source/license per asset in this file; it is their rights record.
            provenance_path = mapping_path.parent / "asset_provenance.json"
            if not artifact.get("auxiliary_artifacts") and provenance_path.is_file():
                self._register_auxiliary_artifact(job_id, "rights", provenance_path)
            return artifact
        self.store.add_artifact(job_id, artifact["kind"], artifact["path"], artifact.get("checksum", ""))
        return artifact

    def _generate_video_per_platform(self, job_id, runner, depends_on, *, owner, draft=None, attempt_id=None):
        """Generate one independently addressed video for every target platform."""
        job = self._media_generation_job(job_id,draft)
        if attempt_id is not None:
            job['attempt_id'] = attempt_id
        cfg = dict(self.config.get("media", {}).get("video", {}) or {})
        required = self._media_required("video", cfg, job)
        platforms = [str(item).strip() for item in job.get("platforms", []) if str(item).strip()]
        if not cfg.get("enabled", False):
            if required:
                runner.block("generate_video_per_platform", "video_required_but_not_enabled", "video generation is required but disabled", depends_on=depends_on)
            runner.skipped("generate_video_per_platform", "video_not_enabled", "video generation is not enabled", required=False, depends_on=depends_on)
            return []
        if not platforms:
            raise RuntimeError("video generation requires at least one target platform")
        results = []
        failures = []
        for platform in platforms:
            step = f"generate_video[{platform}]"
            from .task_source_inputs import project_task_source_job
            platform_job = project_task_source_job(job,platform)
            if (platform_job.get('brief',{}).get('content_blueprint') or {}).get('video_source_planning'):
                from .video_planning_producer import read_bound_video_planning
                planning=read_bound_video_planning(self.store,job_id,platform_job['brief'])
                for field in ('video_script','narration_script','video_planning_audit'):
                    if platform_job['draft_meta'].get(field)!=planning[field]:raise ValueError('render_planning_revision_changed:'+field)
                if (platform_job['draft_meta'].get('video_toolchain_plan') or {}).get('video_asset_requirements'):
                    from .video_asset_semantics import read_requirements
                    read_requirements(self.store,job_id,platform_job['brief'],platform_job['draft_meta']['video_toolchain_plan'])
            platform_job["platform_run_parent_job_id"] = job_id
            platform_job["quality_evidence_required"] = True
            preflight_brief=platform_job.get('brief') or {}
            if (preflight_brief.get('content_blueprint') or {}).get('native_video_research_ref'):
                from .video_preflight_inputs import bind_video_preflight
                meta=platform_job.get('draft_meta') or {};plan=meta.get('video_toolchain_plan') or {}
                plan['video_preflight_ref']=bind_video_preflight(self.store,platform_job,platform,preflight_brief,plan,
                    str(meta.get('video_script') or ''),owner)
                meta['video_toolchain_plan']=plan;platform_job['draft_meta']=meta
            try:
                artifact = runner.run(
                    step,
                    lambda platform_job=platform_job: self.media.generate("video", platform_job),
                    required=required,
                    depends_on=depends_on,
                )
                if not artifact:
                    failures.append({"platform": platform, "error": "missing_artifact"})
                    continue
                results.append((platform, artifact))
                self.store.add_artifact(job_id, artifact["kind"], artifact["path"], artifact.get("checksum", ""))
            except Exception as exc:
                failures.append({"platform": platform, "error": redact_secrets(exc)})
                self.store.record_event(job_id, "platform_video_failed", {"platform": platform, "error": redact_secrets(exc)})
                if required:
                    raise
        self.store.record_event(
            job_id,
            "platform_video_batch_completed",
            {"platforms": platforms, "succeeded": len(results), "failed": failures},
        )
        return results

    @staticmethod
    def _execution_media_kinds(kinds,draft,config=None):
        kinds=set(kinds)
        meta=draft.get('draft_meta') or {}
        plan=meta.get('media_plan')
        audio_cfg=(config or {}).get('media',{}).get('audio',{})
        # Global optional audio capability is not a text/image delivery requirement.
        # Explicit audio/video/unknown plans retain the original required-source gate.
        if ('audio' in kinds and not audio_cfg.get('required')
                and meta.get('content_form') in {'text','short_post','image_text','image_text_post','manual_carousel',
                                                 'article','long_article','technical_article','evidence_answer'}
                and isinstance(plan,list) and plan and all(isinstance(x,str) for x in plan)
                and set(plan)<={'cover','content_images','image','images','caption','article','text'}
                and not meta.get('voice_plan') and not meta.get('audio_plan')
                and not (meta.get('video_toolchain_plan') or {}).get('required')
                and not (draft.get('brief') or {}).get('voice_plan')
                and not (draft.get('brief') or {}).get('audio_plan')
                and not ((draft.get('brief') or {}).get('video_toolchain_plan') or {}).get('required')):
            kinds.discard('audio')
        if kinds & {'article','caption'} and (not str(draft.get('title') or '').strip() or not str(draft.get('body') or '').strip()):
            raise RuntimeError('required_text_plan_not_materialized')
        return kinds-{'article','caption'}

    def _reuse_registered_cover(self,job_id,generated_image=None,current_job=None):
        rows=[row for row in self.store.artifacts(job_id) if row.get('kind')=='cover']
        current_ref=(current_job or {}).get('draft_meta',{}).get('current_visual_plan_ref')
        generated_ref=(generated_image or {}).get('current_visual_plan_ref')
        if current_ref or generated_ref:
            from .visual_policy_gate import file_record,digest
            from .factual_candidate_revision import private_read
            if not current_ref or not generated_ref or current_job.get('id')!=job_id:
                raise RuntimeError('registered_cover_current_visual_source_required')
            pin=file_record(current_ref.get('path')or'',current_ref.get('sha256'))
            plan=private_read(pin['path'],pin['sha256'],limit=262144)
            if plan.get('version')=='caption_revision_inherited_visual_binding_v1':
                plan,_=self.media._current_image_text_plan(current_job)
            if (plan.get('version')!='current_image_text_visual_plan_v1' or plan.get('job_id')!=job_id
                    or plan.get('draft_source_sha256')!=digest({'title':current_job.get('title'),'body':current_job.get('body')})
                    or current_job.get('platforms')!=[plan.get('platform')]):
                raise RuntimeError('registered_cover_current_plan_identity_or_draft_changed')
            if (generated_ref.get('path')!=pin['path'] or generated_ref.get('sha256')!=pin['sha256']
                    or current_ref.get('path')!=pin['path'] or current_ref.get('sha256')!=pin['sha256']):
                raise RuntimeError('registered_cover_current_visual_plan_changed')
            images=generated_image.get('images')
            auxiliary=generated_image.get('auxiliary_artifacts')
            if (not isinstance(images,list) or not isinstance(auxiliary,list) or len(auxiliary)!=2
                    or {row.get('kind')for row in auxiliary}!={'rights','render_manifest'}):
                raise RuntimeError('registered_cover_current_render_set_invalid')
            originals=self.store.artifacts(job_id)
            current_root=(Path(self.data_dir)/'artifacts'/str(job_id)).resolve(strict=True)
            for item in [*images,*auxiliary]:
                item_path=Path(str(item.get('path')or''))
                if (item_path.is_symlink()or any(parent.is_symlink()for parent in item_path.parents)
                        or not item_path.is_file()or not item_path.resolve(strict=True).is_relative_to(current_root)):
                    raise RuntimeError('registered_cover_current_artifact_path_untrusted_or_missing')
                kind=item.get('kind')
                if item in images:kind='cover' if item.get('role')=='cover'else'image'
                matches=[row for row in originals if row.get('kind')==kind and row.get('path')==item.get('path')]
                if len(matches)!=1 or matches[0].get('checksum')!=item.get('checksum'):
                    raise RuntimeError('registered_cover_current_artifact_not_registered')
                file_record(item['path'],item['checksum'])
            aux={row['kind']:row for row in auxiliary}
            manifest=json.loads(Path(aux['render_manifest']['path']).read_text(encoding='utf-8'))
            rights=json.loads(Path(aux['rights']['path']).read_text(encoding='utf-8'))
            identities=[(row.get('role'),row.get('path'),row.get('checksum'))for row in images]
            if (manifest.get('version')!='current_image_text_render_manifest_v1'
                    or rights.get('version')!='current_image_text_rights_v1'
                    or manifest.get('job_id')!=job_id or rights.get('job_id')!=job_id
                    or manifest.get('plan_ref')!=generated_ref or rights.get('plan_ref')!=generated_ref
                    or manifest.get('rights',{}).get('path')!=aux['rights']['path']
                    or manifest.get('rights',{}).get('sha256')!=aux['rights']['checksum']
                    or [(row.get('role'),row.get('file',{}).get('path'),row.get('file',{}).get('sha256'))for row in manifest.get('images')or[]]!=identities
                    or [(row.get('role'),row.get('section'))for row in images]!=[(row.get('role'),row.get('id'))for row in plan['slots']]
                    or len({row.get('path')for row in images})!=len(images)):
                raise RuntimeError('registered_cover_current_manifest_or_slots_changed')
            covers=[item for item in images if item.get('role')=='cover']
            if len(covers)!=1:raise RuntimeError('registered_cover_current_slot_missing_or_ambiguous')
            rows=[row for row in rows if row.get('path')==covers[0]['path']and row.get('checksum')==covers[0]['checksum']]
        if len(rows)!=1:raise RuntimeError('registered_cover_missing_or_ambiguous')
        row=rows[0];path=Path(str(row.get('path') or ''))
        root=(Path(self.data_dir)/'artifacts'/str(job_id)).resolve(strict=True)
        if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents)
                or not path.is_file() or not path.resolve(strict=True).is_relative_to(root)):
            raise RuntimeError('registered_cover_path_untrusted_or_missing')
        checksum=sha256_file(path)
        if not row.get('checksum') or checksum!=row['checksum']:
            raise RuntimeError('registered_cover_checksum_mismatch')
        return {'kind':'cover','path':str(path),'checksum':checksum,'reused_registered_artifact':True,
                'producer_step':'generate_or_collect_images'}

    def _bind_release_artifact_sources(self, job_id, platform, draft_id, content, bound):
        # Normal Store artifacts and formatter output are unqualified source bytes.
        folder = Path(self.data_dir).resolve() / 'artifacts' / str(job_id) / 'platforms' / platform / 'quality_source_bytes'
        folder.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        checksum = hashlib.sha256(raw).hexdigest()
        path = folder / ('publication_copy-' + checksum + '.txt')
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.is_symlink() or sha256_file(path) != checksum:
                raise RuntimeError('current_platform_copy_source_changed')
        else:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        existing = [row for row in self.store.artifacts(job_id)
                    if row['kind'] == 'platform_copy' and row['path'] == str(path)]
        if not existing:
            self.store.add_artifact(job_id, 'platform_copy', str(path), checksum)
            existing = [row for row in self.store.artifacts(job_id)
                        if row['kind'] == 'platform_copy' and row['path'] == str(path)]
        if len(existing) != 1 or existing[0]['checksum'] != checksum:
            raise RuntimeError('current_platform_copy_store_binding_invalid')
        registered = {row['id']: row for row in self.store.artifacts(job_id)}
        from .mandatory_quality_context import current_draft_source_sha256
        from .task_source_inputs import project_task_source_job
        scoped = project_task_source_job(self.store.get_job(job_id), platform)
        records = [{'artifact_id': existing[0]['id'], 'role': 'copy', 'slot': 'copy',
                    'path': str(path), 'checksum': checksum, 'content': content,
                    'provenance': {'producer_step': 'format_for_platform',
                                   'draft_source_sha256': current_draft_source_sha256(scoped, draft_id)}}]
        for role, artifact_id, actual_sha, provenance in bound:
            row = registered[artifact_id]
            if row['job_id'] != job_id or row['checksum'] != actual_sha or sha256_file(Path(row['path'])) != actual_sha:
                raise RuntimeError('current_source_artifact_changed')
            records.append({'artifact_id': artifact_id, 'role': role, 'slot': role + ':' + str(artifact_id),
                            'path': row['path'], 'checksum': actual_sha})
        payload = {'version': 'native_render_artifact_binding_v1', 'job_id': job_id, 'platform': platform,
                   'draft_version_id': draft_id, 'artifacts': records}
        payload['revision_id'] = 'source-' + hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        digest = hashlib.sha256(raw).hexdigest(); manifest = folder / ('artifact-binding-' + digest + '.json')
        try:
            fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if manifest.is_symlink() or sha256_file(manifest) != digest:
                raise RuntimeError('current_artifact_binding_changed')
        else:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        pin = {'path': str(manifest), 'sha256': digest}
        from .visual_candidate_revision import binding_step_name,record_binding_reference
        from .native_quality_resume import binding_step_name as quality_binding_name, record_binding_reference as record_quality_binding
        from .native_stage_resume import binding_step_name as checkpoint_binding_name, record_binding_reference as record_checkpoint_binding
        quality_step=quality_binding_name(self.store,job_id,platform)
        checkpoint_step=checkpoint_binding_name(self.store,job_id,platform)
        if quality_step and checkpoint_step:raise PermissionError('current_artifact_binding_multiple_active_scopes')
        actual_step=checkpoint_step or quality_step or binding_step_name(self.store,job_id,platform)
        WorkflowStepRunner(self.store, 'wf_' + job_id, job_id, platform=platform).succeeded(
            actual_step, {'artifact_manifest': pin},
            message='真实Store实物来源登记，尚未代表质量通过')
        if checkpoint_step:
            record_checkpoint_binding(self.store,job_id,platform,pin)
        elif quality_step:
            record_quality_binding(self.store,job_id,platform,pin)
        elif actual_step!='bind_rendered_artifact_sources':
            record_binding_reference(self.store,job_id,platform,pin)
        return pin

    @staticmethod
    def _threads_formatter_job(job, image_specs, artifacts):
        """把本任务已登记且字节未变的封面和内图绑定到终稿，封面也计入平台图数。"""
        if (not isinstance(image_specs, list) or any(not isinstance(item, dict)
                or set(item) != {'role', 'path'} or item['role'] not in {'image', 'cover'}
                or not isinstance(item['path'], str) for item in image_specs)
                or len({item['path'] for item in image_specs}) != len(image_specs)):
            raise ValueError('threads_current_image_inventory_duplicate_or_invalid')
        images = []
        for item in image_specs:
            path, role = item['path'], item['role']
            rows = [row for row in artifacts if row.get('kind') == role
                    and row.get('path') == path and row.get('job_id') == job.get('id')]
            if len(rows) != 1:
                raise ValueError('threads_current_image_not_registered_for_job')
            row = rows[0]
            file = Path(path)
            if (not file.is_absolute() or file.is_symlink() or any(p.is_symlink() for p in file.parents)
                    or not file.is_file() or sha256_file(file) != row.get('checksum')):
                raise ValueError('threads_current_registered_image_bytes_changed')
            images.append({'path': path, 'checksum': row['checksum'], 'artifact_id': row['id'], 'role': role})
        return dict(job, images=images)

    def _prepare_platform_output_sources(self, job_id, generated_image, platform_videos, shared_media=None):
        from .mandatory_quality_context import current_draft_source_sha256
        job = self.store.get_job(job_id)
        produced_images = []
        if isinstance(generated_image, dict):
            produced_images.extend(generated_image.get("images") or [])
            if generated_image.get("kind") in {"cover", "image"} and generated_image.get("path") and not any(
                str(child.get("path")) == str(generated_image["path"]) for child in produced_images
            ):
                produced_images.append(generated_image)
        shared_media = shared_media or []
        produced_roles = {
            "cover" if str(item.get("role") or item.get("kind") or "").casefold() == "cover" else "image"
            for item in produced_images
        }
        produced_roles.update(kind for kind, _ in shared_media)
        required_media = self._execution_media_kinds(generated_media_kinds_for_job(job, self.config),job,self.config)
        for kind in required_media - {"video"}:
            if kind not in produced_roles:
                raise RuntimeError(f"required_platform_{kind}_unowned")
        if "video" in required_media and any(platform not in platform_videos for platform in job["platforms"]):
            raise RuntimeError("required_platform_video_unowned")
        artifacts = self.store.artifacts(job_id)
        artifact_by_identity = {(row["kind"], row["path"]): row for row in artifacts}
        draft_id = self.store.draft_versions(job_id)[-1]["id"]
        prepared_outputs = {}
        for platform in job["platforms"]:
            normalized = str(platform).casefold()
            from .task_source_inputs import project_task_source_job
            scoped_job=project_task_source_job(job,platform)
            format_job = scoped_job
            if normalized == 'threads':
                image_specs = [{'role': 'cover' if str(image.get('role') or image.get('kind') or '').casefold() == 'cover' else 'image',
                                'path': str(image['path'])} for image in produced_images]
                image_specs.extend({'role': kind, 'path': str(generated['path'])}
                    for kind, generated in shared_media if kind in {'image', 'cover'})
                format_job = self._threads_formatter_job(scoped_job, image_specs, artifacts)
            copy = format_for_platform(format_job, platform)
            owned = []
            if platform in platform_videos:
                video = platform_videos[platform]
                owned.append(("video", video["kind"], str(video["path"]), video,
                              video.get('producer_step') or f"generate_video[{platform}]"))
            for image in produced_images:
                kind = "cover" if str(image.get("role") or image.get("kind") or "").casefold() == "cover" else "image"
                owned.append((kind, kind, str(image["path"]), image, "generate_or_collect_images"))
            for kind, generated in shared_media:
                owned.append((kind, generated["kind"], str(generated["path"]), generated,
                              f"generate_{kind}"))
            auxiliary=(generated_image or {}).get('auxiliary_artifacts') or []
            if auxiliary:
                from .visual_policy_gate import file_record
                if {x.get('kind')for x in auxiliary}!={'rights','render_manifest'} or len(auxiliary)!=2:
                    raise RuntimeError('current_image_text_auxiliary_set_invalid')
                auxiliary_by_kind={x['kind']:x for x in auxiliary}
                for row in auxiliary:
                    path=Path(str(row.get('path') or ''))
                    if (not path.is_absolute() or path.is_symlink() or any(x.is_symlink()for x in path.parents)
                            or not path.resolve().is_relative_to((Path(self.data_dir)/'artifacts'/str(job_id)).resolve())
                            or sha256_file(path)!=row.get('checksum')):
                        raise RuntimeError('current_image_text_auxiliary_source_invalid')
                    actual=artifact_by_identity.get((row['kind'],str(path)))
                    if actual is None or actual['job_id']!=job_id or actual['checksum']!=row['checksum']:
                        raise RuntimeError('current_image_text_auxiliary_not_registered')
                manifest=json.loads(Path(auxiliary_by_kind['render_manifest']['path']).read_text(encoding='utf-8'))
                rights=json.loads(Path(auxiliary_by_kind['rights']['path']).read_text(encoding='utf-8'))
                if (manifest.get('version')!='current_image_text_render_manifest_v1'
                        or rights.get('version')!='current_image_text_rights_v1'
                        or manifest.get('job_id')!=job_id or rights.get('job_id')!=job_id
                        or manifest.get('plan_ref')!=(generated_image or {}).get('current_visual_plan_ref')
                        or rights.get('plan_ref')!=manifest['plan_ref']
                        or manifest.get('rights',{}).get('path')!=auxiliary_by_kind['rights']['path']
                        or manifest.get('rights',{}).get('sha256')!=auxiliary_by_kind['rights']['checksum']
                        or [(x.get('role'),x.get('file',{}).get('path'),x.get('file',{}).get('sha256'))for x in manifest.get('images')or[]]
                           !=[(x.get('role'),x.get('path'),x.get('checksum'))for x in produced_images]):
                    raise RuntimeError('current_image_text_manifest_not_current_artifacts')
                file_record(manifest['plan_ref']['path'],manifest['plan_ref']['sha256'])
                for row in auxiliary:
                    owned.append((row['kind'],row['kind'],row['path'],row,'generate_or_collect_images'))
            elif produced_images:
                provenance_path=str(Path(self.data_dir)/'artifacts'/str(job_id)/'asset_provenance.json')
                if ('rights',provenance_path) in artifact_by_identity:
                    owned.append(('rights','rights',provenance_path,{},'generate_or_collect_images'))
            if normalized == 'wechat':
                root=Path(self.data_dir)/'artifacts'/str(job_id)
                article_rows=[row for row in artifacts if row['kind']=='wechat_format' and Path(row['path']).name=='wechat_review.html']
                card_rows=[row for row in artifacts if row['kind']=='knowledge_card' and Path(row['path']).suffix.casefold()=='.png']
                if len(article_rows)!=1 or len(card_rows)<3:
                    raise RuntimeError('wechat_review_artifacts_missing_or_ambiguous')
                for role,rows,step in [('article_html',article_rows,'render_wechat_local_article'),
                                       ('knowledge_card',card_rows,'render_wechat_knowledge_cards')]:
                    for row in rows:
                        file=Path(row['path'])
                        if file.is_symlink() or any(parent.is_symlink() for parent in file.parents) or not file.is_file() or not file.resolve().is_relative_to(root.resolve()) or sha256_file(file)!=row['checksum']:
                            raise RuntimeError('wechat_review_artifact_path_or_checksum_invalid')
                        owned.append((role,row['kind'],row['path'],{},step))
            bound = []
            for role, kind, path, generated, producer_step in owned:
                row = artifact_by_identity.get((kind, path))
                if row is None:
                    raise RuntimeError("generated_platform_artifact_not_persisted")
                file = Path(path)
                if not file.is_file():
                    raise RuntimeError("generated_platform_artifact_missing")
                provenance = {"producer_step": producer_step}
                for field in ("source_url", "license", "rights", "source", "semantic_match_score"):
                    if field in generated:
                        provenance[field] = generated[field]
                bound.append((role, row["id"], sha256_file(file), provenance))
            quality = {"passed": False, "phase": "unreviewed_source_bytes"}
            copy_provenance = {
                "producer_step": "format_for_platform",
                "draft_version_id": draft_id,
                "draft_source_sha256": current_draft_source_sha256(scoped_job, draft_id),
            }
            revision_payload = {"draft_version_id": draft_id, "copy": copy, "copy_provenance": copy_provenance,
                                "artifacts": bound, "quality": quality}
            revision = hashlib.sha256(json.dumps(revision_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            if platform in platform_videos:
                from .native_render_parts import bind_actual_video_parts
                bound.extend(bind_actual_video_parts(self.store, self.data_dir, job_id, platform, platform_videos[platform]))
            source_pin = self._bind_release_artifact_sources(job_id, platform, draft_id, copy, bound)
            revision = json.loads(Path(source_pin['path']).read_text(encoding='utf-8'))['revision_id']
            prepared_outputs[platform] = (revision, copy, copy_provenance, bound, quality)
        return prepared_outputs

    def _execute_current_native_quality(self, job_id, runner):
        from .mandatory_release_gate import _scoped_store, _resolve_current_policy
        from .mandatory_quality_context import prepare_current_quality_context, canonical_sha
        from .native_quality_runner import run_native_quality
        results = {}
        for platform in self.store.get_job(job_id)["platforms"]:
            scoped = _scoped_store(self.store, platform)
            policy = _resolve_current_policy(scoped, self.data_dir, job_id, platform)
            context = prepare_current_quality_context(scoped, self.data_dir, job_id, platform, current_policy=policy)
            key = canonical_sha(context)
            prior = [json.loads(row["detail_json"]) for row in self.store.events(job_id)
                     if row["event"] == "native_mandatory_quality_attempt" and json.loads(row["detail_json"]).get("context_sha256") == key]
            if prior:
                actual = self._mandatory_release_gate(job_id, platform=platform, phase="release")
                if actual.get("passed") is not True:
                    raise WorkflowBlocked("run_native_mandatory_quality", "current_quality_attempt_not_qualified",
                        "同一实物版本已有失败或未完成审核，须明确修订后再审", actual)
                results[platform] = actual
                continue
            self.store.record_event(job_id, "native_mandatory_quality_attempt",
                {"platform": platform, "context_sha256": key, "quality_passed": False})
            timeout=600
            if (self.store.get_job(job_id).get('brief')or{}).get('caption_revision_ref'):
                from .native_stage_resume import caption_revision_stage_budget
                timeout=caption_revision_stage_budget(self.store,job_id,timeout)
            result = run_native_quality(self.store, self.data_dir, job_id, platform, timeout=timeout)
            self.store.record_event(job_id, "native_mandatory_quality_result",
                {"platform": platform, "context_sha256": key, "result": result})
            if result.get("passed") is not True:
                raise WorkflowBlocked("run_native_mandatory_quality", "actual_quality_review_failed",
                    "真实当前规则或质量审核未通过", result)
            results[platform] = result
        runner.succeeded("run_native_mandatory_quality", results, depends_on=["validate_image_requirements"])
        return results

    def _record_platform_outputs(self, job_id, final_gate, generated_image, platform_videos, shared_media=None,
                                 prepared_outputs=None):
        from .mandatory_quality_context import current_draft_source_sha256
        job = self.store.get_job(job_id)
        gate = (final_gate.get("gates") or {}).get("G6_platform_quality") or {}
        results = gate.get("results") or {}
        if not final_gate.get("passed") or any(not (results.get(str(platform).casefold()) or {}).get("passed")
                                             for platform in job["platforms"]):
            raise WorkflowBlocked("record_platform_outputs", "unqualified_platform_outputs",
                                  "最终平台质量未通过，禁止合格输出登记", final_gate)
        draft_id = self.store.draft_versions(job_id)[-1]["id"]
        if prepared_outputs is None:
            prepared_outputs = self._prepare_platform_output_sources(job_id, generated_image, platform_videos, shared_media)
        if set(prepared_outputs) != set(job['platforms']):
            raise RuntimeError('quality_source_platform_coverage_changed')
        registered = {row['id']: row for row in self.store.artifacts(job_id)}
        from .task_source_inputs import project_task_source_job
        from .mandatory_release_gate import _scoped_store, _resolve_current_policy
        from .mandatory_quality_context import _pin, _object
        for platform, (revision, copy, provenance, bound, _) in prepared_outputs.items():
            scoped = project_task_source_job(job, platform)
            scoped_store = _scoped_store(self.store, platform)
            policy = _resolve_current_policy(scoped_store, self.data_dir, job_id, platform)
            source = _object(_pin(policy.get('artifact_manifest'), 'current_output_source'), 'current_output_source')
            expected_bound = [(row['role'], row['artifact_id'], row['checksum']) for row in source['artifacts'] if row['role'] != 'copy']
            actual_bound = [(role, artifact_id, checksum) for role, artifact_id, checksum, _ in bound]
            if (revision != source['revision_id'] or source['draft_version_id'] != draft_id
                    or source['job_id'] != job_id or source['platform'] != platform
                    or len(set(actual_bound)) != len(actual_bound)
                    or sorted(actual_bound) != sorted(expected_bound)):
                raise RuntimeError('quality_source_exact_artifact_set_changed')
            format_job = scoped
            if str(platform).casefold() == 'threads':
                image_specs = [{'role': role, 'path': registered[artifact_id]['path']}
                    for role, artifact_id, _, _ in bound if role in {'image', 'cover'}]
                format_job = self._threads_formatter_job(scoped, image_specs, list(registered.values()))
            if (copy != format_for_platform(format_job, platform)
                    or provenance.get('draft_version_id') != draft_id
                    or provenance.get('draft_source_sha256') != current_draft_source_sha256(scoped, draft_id)):
                raise RuntimeError('quality_source_current_copy_changed')
            for role, artifact_id, checksum, _ in bound:
                row = registered.get(artifact_id)
                if (not row or row['job_id'] != job_id or row['checksum'] != checksum
                        or sha256_file(Path(row['path'])) != checksum):
                    raise RuntimeError('quality_source_actual_artifact_changed')
        mandatory = self._mandatory_release_gate(job_id, phase='release')
        if mandatory.get('passed') is not True:
            self.store.record_event(job_id, 'mandatory_release_quality_blocked', mandatory)
            raise WorkflowBlocked('run_mandatory_release_gate', 'mandatory_final_quality_not_qualified',
                                  '最终内容缺正常规则或质量执行原件，不能交付', mandatory)
        self.store.save_workflow_acceptance(job_id, {
            'version':'final_platform_output_acceptance_v1','job_id':job_id,
            'draft_version_id':draft_id,'passed':True,'final_gate':final_gate,
            'final_gate_checksum':hashlib.sha256(json.dumps(final_gate,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'content_revisions':{platform:value[0] for platform,value in prepared_outputs.items()}})
        for platform, (revision, copy, copy_provenance, bound, quality) in prepared_outputs.items():
            if copy_provenance["draft_version_id"] != draft_id:
                raise RuntimeError("quality_review_draft_version_changed")
            quality = {"passed": True, "phase": "rendered", "platform_gate": results[str(platform).casefold()],
                "final_gate_checksum": hashlib.sha256(json.dumps(final_gate, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                "mandatory_release": mandatory["results"][platform]}
            # Qualification changes status, while the reviewed source revision stays stable.
            saved = [self.store.record_platform_output(
                job_id, platform, revision, draft_id, "copy", "copy", content=copy,
                provenance=copy_provenance, quality_evidence=quality)]
            for role, artifact_id, _, provenance in bound:
                saved.append(self.store.record_platform_output(
                    job_id, platform, revision, draft_id, f"{role}:{artifact_id}", role,
                    artifact_id=artifact_id, provenance=provenance, quality_evidence=quality))
            self.store.record_platform_output(
                job_id, platform, revision, draft_id, "manifest", "manifest",
                content={"slots": {row["slot"]: row["checksum"] for row in saved}},
                provenance={"producer_step": "run_mandatory_release_gate"}, quality_evidence=quality)
        self.store.record_event(job_id, 'mandatory_release_quality_verified', mandatory)

    def _media_required(self, kind, cfg, job):
        if kind == "image":
            brief = (job or {}).get("brief") or {}
            platforms = {str(p).casefold() for p in (job or {}).get("platforms", [])}
            if brief.get("run_contract") and platforms & {"zhihu", "juejin", "wechat", "wechat_official", "xiaohongshu", "rednote"}:
                return True
        if bool((cfg or {}).get("required", False)):
            return True
        if kind != "video":
            return False
        plan = ((job or {}).get("draft_meta") or {}).get("video_toolchain_plan") or {}
        return bool(plan.get("required"))

    def _validate_image_requirements(self, job_id, runner, generated_image=None):
        image_cfg = self.config.get("media", {}).get("image", {})
        job = self.store.get_job(job_id)
        strict_article = self._strict_article_job(job_id)
        required = bool(image_cfg.get("required", False)) or strict_article
        artifacts = [item for item in self.store.artifacts(job_id) if item.get("kind") in {"image", "cover"}]
        if not required and not image_cfg.get("enabled", False):
            runner.skipped("validate_image_requirements", "image_not_required", "current config does not require images", required=False, depends_on=["generate_or_collect_images"])
            return
        minimum = max(4, int(image_cfg.get("min_count", 0) or 0)) if strict_article else int(image_cfg.get("min_count", 1 if required else 0))
        verified = []
        failures = []
        for item in artifacts:
            path = Path(item.get("path", ""))
            if path.is_file() and path.stat().st_size > 0 and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
                verified.append(str(path))
            else:
                failures.append(str(path))
        gate = {
            "passed": len(verified) >= minimum and not failures,
            "checks": [
                {"rule_id": "image.required_count", "required": required, "passed": len(verified) >= minimum, "actual": len(verified), "expected_min": minimum, "blocking": required},
                {"rule_id": "image.file_readable", "required": required, "passed": not failures, "failed_paths": failures, "blocking": required},
            ],
        }
        if required and not gate["passed"]:
            runner.block("validate_image_requirements", "image_gate_failed", "required image validation failed", gate, depends_on=["generate_or_collect_images"])
        runner.succeeded("validate_image_requirements", gate, depends_on=["generate_or_collect_images"])

    def _strict_article_job(self, job_id):
        job = self.store.get_job(job_id)
        platforms = {str(p).casefold() for p in job.get("platforms", [])}
        return bool((job.get("brief") or {}).get("run_contract")) and bool(
            platforms & {"zhihu", "juejin", "wechat", "wechat_official", "xiaohongshu", "rednote"}
        )

    @staticmethod
    def _real_world_ai_lane(job, brief, draft):
        draft_meta = draft.get("draft_meta") if isinstance(draft.get("draft_meta"), dict) else {}
        strategy = brief.get("strategy") if isinstance(brief.get("strategy"), dict) else {}
        lanes = {
            str(value or "").strip()
            for value in (
                (job.get("brief") or {}).get("lane"),
                brief.get("lane"),
                strategy.get("lane"),
                strategy.get("channel_lane"),
                draft_meta.get("lane"),
            )
        }
        profiles = {
            str(value or "").strip()
            for value in (
                (job.get("brief") or {}).get("policy_profile"),
                brief.get("policy_profile"),
                draft_meta.get("policy_profile"),
            )
        }
        return bool(lanes & {"real_world_ai_implementation", "real_world_ai_implementation_v1"}) or "real_world_ai_implementation_v1" in profiles

    def _validate_real_world_ai_package(self, job, brief, draft, runner):
        if not self._real_world_ai_lane(job, brief, draft):
            runner.skipped(
                "validate_real_world_ai_package",
                "non_ai_lane",
                "canonical real-world AI package gate does not apply",
                depends_on=["validate_content_structure"],
            )
            return
        draft_meta = draft.setdefault("draft_meta", {})
        package = (
            draft_meta.get("real_world_ai_package")
            or draft.get("real_world_ai_package")
            or brief.get("real_world_ai_package")
        )
        gate = validate_real_world_ai_package(package)
        draft_meta["real_world_ai_package"] = package if isinstance(package, dict) else {}
        draft_meta["real_world_ai_package_gate"] = gate
        if not gate["passed"]:
            runner.block(
                "validate_real_world_ai_package",
                "real_world_ai_package_invalid",
                "AI-lane content requires a complete canonical real-world AI package",
                gate,
                depends_on=["validate_content_structure"],
            )
        runner.succeeded(
            "validate_real_world_ai_package",
            gate,
            depends_on=["validate_content_structure"],
        )

    def _validate_strict_article_completion(self, job_id, draft, runner):
        """Fail closed for compiled article runs before review or manifests."""
        platforms = {str(p).casefold() for p in self.store.get_job(job_id).get("platforms", [])}
        article_platforms = {"zhihu", "juejin", "wechat", "wechat_official", "xiaohongshu", "rednote"}
        brief = self.store.get_job(job_id).get("brief") or {}
        strict = bool(brief.get("run_contract")) and bool(platforms & article_platforms)
        if not strict:
            return
        from .media_quality import _article_evidence_gate, _article_language_gate

        packet = self._generation_platform_packet(job_id, draft, list(platforms), next(iter(platforms & article_platforms)))
        language = _article_language_gate(packet, packet["platform"])
        evidence = _article_evidence_gate(packet, packet["platform"])
        rows = self.store.artifacts(job_id)
        cover = [r for r in rows if r.get("kind") == "cover"]
        images = [r for r in rows if r.get("kind") == "image"]
        provenance_path = Path(self.data_dir) / "artifacts" / str(job_id) / "asset_provenance.json"
        provenance = {}
        if provenance_path.is_file():
            try:
                provenance = {str(r.get("path")): r for r in json.loads(provenance_path.read_text(encoding="utf-8")).get("assets", []) if isinstance(r, dict)}
            except (OSError, ValueError):
                provenance = {}
        def valid(row):
            path = Path(str(row.get("path") or ""))
            try:
                semantic = float(provenance.get(str(path), {}).get("semantic_match_score", 0) or 0)
            except (TypeError, ValueError):
                semantic = 0
            source = provenance.get(str(path), {}).get("source_url")
            rights = provenance.get(str(path), {}).get("license")
            return path.is_file() and bool(row.get("checksum")) and bool(source) and bool(rights) and semantic >= 0.72
        mapping = Path(self.data_dir) / "artifacts" / str(job_id) / "section_image_map.json"
        if not mapping.is_file():
            mapping = Path(self.data_dir) / "artifacts" / str(job_id) / "cards" / "section_image_map.json"
        try:
            mapping_rows = json.loads(mapping.read_text(encoding="utf-8")) if mapping.is_file() else []
        except (OSError, ValueError):
            mapping_rows = []
        mapping_ok = isinstance(mapping_rows, list) and len(mapping_rows) >= 3
        failures = []
        if not language.get("passed"): failures.append("article_language_gate")
        if not evidence.get("passed"): failures.append("article_evidence_gate")
        if len(cover) < 1 or not all(valid(r) for r in cover): failures.append("cover_artifact_contract")
        if len(images) < 3 or not all(valid(r) for r in images): failures.append("inline_image_artifact_contract")
        if not mapping_ok: failures.append("section_image_map_missing")
        gate = {"passed": not failures, "failures": failures, "language": language, "evidence": evidence,
                "cover_count": len(cover), "image_count": len(images), "section_image_map": mapping_ok}
        draft.setdefault("draft_meta", {})["strict_article_completion_gate"] = gate
        if failures:
            runner.block("validate_article_completion", "article_completion_contract_failed",
                         "article content or required visual artifact package is incomplete", gate,
                         depends_on=["validate_image_requirements"])
            raise WorkflowBlocked("validate_article_completion", "article_completion_contract_failed",
                                  "article content or required visual artifact package is incomplete", gate)

    def _quality_gate(self, job_id, draft, risk, geo, *, phase="rendered"):
        dm = draft.get("draft_meta", {})
        gate = {"passed": True, "gates": {}}
        g1 = risk.get("level", "pass") != "block"
        gate["gates"]["G1_risk_compliance"] = {"passed": g1, "level": risk.get("level", "pass")}
        platforms = dm.get("strategy", {}).get("primary_platforms", [])
        short_video = (
            str(dm.get("content_form") or "").casefold() in {"short_video", "knowledge_card_video", "edited_short_video", "microcase_video", "short_post", "micro_post", "tweet"}
            or bool({str(platform).casefold() for platform in platforms} & (SHORT_VIDEO_PLATFORMS | {"twitter", "x", "threads", "bluesky"}))
        )
        if short_video:
            checks = geo.get("checks") or {}
            g2 = bool(checks.get("direct_answer")) and bool(checks.get("short_paragraphs"))
            gate["gates"]["G2_geo"] = {
                "passed": g2,
                "score": geo.get("score", 0),
                "contract": "short_video",
                "checks": {
                    "direct_answer": bool(checks.get("direct_answer")),
                    "short_paragraphs": bool(checks.get("short_paragraphs")),
                },
                "note": "source provenance remains mandatory in G7_growth_recipe",
            }
        else:
            g2 = geo.get("score", 0) >= 40
            gate["gates"]["G2_geo"] = {"passed": g2, "score": geo.get("score", 0), "contract": "long_form"}
        qg = dm.get("quality_gate", {})
        g3 = qg.get("passed") is True
        failed_dimensions = list(qg.get("failed_dimensions", []) or [])
        if short_video and not g3 and set(failed_dimensions) == {"burstiness"}:
            # Eight concise beats are intentionally more even than an article.
            # Keep every other anti-generic dimension enforced.
            g3 = True
            gate["gates"]["G3_anti_generic"] = {
                "passed": True,
                "failed": failed_dimensions,
                "contract": "short_video",
                "variance_exception": "burstiness_only",
            }
        else:
            gate["gates"]["G3_anti_generic"] = {
                "passed": g3,
                "failed": failed_dimensions,
                "contract": "short_video" if short_video else "long_form",
            }
        artifacts = dm.get("media_plan", [])
        g4 = len(artifacts) > 0 if "short_video" == dm.get("content_form", "") else True
        gate["gates"]["G4_media_assets"] = {"passed": g4, "plan": artifacts}
        g5 = len(platforms) > 0
        gate["gates"]["G5_format"] = {"passed": g5, "platforms": platforms}
        try:
            job_brief = self.store.get_job(job_id).get("brief") or {}
        except KeyError:
            job_brief = {}
        editorial = job_brief.get("editorial_evidence") or {}
        editorial_complete = bool(
            str(editorial.get("strategy_source") or "").strip()
            and str(editorial.get("calendar_column") or "").strip()
            and str(editorial.get("planned_for") or editorial.get("planned_date") or "").strip()
            and (editorial.get("dedupe_passed") is True or str(editorial.get("dedupe") or "").strip())
        )
        if str(job_brief.get("selection_mode") or "") == "editorial_calendar" and editorial_complete:
            growth = {
                "passed": True,
                "failures": [],
                "source_status": "editorial_calendar",
                "editorial_evidence": editorial,
            }
        else:
            growth = validate_growth_recipe(dm.get("growth_recipe"))
        gate["gates"]["G7_growth_recipe"] = growth
        platform_quality = self._generation_platform_quality_gate(job_id, draft, list(platforms), phase=phase)
        if platform_quality:
            gate["gates"]["G6_platform_quality"] = platform_quality
        gate["passed"] = bool(gate["gates"]) and all(g.get("passed") is True for g in gate["gates"].values())
        gate["score"] = sum(1 for g in gate["gates"].values() if g["passed"])
        gate["total"] = len(gate["gates"])
        return gate

    def _generation_platform_quality_gate(self, job_id, draft, platforms, *, phase="generation"):
        results = {}
        for platform in platforms:
            normalized = str(platform or "").casefold()
            packet = self._generation_platform_packet(job_id, draft, platforms, normalized)
            try:
                job_brief = (self.store.get_job(job_id).get("brief") or {})
            except KeyError:
                job_brief = {}
            if job_brief.get("run_contract"):
                packet["run_contract"] = job_brief["run_contract"]
                packet["runtime_execution_required"] = True
            plan = packet.get("video_toolchain_plan") or {}
            needs_rendered_video = normalized in SHORT_VIDEO_PLATFORMS and bool(plan.get("required"))
            if phase == "generation" and self._defers_render_only_video_evidence(packet):
                result = {
                    "passed": True,
                    "deferred": True,
                    "reason": "render_only_video_evidence_checked_after_render",
                }
            elif phase == "rendered" and needs_rendered_video:
                result = self._rendered_video_platform_gate(packet, normalized)
            elif normalized == 'wechat':
                from .quality_gates import measure_wechat_local_assets
                measured = measure_wechat_local_assets(self.store,self.data_dir,job_id,draft) if phase=='rendered' else None
                result = validate_wechat_auto_packet(packet,phase=phase,local_evidence=measured,
                    native_task_scope=self._wechat_native_task_scope(job_id))
            else:
                result = self._platform_quality_validator(normalized, packet)
            if result:
                results[normalized] = result
        if not results or set(results) != {str(item).casefold() for item in platforms}:
            return {"passed": False, "mode": "enforce", "failures": ["required_platform_quality_validator_missing"],
                    "platforms": list(results), "results": results}
        return {
            "passed": all(result.get("passed") is True for result in results.values()),
            "mode": "enforce",
            "platforms": list(results.keys()),
            "results": results,
        }

    def _wechat_native_task_scope(self,job_id):
        binding=(self.store.get_job(job_id).get('brief') or {}).get('batch_plan')
        return 'batch' if isinstance(binding,dict) and binding.get('source')=='native.overnight_batch' else 'single'

    @staticmethod
    def _defers_render_only_video_evidence(packet):
        """Generation cannot prove media evidence that only a renderer can emit."""
        plan = packet.get("video_toolchain_plan") if isinstance(packet, dict) else {}
        if not isinstance(plan, dict) or not plan.get("required"):
            return False
        if packet.get("scene_visual_alignment") or packet.get("final_video") or packet.get("video_path"):
            return False
        return str(packet.get("platform") or "").casefold() in SHORT_VIDEO_PLATFORMS

    @staticmethod
    def _rendered_video_platform_gate(packet, platform):
        """Accept only measured renderer output after a required video render."""
        meta = dict(packet if isinstance(packet, dict) else {})
        artifact = meta.get("video_artifact") or {}
        manifest = meta.get("render_manifest") or {}
        output = Path(str(artifact.get("path") or manifest.get("output") or ""))
        plan = meta.get("video_toolchain_plan") or {}
        contract = manifest.get("toolchain_contract") or {}
        planned = set(contract.get("planned_tools") or [])
        motion = manifest.get("motion_evidence") or {}
        segments = (manifest.get("segment_motion_evidence") or {}).get("segments") or []
        audio = meta.get("audio_probe") or {}
        bgm = meta.get("bgm_source") or meta.get("bgm") or {}
        captions = meta.get("burned_captions") or {}
        subtitle = meta.get("subtitle") or {}
        backgrounds = meta.get("background_assets") or []
        # ── fallback: 合成阶段 artifact 未合并到 draft_meta 时，从落盘文件补齐测量值 ──
        job_id = str(meta.get("id") or packet.get("id") or "")
        if job_id:
            art_dir = Path(os.environ.get("AI_SELF_MEDIA_TOOLS_HOME") or (Path.home() / ".ai-self-media-tools")) / "data" / "artifacts" / job_id
            if art_dir.is_dir():
                # 先补 manifest/output，避免后续 audio 探针因 output 为空而跳过
                if not manifest.get("ok"):
                    try:
                        import json as _j4
                        mp = art_dir / "video_toolchain_runner_manifest.json"
                        if mp.is_file():
                            fallback_manifest = _j4.loads(mp.read_text(encoding="utf-8"))
                            if isinstance(fallback_manifest, dict) and fallback_manifest.get("ok"):
                                manifest = fallback_manifest
                                if not output.is_file():
                                    output = Path(str(fallback_manifest.get("output") or ""))
                                if not plan.get("required"):
                                    plan = fallback_manifest.get("video_toolchain_plan") or plan
                                if not planned:
                                    planned = set((fallback_manifest.get("toolchain_contract") or {}).get("planned_tools") or [])
                                if not motion.get("passed"):
                                    motion = fallback_manifest.get("motion_evidence") or {}
                                if not segments:
                                    segments = (fallback_manifest.get("segment_motion_evidence") or {}).get("segments") or []
                    except Exception:
                        pass
                if (not audio or not int(audio.get("stream_count") or 0)) and output.is_file():
                    try:
                        import json as _j, subprocess as _sp
                        pr = _sp.run(["ffprobe","-v","error","-show_entries","stream=codec_type","-show_entries","format=duration","-of","json", str(output)], capture_output=True, text=True, timeout=8)
                        j = _j.loads(pr.stdout or "{}")
                        streams = j.get("streams") or []
                        audio_streams = sum(1 for s in streams if s.get("codec_type")=="audio")
                        dur = float((j.get("format") or {}).get("duration") or 0)
                        if audio_streams or dur:
                            audio = {"stream_count": audio_streams, "duration": dur}
                            meta["audio_probe"] = audio
                    except Exception:
                        pass
                if (not bgm or not bgm.get("source_url")):
                    try:
                        import json as _j2
                        for cand in [art_dir / "bgm_source.json", art_dir / "bgm.json"]:
                            if cand.is_file():
                                raw_bgm = _j2.loads(cand.read_text(encoding="utf-8"))
                                if isinstance(raw_bgm, dict):
                                    # 保留实际来源 URL，不补造音乐匹配理由
                                    if raw_bgm.get("url") and not raw_bgm.get("source_url"):
                                        raw_bgm["source_url"] = raw_bgm["url"]
                                    if raw_bgm.get("source_url"):
                                        bgm = raw_bgm
                                        meta["bgm_source"] = bgm
                                        break
                    except Exception:
                        pass
                if not backgrounds:
                    try:
                        bgs = sorted(art_dir.glob("backgrounds/bg_*.png"))
                        if bgs:
                            backgrounds = [{"path": str(p)} for p in bgs]
                            meta["background_assets"] = backgrounds
                    except Exception:
                        pass
                if (not subtitle or not int(subtitle.get("cue_count") or 0)):
                    try:
                        import re as _re
                        srt = art_dir / "narration.srt"
                        if srt.is_file():
                            cues = len([l for l in srt.read_text(encoding="utf-8", errors="ignore").splitlines() if _re.match(r"^\d+$", l.strip())])
                            # 仅记录真实SRT条数；它不能证明已烧录或可读性。
                            subtitle = {"cue_count": cues}
                            meta["subtitle"] = subtitle
                    except Exception:
                        pass
                # (manifest 已在上方补齐)
        required_tools = {
            "cinema_composition.storyboard",
            "shotcraft_moves.shot_plan_for_text",
            "kuaishou_render.render_cards",
            "kuaishou_render.download_bgm",
            "kuaishou_render.gen_subtitles",
            "kuaishou_render.encode_final",
        }
        forbidden_bgm = {"synthetic", "procedural", "generated_tone", "midi", "generated_synthetic_bgm"}
        trusted_release = False
        trusted_error = ""
        if output:
            try:
                trusted_release = bool(
                    MediaBridge._validate_trusted_video_manifest(output.parent, expected_output=output)
                )
                if not trusted_release:
                    trusted_error = "trusted video manifest is missing"
            except RuntimeError as exc:
                trusted_error = str(exc)
        else:
            trusted_error = "trusted video manifest is missing"
        renderer_manifest_passed = (
            manifest.get("ok") is True
            and bool(plan.get("required"))
            and trusted_release
        )
        gates = {
            "rendered_output": {"passed": output.is_file() and output.stat().st_size > 0 and str(manifest.get("output") or "") == str(output)},
            "renderer_manifest": {"passed": renderer_manifest_passed},
            "trusted_release": {
                "passed": trusted_release,
                "mode": "trusted",
                "error": trusted_error,
            },
            "required_tool_contract": {"passed": required_tools.issubset(planned)},
            "motion_evidence": {"passed": motion.get("passed") is True and int(motion.get("unique_frame_count") or 0) >= 2},
            "segment_motion_evidence": {"passed": len(segments) >= 3 and all(isinstance(row, dict) and row.get("move_id") and row.get("profile") for row in segments)},
            "audio_stream": {"passed": int(audio.get("stream_count") or 0) >= 1 and float(audio.get("duration") or 0) >= 40},
            "real_instrument_bgm": {
                "passed": isinstance(bgm, dict) and str(bgm.get("source") or "").casefold() not in forbidden_bgm
                and bool(bgm.get("source_url")) and bool(bgm.get("license") or bgm.get("license_type"))
                and bool(bgm.get("fit_reason")) and not bool(bgm.get("fallback_used")),
            },
            "subtitle_safety": {
                "passed": int(subtitle.get("cue_count") or 0) >= 8 and captions.get("position") == "lower_third"
                and captions.get("burned_in") is True and int(captions.get("font_size") or 0) >= 44
                and int(captions.get("max_chars_per_line") or 99) <= 18 and int(captions.get("max_lines") or 99) <= 2
                and int(captions.get("margin_v") or 0) >= 180,
            },
            "visual_backgrounds": {"passed": isinstance(backgrounds, list) and len(backgrounds) >= 4},
            "platform_binding": {"passed": str(platform).casefold() in {str(item).casefold() for item in plan.get("platforms") or []}},
        }
        # Renderer evidence augments the ordinary platform contract; it cannot
        # replace per-scene backgrounds, mapping, or pre-generation strategy.
        meta.update(background_assets=backgrounds, audio_probe=audio,
                    burned_captions=captions, subtitle=subtitle, render_manifest=manifest)
        scenes = meta.get("scene_visual_alignment") or []
        cards = meta.get("knowledge_card_sequence") or []
        gates["real_scene_backgrounds"] = _real_scene_background_gate(
            meta, minimum=max(4, len(cards), len(scenes))
        )
        gates["scene_real_scene_mapping"] = _scene_real_scene_mapping_gate(meta, scenes)
        if str(platform).casefold() == "kuaishou":
            native = validate_kuaishou_auto_packet(meta, phase="preflight")
            for name in ("strategy_before_generation", "kuaishou_trend_evidence",
                         "workflow_steps", "card_layout_diversity", "real_music_source",
                         "bgm_license_manifest", "no_silent_bgm_fallback"):
                gates["kuaishou_" + name] = native["gates"][name]
        from .video_artifact import validate_duration_policy
        duration_media = {}
        if output.is_file():
            from .video_artifact import probe_video
            try:
                duration_media = probe_video(output)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                pass
        gates["duration_policy"] = validate_duration_policy(
            platform, float(duration_media.get("duration_seconds") or 0), manifest
        )
        from .visual_policy_gate import validate_visual_policy_release
        gates["visual_policy_release"] = validate_visual_policy_release(
            meta, platform, video_path=output, render_manifest=manifest
        )
        failures = [name for name, value in gates.items() if not value["passed"]]
        return {"passed": not failures, "phase": "rendered", "gates": gates, "failed_dimensions": failures}

    @staticmethod
    def _attach_video_render_evidence(draft, artifact):
        """Merge renderer-written measurements into the final quality packet."""
        meta = draft.setdefault("draft_meta", {})
        if isinstance(artifact.get('resolved_video_toolchain_plan'),dict):
            meta['video_toolchain_plan']=artifact['resolved_video_toolchain_plan']
        if isinstance(artifact.get('audio_input_binding'),dict):
            meta['audio_input_binding']=artifact['audio_input_binding']
        manifest = artifact.get("render_manifest")
        if isinstance(manifest, dict):
            meta["render_manifest"] = manifest
        renderer_packet = artifact.get("render_packet")
        if isinstance(renderer_packet, dict):
            for key in ("audio_probe", "subtitle", "burned_captions", "background_assets", "bgm", "bgm_source",
                        "real_scene_background_plan", "visual_background_plan", "scene_visual_alignment",
                        "knowledge_card_sequence", "source_assets", "visual_probe", "visual_policy_evidence",
                        "skill_execution_evidence"):
                if key in renderer_packet:
                    meta[key] = renderer_packet[key]
        # 2026-08-17 修复：visual_route（内容驱动路由）从 artifact 写回 draft_meta，
        # 否则 job 里永远 None（media.generate 修改的是局部 job 副本，未持久化）
        vr = artifact.get("visual_route")
        if isinstance(vr, dict):
            meta["visual_route"] = vr
        meta["video_artifact"] = {
            "path": artifact.get("path", ""),
            "checksum": artifact.get("checksum", ""),
            "selected_pipeline": artifact.get("selected_pipeline", ""),
        }

    @staticmethod
    def _generation_platform_packet(job_id, draft, platforms, platform):
        from .task_source_inputs import project_task_source_job
        draft=project_task_source_job(dict(draft,platforms=platforms),platform)
        draft_meta = draft.get("draft_meta") or {}
        strategy = draft_meta.get("strategy") or {}
        packet = {}
        for source in (strategy, draft_meta, draft):
            if isinstance(source, dict):
                packet.update(source)
        scoped_render = (draft_meta.get("platform_render_evidence") or {}).get(platform)
        if isinstance(scoped_render, dict):
            packet.update(scoped_render)
        packet.setdefault("id", job_id)
        packet.setdefault("title", draft.get("title", ""))
        packet.setdefault("body", draft.get("body", ""))
        packet.setdefault("platform", platform)
        packet.setdefault("platforms", platforms)
        if str(platform).casefold() in {"xiaohongshu", "rednote"} and not packet.get("ai_assisted_disclosure"):
            from .xiaohongshu_policy import AI_ASSISTED_DISCLOSURE
            packet["ai_assisted_disclosure"] = AI_ASSISTED_DISCLOSURE
        if (str(platform).casefold() in {"twitter", "x"}
                and (job_id == "25110343c3354385" or draft_meta.get("target_adaptation_ref"))):
            from .target_adaptation import read_target_adaptation
            target = read_target_adaptation(dict(draft, id=job_id, platforms=platforms), platform)
            caption = target["caption"]
            if (not isinstance(caption, str) or not 8 <= len(caption) <= 275
                    or hashlib.sha256(caption.encode()).hexdigest() != target["caption_sha256"]):
                raise ValueError("twitter_target_copy_source_or_length_invalid")
            packet.update(text=caption, caption=caption, target_copy_ref=target["target_copy_ref"],
                          caption_sha256=target["caption_sha256"])
        if "strategy_brief" not in packet and isinstance(strategy, dict):
            packet["strategy_brief"] = strategy
        if "content_type" not in packet and packet.get("content_form"):
            packet["content_type"] = packet["content_form"]
        return packet

    @staticmethod
    def _platform_quality_validator(platform, packet):
        from .final_acceptance_matrix import normalize_platform
        platform = normalize_platform(platform)
        if platform in {"wechat", "wechat_newspic"}:
            return validate_wechat_auto_packet(packet)
        if platform == "kuaishou":
            return validate_kuaishou_auto_packet(packet)
        if platform == "shipinhao":
            return validate_shipinhao_auto_packet(packet)
        if platform == "bilibili":
            return validate_bilibili_auto_packet(packet)
        if platform in {"douyin", "douyin_ai", "douyin_pet"}:
            if platform == "douyin_pet":
                packet = dict(packet, lane=packet.get("lane") or "pet")
            elif platform == "douyin_ai":
                packet = dict(packet, lane=packet.get("lane") or "ai")
            if packet.get("content_line") == "tiktok_hot_localized_repost":
                failures = validate_douyin_tiktok_repost_packet(packet, require_visual_review=True)
                return {"passed": not failures, "failed_dimensions": failures}
            return validate_douyin_auto_packet(packet)
        if platform in {"xiaohongshu", "rednote"}:
            return validate_xiaohongshu_auto_packet(packet)
        if platform in {"juejin", "zhihu", "devto", "telegraph", "writeas", "buttondown"}:
            return validate_platform_article_packet(packet, platform)
        if platform in {"tiktok", "youtube_long_form", "youtube_shorts", "youtube"}:
            return validate_video_packet(packet)
        if platform == 'threads':
            from .formatters import format_threads_copy
            try:
                measured = format_threads_copy(packet, phase='generation')
            except ValueError as exc:
                return {'passed': False, 'failed_dimensions': [str(exc)]}
            return {'passed': True, 'failed_dimensions': [],
                    **{key: value for key, value in measured.items() if key != 'text'}}
        if platform in {"twitter", "x"}:
            text = str(packet.get("text") or packet.get("caption") or packet.get("body") or "").strip()
            return {"passed": len(text) >= 8 and len(text) <= 275, "failed_dimensions": [] if 8 <= len(text) <= 275 else ["x_text_length"]}
        return None

    @staticmethod
    def _worker_id():
        return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


    def continue_caption_revision(self, job_id, owner, runner, proof_ref, history):
        """New caption work; immutable primary/pixels are lineage, never inherited QA."""
        from .native_stage_resume import validate_caption_revision, CAPTION_VERSION, _CAPTION_ACTIVE
        from .target_adaptation import generate_target_adaptation
        from .visual_policy_gate import validate_content_policy_inputs
        from .humanize import _score, quality_gate
        from .claim_ledger import validate_claims
        from .seo import geo_check
        from .factual_candidate_revision import write_once
        proof, actual = validate_caption_revision(self.store, proof_ref, child_id=job_id, live=True)
        if actual != history:
            raise ValueError('caption_revision_source_changed_before_generation')
        parent = history['parent']
        job = self.store.get_job(job_id)
        # A new strategy observation is explicit work, not a retimestamped parent Source.
        from .current_strategy_refresh import refresh_current_strategy_inputs
        from .native_quality_resume import FACT_FIELDS
        from .task_source_inputs import persist_task_source_inputs, refresh_task_source_contexts
        from .intelligence import prepare_generation_strategy_inputs
        original_brief = copy.deepcopy(job['brief'])
        strategy_job = copy.deepcopy(job)
        owned = self._enrich_brief(strategy_job)
        for field in ('historical_feedback','platform_historical_feedback','topic_historical_feedback',
                      'cluster_memory','legacy_feedback_reference'):
            if field in owned:strategy_job['brief'][field] = copy.deepcopy(owned[field])
        contexts = {p: load_platform_workflow_context(p,plan=strategy_job['brief']) for p in job['platforms']}
        refreshed = refresh_current_strategy_inputs(self.store,self.config,strategy_job,contexts,runner)
        prepared = refreshed['brief']
        if any(prepared.get(k) != original_brief.get(k) for k in FACT_FIELDS):
            raise ValueError('caption_revision_strategy_refresh_changed_historical_facts')
        for platform, scoped in refreshed['platform_briefs'].items():
            original = original_brief['platform_workflow_inputs'][platform]
            if any(scoped.get(k) != original.get(k) for k in FACT_FIELDS):
                raise ValueError('caption_revision_scoped_strategy_changed_historical_facts')
        audit = copy.deepcopy(original_brief.get('source_collection_audit')or{})
        audit['current_strategy_refresh_audit'] = refreshed['strategy_refresh_audit']
        prepared['source_collection_audit'] = audit
        prepared['caption_revision_ref'] = copy.deepcopy(proof_ref)
        for scoped in refreshed['platform_briefs'].values():scoped['source_collection_audit'] = copy.deepcopy(audit)
        prepared['platform_workflow_inputs'] = copy.deepcopy(refreshed['platform_briefs'])
        job = persist_task_source_inputs(self.store,job,owner,prepared)
        contexts = refresh_task_source_contexts(contexts,prepared)
        scoped = {p:self._bind_platform_source_inputs(job_id,b,p,contexts[p],owner)
                  for p,b in refreshed['platform_briefs'].items()}
        prepared['platform_workflow_inputs'] = copy.deepcopy(scoped)
        job = persist_task_source_inputs(self.store,job,owner,prepared)
        if len(scoped) != 1:raise PermissionError('caption_revision_single_current_platform_required')
        prepare_generation_strategy_inputs(job['topic'],next(iter(scoped.values())))
        hygiene = self._content_hygiene(job)
        if hygiene.get('status') == 'blocked':
            runner.block('validate_current_caption_hygiene', 'caption_current_dedup_blocked',
                         '当前七日跨渠道去重拒绝此修订', {'content_hygiene': hygiene})
        runner.succeeded('validate_current_caption_hygiene', hygiene)
        contexts = {p: load_platform_workflow_context(p, plan=job['brief']) for p in job['platforms']}
        inputs = validate_content_policy_inputs(job, contexts, store=self.store)
        if inputs.get('passed') is not True:
            runner.block('validate_current_caption_policy', 'caption_current_policy_blocked', '当前caption规则不接受此稿', inputs)
        runner.succeeded('validate_current_caption_policy', inputs)
        draft = {k: copy.deepcopy(parent[k]) for k in ('title', 'body', 'prompt_version', 'draft_meta')}
        meta = draft['draft_meta']
        for field in ('account_analysis','same_lane_intelligence','strategy_evidence','strategy_evidence_gate',
                      'strategy_observation_ref','viral_collection','viral_breakdown','hot_work_parameter_pack',
                      'platform_intelligence_constraints','historical_feedback','platform_historical_feedback',
                      'topic_historical_feedback','cluster_memory','legacy_feedback_reference'):
            if field in next(iter(scoped.values())):meta[field] = copy.deepcopy(next(iter(scoped.values()))[field])
        for key in ('normal_generation_source_ref', 'normal_factual_revision_ref', 'normal_completed_target_checkpoint_ref',
                    'rendered_quality_revision', 'target_adaptation_ref', 'platform_drafts', 'platform_render_evidence',
                    'quality_gate', 'native_quality', 'final_quality_evidence', 'platform_quality_gates',
                    'current_visual_plan_ref', 'quality_scores', 'humanized_copy'):
            meta.pop(key, None)
        meta['caption_revision_source_ref'] = copy.deepcopy(proof_ref)
        meta['quality_scores'] = _score(draft['body'], meta)
        meta['quality_gate'] = quality_gate(meta['quality_scores'])
        runner.succeeded('bind_inherited_primary_content', {'parent_job_id': parent['id'],
            'parent_draft_id': proof['parent_draft_id'], 'body_sha256': hashlib.sha256(draft['body'].encode()).hexdigest(),
            'new_primary_generation': False, 'historical_fact_observation_times_preserved': True})
        self._validate_draft_structure(draft)
        self._validate_real_world_ai_package(job, job['brief'], draft, runner)
        claims = validate_claims(draft['title'] + '\n' + draft['body'], job['brief'].get('claim_ledger') or [])
        depth = validate_content_depth_plan(meta.get('content_depth_plan'))
        if claims.get('passed') is not True or depth.get('passed') is not True:
            runner.block('validate_inherited_content_facts_depth', 'caption_historical_facts_not_currently_qualified',
                         '历史事实或深度不能按当前规则接受', {'claims': claims, 'depth': depth})
        runner.succeeded('validate_inherited_content_facts_depth', {'claims': claims, 'depth': depth})
        geo = runner.run('run_fact_check', lambda: geo_check(draft['title'] + '\n' + draft['body']), require_output=True)
        self.store.save_geo_score(job_id, geo)
        risk = runner.run('run_safety_gate', lambda: self.risk.evaluate(draft['title'] + '\n' + draft['body']), require_output=True)
        compliance = self.compliance.evaluate(draft['body'], job['brief'], job['platforms'])
        if risk.get('level') == 'block' or compliance.get('level') == 'block':
            runner.block('run_safety_gate', 'caption_historical_content_safety_blocked', '当前安全门拒绝', {'risk': risk, 'compliance': compliance})
        meta['geo_details'] = geo;meta['geo_score'] = geo['score']
        meta['target_adaptation_ref'] = runner.run('generate_caption_revision',
            lambda: generate_target_adaptation(self, job, draft, job['brief'], runner), require_output=True)
        self._validate_target_publication_copy(job_id, job, job['brief'], draft, job['brief'].get('claim_ledger') or [], runner)
        validate_caption_revision(self.store, proof_ref, child_id=job_id, live=True)
        self.store.save_draft(job_id, draft['title'], draft['body'], risk['level'], risk,
                              draft.get('prompt_version') or '', meta)
        # Copy exact pixels into the child's owned artifact root; preserve all old receipts.
        root = self.data_dir / 'artifacts' / job_id
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        copied = {}
        for original in history['artifacts']:
            if original['kind'] not in {'image', 'cover'}:
                continue
            source = Path(original['path']); raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != original['checksum']:
                raise ValueError('caption_revision_parent_pixel_changed')
            target = root / source.name
            with target.open('xb') as stream:
                os.chmod(target, 0o600);stream.write(raw)
            copied[str(source)] = {'path': str(target), 'checksum': original['checksum'], 'kind': original['kind']}
            self.store.add_artifact(job_id, original['kind'], str(target), original['checksum'])
            self.store.record_event(job_id, 'caption_revision_pixel_lineage',
                {'parent_job_id': parent['id'], 'parent_artifact_id': original['id'], 'path': str(target),
                 'checksum': original['checksum'], 'new_capture': False, 'new_render': False})
        # The wrapper records a new binding, not a new source capture or render.
        from .target_adaptation import read_target_adaptation
        child = self.store.get_job(job_id);target_copy = read_target_adaptation(child, 'twitter')
        wrapper = {'version': 'caption_revision_inherited_visual_binding_v1', 'job_id': job_id,
            'current_task_id': _CAPTION_ACTIVE[(id(self.store),job_id)]['task'],
            'proof_ref': proof_ref, 'parent_job_id': parent['id'], 'parent_draft_id': proof['parent_draft_id'],
            'original_plan_ref': history['plan_ref'], 'target_copy_ref': target_copy['target_copy_ref'],
            'caption_sha256': target_copy['caption_sha256'], 'pixels': copied,
            'new_source_capture': False, 'new_pixel_render': False}
        wrapper_ref = write_once(root / 'inherited-visual-binding.private.json', wrapper)
        meta = copy.deepcopy(child['draft_meta']);meta['current_visual_plan_ref'] = wrapper_ref
        self.store.save_draft(job_id, draft['title'], draft['body'], risk['level'], risk,
                              draft.get('prompt_version') or '', meta)
        child = self.store.get_job(job_id)
        plan, _ = self.media._current_image_text_plan(child)
        images = []
        for slot in plan['slots']:
            # Parent output ordering is checked against its original render manifest.
            candidates = [r for r in history['outputs'] if r.get('role') == ('cover' if slot['role'] == 'cover' else 'image')]
            originals = [r for r in history['artifacts'] if any(r['id'] == o.get('artifact_id') for o in candidates)]
            if slot['role'] == 'cover':
                if len(originals) != 1:raise ValueError('caption_revision_unique_cover_required')
                source = originals[0]
            else:
                image_slots = [s for s in plan['slots'] if s['role'] != 'cover']
                source = originals[image_slots.index(slot)]
            bound = copied[source['path']]
            images.append(dict(bound, role=slot['role'], section=slot['id']))
        originals = {a['kind']: a for a in history['artifacts'] if a['kind'] in {'rights', 'render_manifest'}}
        if set(originals) != {'rights', 'render_manifest'}:
            raise ValueError('caption_revision_original_manifest_and_rights_required')
        rights = json.loads(Path(originals['rights']['path']).read_text())
        rights.update(job_id=job_id, plan_ref=wrapper_ref,
                      inherited_from={'path': originals['rights']['path'], 'sha256': originals['rights']['checksum']},
                      new_rights_claim=False)
        rights_ref = write_once(root / 'rights.private.json', rights)
        manifest = json.loads(Path(originals['render_manifest']['path']).read_text())
        manifest.update(job_id=job_id, plan_ref=wrapper_ref, rights=rights_ref, new_pixel_render=False,
                    inherited_from={'parent_job_id': parent['id'], 'original_plan_ref': history['plan_ref'],
                                    'render_manifest': {'path': originals['render_manifest']['path'],
                                                        'sha256': originals['render_manifest']['checksum']}},
                    images=[{'role': r['role'], 'file': {'path': r['path'], 'sha256': r['checksum']}} for r in images])
        manifest_ref = write_once(root / 'render-manifest.private.json', manifest)
        auxiliary = []
        for kind, ref in [('rights', rights_ref), ('render_manifest', manifest_ref)]:
            self.store.add_artifact(job_id, kind, ref['path'], ref['sha256'])
            auxiliary.append({'kind': kind, 'path': ref['path'], 'checksum': ref['sha256']})
        generated = {'kind': 'image', 'images': images, 'current_visual_plan_ref': wrapper_ref,
                     'auxiliary_artifacts': auxiliary, 'new_source_capture': False, 'new_pixel_render': False}
        self._validate_image_requirements(job_id, runner, generated)
        self._validate_strict_article_completion(job_id, self.store.get_job(job_id), runner)
        gate = self._quality_gate(job_id, self.store.get_job(job_id), risk, geo, phase='generation')
        if gate.get('passed') is not True:
            runner.block('run_quality_gate', 'caption_current_generation_quality_failed', '新修订当前生成门不通过', gate)
        runner.succeeded('run_quality_gate', gate, depends_on=['run_safety_gate'])
        validate_caption_revision(self.store, proof_ref, child_id=job_id, live=True)
        return self.continue_rendered_candidate(job_id, owner, runner, generated, {})

