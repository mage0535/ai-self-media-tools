import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from .compliance import ComplianceChecker
from .claim_ledger import sanitize_unsupported_claims, validate_claims
from .content_depth import validate_content_depth_plan
from .content_hygiene import audit_topic, validate_generated_text
from .content_policy import SHORT_VIDEO_PLATFORMS, generated_media_kinds_for_job
from .capability_runtime import execute_generation_capabilities, execute_post_generation_capabilities
from .execution_trace import build_pre_delivery_trace, complete_delivery_trace
from .delivery_health import delivery_health_decision
from .formatters import format_for_platform
from .generator import DraftGenerator
from .humanize import naturalize_copy, repair_weak_hook
from .intelligence import GLOBAL_EN_PLATFORMS, build_generation_context
from .media import MediaBridge
from .adapters.media import (
    probe_final_video,
    validate_bgm_contract,
    validate_handoff_contract,
    validate_scene_manifest_contract,
    validate_tts_fingerprint,
)
from .media_quality import (
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
from .publication_ledger import PublicationLedger
from .profiles import resolve_profile
from .publishers import build_publisher
from .resource import ResourceGuard
from .review import ReviewTokens
from .risk import RiskFilter, redact_secrets
from .growth_recipe import validate_growth_recipe
from .seo import geo_check
from .wechat_toolchain import prepare_wechat_professional_draft, requires_wechat_toolchain
from .workflow_runtime import (
    WorkflowBlocked,
    WorkflowStepRunner,
    strict_workflow_lock,
    write_platform_report,
)
from .platform_workflow_context import load_platform_workflow_context


class Pipeline:
    def __init__(self, store, config=None):
        self.store = store
        self.config = config or {}
        self.publication_ledger = getattr(store, "publication_ledger", PublicationLedger(store.path))
        self.data_dir = Path(self.config.get("data_dir", store.path.parent))
        self.generator = DraftGenerator(self.config.get("generator", {}))
        self.compliance = ComplianceChecker()
        risk_cfg = self.config.get("risk", {})
        self.risk = RiskFilter(
            risk_cfg.get("block_words"), risk_cfg.get("review_words"), risk_cfg.get("legacy_script", ""), risk_cfg.get("timeout", 20)
        )
        self.guard = ResourceGuard(self.data_dir, self.config.get("resources", {}))
        self.media = MediaBridge(self.config.get("media", {}), self.data_dir, self.guard)
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

    def create(self, topic, platforms, brief=None, profile="default", topic_fingerprint=""):
        platforms = list(dict.fromkeys(str(p).strip() for p in platforms if str(p).strip()))
        explicit_brief = brief or {}
        resolved = resolve_profile(self.config.get("profiles", {}), profile, explicit_brief)
        resolved["platforms"] = platforms
        if len(platforms) == 1:
            resolved.setdefault("platform", platforms[0])
        explicit_language = any(key in explicit_brief for key in ("language", "locale", "language_locked"))
        if platforms and all(str(p).casefold() in GLOBAL_EN_PLATFORMS for p in platforms) and not explicit_language:
            resolved["language"] = "en"
        return self.store.create_job(topic, platforms, resolved, profile, topic_fingerprint)

    def run(self, job_id, force=False):
        job = self.store.get_job(job_id)
        if job["state"] != "created" and not force:
            return self._hydrate(job)
        if force and job["state"] not in {"created", "failed", "blocked", "rejected"}:
            raise ValueError(f"cannot force generation from state: {job['state']}")
        owner = self._worker_id()
        workflow_id = f"wf_{job_id}"
        with strict_workflow_lock(self.store, owner, workflow_id, self.lock_timeout_seconds, self.strict_serial):
            if not self.store.claim(job_id, {job["state"]}, owner, 900, "generating"):
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
                self.generator.config["generation_attempts_path"] = str(self.data_dir / "jobs" / job_id / "generation_attempts.json")
                self.generator.config["checkpoint_dir"] = str(self.data_dir / "jobs" / job_id)
                if len(platform_contexts) == 1:
                    platform_name = str(next(iter(platform_contexts)))
                    platform_context = next(iter(platform_contexts.values()))
                    compiled = platform_context.get("strategy", {}).get("compiled")
                    if isinstance(compiled, dict):
                        brief["strategy_compiled"] = compiled
                        brief["strategy"] = compiled
                        contract = brief.get("run_contract")
                        if not isinstance(contract, dict):
                            from .run_contract import build_run_contract
                            contract = build_run_contract(str(next(iter(platform_contexts))))
                            brief["run_contract"] = contract
                        if isinstance(contract, dict):
                            from .run_contract import bound_stage_payload
                            from .content_quality_reference import load_content_quality_reference_pack
                            from .strategy_compiler import compact_compiled_strategy
                            from .same_lane_intelligence import latest_same_lane_playbook

                            quality_reference = platform_context.get("content_quality_reference_pack")
                            if not isinstance(quality_reference, dict) or quality_reference.get("loaded") is not True:
                                quality_reference = load_content_quality_reference_pack(
                                    platform_name,
                                    content_form=str((brief.get("content_blueprint") or {}).get("content_form") or brief.get("content_form") or ""),
                                )
                            brief["bounded_model_input"] = bound_stage_payload(
                                contract,
                                "generate",
                                {
                                    "content_blueprint": brief.get("content_blueprint") or {},
                                    "claim_ledger": list(brief.get("claim_ledger") or []),
                                    "tool_selection_plan": dict(brief.get("tool_selection_plan") or {}),
                                    "strategy": compact_compiled_strategy(compiled),
                                    "content_quality_reference_pack": quality_reference,
                                    "runtime_capabilities": platform_context.get("runtime_capabilities") or {},
                                    "same_lane_intelligence": latest_same_lane_playbook(self.store, platform_name),
                                },
                            )
                if len(platform_contexts) == 1:
                    platform_name = str(next(iter(platform_contexts)))
                    from .capability_context import build_generation_capability_context
                    capability_context = build_generation_capability_context(
                        platform_name,
                        brief.get("content_blueprint") or {
                            "topic": job.get("topic") or "",
                            "content_form": brief.get("content_form") or "",
                        },
                    )
                    brief["content_profile"] = capability_context["profile"]
                    brief["capability_plan"] = capability_context["capability_plan"]
                    brief["tool_selection"] = capability_context["tool_selection"]
                    brief["compiled_skill_rules"] = capability_context["compiled_skill_rules"]
                    contract = brief.get("run_contract")
                    if isinstance(contract, dict):
                        from .run_contract import bound_stage_payload
                        brief["bounded_model_input"] = bound_stage_payload(
                            contract,
                            "generate",
                            {
                                **dict(brief.get("bounded_model_input") or {}),
                                "content_profile": capability_context["profile"],
                                "capability_plan": capability_context["capability_plan"],
                                "tool_selection": capability_context["tool_selection"],
                                "compiled_skill_rules": capability_context["compiled_skill_rules"],
                            },
                        )
                runner.succeeded("run_operation_strategy", {"historical_feedback": bool(brief.get("historical_feedback"))}, depends_on=["load_content_strategy"])
                # Check if job has pre-populated body content (manually written, not a stub)
                existing_body = (job.get("body") or "").strip()
                if len(existing_body) > 100:
                    # Use pre-populated content directly; run naturalize_copy for quality scoring
                    ctx = build_generation_context(job["topic"], brief)
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
                    draft = runner.run("generate_content", lambda: self.generator.generate(job["topic"], brief), depends_on=["run_operation_strategy"], require_output=True)
                capability_execution = runner.run(
                    "execute_generation_capabilities",
                    lambda: execute_generation_capabilities(draft, brief),
                    depends_on=["generate_content"],
                    require_output=True,
                )
                draft.setdefault("draft_meta", {})["capability_execution"] = capability_execution
                for context_key in ("content_profile", "capability_plan", "tool_selection", "compiled_skill_rules"):
                    if brief.get(context_key) is not None:
                        draft["draft_meta"][context_key] = brief[context_key]
                tool_selection = brief.get("tool_selection") if isinstance(brief.get("tool_selection"), dict) else {}
                draft["draft_meta"]["tools_capability_analysis"] = tool_selection.get("tools_capability_analysis") or {}
                draft["draft_meta"]["tool_selection_plan_original"] = tool_selection.get("tool_selection_plan") or brief.get("tool_selection_plan") or {}
                workflow_invocations = {
                    "load_platform_workflow_context": {"status": "ok", "evidence": "workflow_step_succeeded"},
                    "load_content_strategy": {"status": "ok", "evidence": "workflow_step_succeeded"},
                    "run_operation_strategy": {"status": "ok", "evidence": "workflow_step_succeeded"},
                    "generate_content": {"status": "ok", "evidence": "workflow_step_succeeded"},
                    "execute_generation_capabilities": {"status": "ok" if capability_execution.get("passed") else "failed", "evidence": capability_execution.get("executed", [])},
                }
                capability_planned = [
                    str(item.get("capability_id") or "")
                    for item in capability_execution.get("planned") or []
                    if isinstance(item, dict) and str(item.get("capability_id") or "")
                ]
                executed_by_id = {
                    str(item.get("capability_id")): item
                    for item in capability_execution.get("executed") or []
                    if isinstance(item, dict) and item.get("capability_id")
                }
                draft["draft_meta"]["tool_selection_plan"] = {
                    "version": "tool_selection_plan_v3",
                    "selected_tools": capability_planned,
                    "selection_reasons": {name: "selected by the registry for the generation-stage capability DAG" for name in capability_planned},
                    "invocation_order": capability_planned,
                    "not_default_only": True,
                }
                draft["draft_meta"]["tool_invocation_manifest"] = {
                    "version": "tool_invocation_manifest_v3",
                    "planned_tools": {name: "capability_registry" for name in capability_planned},
                    "invocations": {
                        name: {
                            "status": "ok" if name in executed_by_id else "failed",
                            "output_hash": (executed_by_id.get(name) or {}).get("output_hash", ""),
                            "evidence": executed_by_id.get(name) or {},
                        }
                        for name in capability_planned
                    },
                    "executed_count": len(executed_by_id),
                    "missing_tools": [name for name in capability_planned if name not in executed_by_id],
                    "capability_execution": capability_execution,
                }
                draft["draft_meta"]["workflow_stage_manifest"] = {
                    "version": "workflow_stage_manifest_v1",
                    "stages": workflow_invocations,
                }
                generated_hygiene = validate_generated_text(str(draft.get("title") or "") + "\n" + str(draft.get("body") or ""))
                draft.setdefault("draft_meta", {})["generated_text_hygiene"] = generated_hygiene
                if not generated_hygiene.get("passed"):
                    runner.block(
                        "validate_content_structure",
                        "source_page_code_contamination",
                        "generated text contains scraped page code or script payload",
                        generated_hygiene,
                        depends_on=["generate_content", "execute_generation_capabilities"],
                    )
                if brief.get("automated_workflow") and not capability_execution.get("passed"):
                    runner.block(
                        "execute_generation_capabilities",
                        "required_capability_not_executed",
                        "automated workflow selected capabilities without valid execution evidence",
                        capability_execution,
                        depends_on=["generate_content"],
                    )
                if requires_wechat_toolchain(self.config, job["platforms"]):
                    draft = runner.run(
                        "prepare_wechat_professional_toolchain",
                        lambda: prepare_wechat_professional_draft(job_id, job, draft, self.config, self.data_dir),
                        depends_on=["generate_content"],
                        require_output=True,
                    )
                    wewrite_status = ((draft.get("draft_meta") or {}).get("tool_invocations") or {}).get("wewrite", {}).get("status")
                    if wewrite_status != "used":
                        runner.block(
                            "prepare_wechat_professional_toolchain",
                            "wechat_toolchain_unavailable",
                            "WeChat production workflow requires successful WeWrite llm-write evidence",
                            ((draft.get("draft_meta") or {}).get("tool_invocations") or {}).get("wewrite", {}),
                            depends_on=["generate_content"],
                        )
                self._validate_draft_structure(draft)
                platform_alignment = self._enforce_target_platform_strategy(draft, job)
                draft.setdefault("draft_meta", {})["platform_alignment"] = platform_alignment
                runner.succeeded("validate_content_structure", {"title_present": bool(draft.get("title")), "body_chars": len(str(draft.get("body", ""))), "platform_alignment": platform_alignment}, depends_on=["generate_content"])
                self._persist_intelligence(job_id, draft.get("draft_meta", {}))
                text = draft["title"] + "\n" + draft["body"]
                claim_ledger = (draft.get("draft_meta") or {}).get("claim_ledger") or brief.get("claim_ledger") or []
                claim_gate = validate_claims(text, claim_ledger)
                draft.setdefault("draft_meta", {})["claim_gate"] = claim_gate
                strict_claims = bool((job.get("brief") or {}).get("run_contract")) or str((job.get("brief") or {}).get("selection_mode") or "") == "editorial_calendar"
                if not claim_gate.get("passed") and strict_claims:
                    cleaned_title = sanitize_unsupported_claims(draft["title"], claim_gate.get("findings")) or str(job.get("topic") or "Verified workflow")
                    cleaned_body = sanitize_unsupported_claims(draft["body"], claim_gate.get("findings"))
                    cleaned_gate = validate_claims(cleaned_title + "\n" + cleaned_body, claim_ledger)
                    if len(cleaned_body) >= 80 and cleaned_gate.get("passed"):
                        draft["title"] = cleaned_title
                        draft["body"] = cleaned_body
                        text = cleaned_title + "\n" + cleaned_body
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
                current_quality = (draft.get("draft_meta") or {}).get("quality_gate") or {}
                if "hook_strength" in set(current_quality.get("failed_dimensions") or []):
                    repaired = repair_weak_hook(draft.get("title"), draft.get("body"), draft.get("draft_meta") or {})
                    if repaired.get("changed"):
                        draft["body"] = repaired["body"]
                        draft["draft_meta"]["quality_scores"] = repaired["quality_scores"]
                        draft["draft_meta"]["quality_gate"] = repaired["quality_gate"]
                        draft["draft_meta"]["hook_repair"] = {
                            "version": "deterministic_hook_repair_v1",
                            "hook": repaired["hook"],
                            "passed": repaired["quality_gate"].get("passed") is True,
                        }
                gate = self._quality_gate(job_id, draft, risk, geo, phase="generation", platforms=job.get("platforms"))
                draft["draft_meta"]["geo_score"] = geo["score"]
                draft["draft_meta"]["geo_details"] = geo
                draft["draft_meta"]["quality_gate"] = gate
                if self.require_gate_pass and not gate.get("passed", True):
                    runner.block("run_quality_gate", "quality_gate_failed", "required quality gate failed", gate, depends_on=["run_safety_gate"])
                if not gate.get("passed", True):
                    risk["level"] = "review"
                runner.succeeded("run_quality_gate", gate, depends_on=["run_safety_gate"])
            # Humanizer-zh: 草稿 AI 去痕处理
                humanize_enabled = self.config.get("humanizer", {}).get("enabled", True)
                if humanize_enabled and risk["level"] == "pass":
                    self._humanize_draft(job_id, draft)
                self.store.save_draft(
                    job_id, draft["title"], draft["body"], risk["level"], risk, draft.get("prompt_version", ""), draft.get("draft_meta", {})
                )
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
                    self._generate_optional_media(job_id, "illustration", runner, ["collect_or_prepare_materials"])
            # gzh-design：Markdown → 公众号 HTML 格式转换
                gzh_enabled = self.config.get("media", {}).get("wechat_format", {}).get("enabled", False)
                if gzh_enabled and any("wechat" in p.lower() for p in job.get("brief", {}).get("platforms", job.get("platforms", []))):
                    self._generate_optional_media(job_id, "wechat_format", runner, ["collect_or_prepare_materials"])
            # magazine-layout：Markdown → 杂志风格 HTML（独立文章页）
                magazine_enabled = self.config.get("media", {}).get("magazine_format", {}).get("enabled", False)
                if magazine_enabled and any(p not in ("wechat", "weixin") for p in job.get("brief", {}).get("platforms", job.get("platforms", []))):
                    self._generate_optional_media(job_id, "magazine_format", runner, ["collect_or_prepare_materials"])
                generated_image = self._generate_optional_media(job_id, "image", runner, ["collect_or_prepare_materials"], step_name="generate_or_collect_images")
                self._validate_image_requirements(job_id, runner, generated_image)
                generated_kinds = set(generated_media_kinds_for_job(self.store.get_job(job_id), self.config))
                generated_kinds.discard("image")
                for kind in generated_kinds:
                    artifact = self._generate_optional_media(job_id, kind, runner, ["validate_image_requirements"])
                    if kind == "video" and artifact:
                        self._attach_video_render_evidence(draft, artifact)
                final_gate = self._quality_gate(job_id, draft, risk, geo, phase="rendered", platforms=job.get("platforms"))
                draft["draft_meta"]["quality_gate"] = final_gate
                if self.require_gate_pass and not final_gate.get("passed", True):
                    runner.block(
                        "run_final_platform_quality_gate",
                        "final_platform_quality_gate_failed",
                        "rendered media did not satisfy required platform quality gate",
                        final_gate,
                        depends_on=["validate_image_requirements"],
                    )
                runner.succeeded("run_final_platform_quality_gate", final_gate, depends_on=["validate_image_requirements"])
                current_job = self.store.get_job(job_id)
                artifacts = self.store.artifacts(job_id)
                image_required = self._media_required("image", self.config.get("media", {}).get("image", {}), current_job)
                video_required = self._media_required("video", self.config.get("media", {}).get("video", {}), current_job)
                capability_execution = execute_post_generation_capabilities(
                    capability_execution,
                    draft,
                    brief,
                    artifacts=artifacts,
                    render_manifest=(draft.get("draft_meta") or {}).get("render_manifest") or {},
                    quality_gate=final_gate,
                )
                draft["draft_meta"]["capability_execution"] = capability_execution
                draft["draft_meta"]["execution_trace"] = build_pre_delivery_trace(
                    capability_execution=capability_execution,
                    artifacts=artifacts,
                    assets_required=bool(image_required or video_required),
                    render_manifest=(draft.get("draft_meta") or {}).get("render_manifest") or {},
                    render_required=bool(video_required),
                    quality_gate=final_gate,
                )
                if brief.get("automated_workflow") and draft["draft_meta"]["execution_trace"].get("passed") is False:
                    runner.block(
                        "run_final_platform_quality_gate",
                        "canonical_execution_trace_failed",
                        "selected required capabilities lack real execution or artifact evidence",
                        draft["draft_meta"]["execution_trace"],
                        depends_on=["validate_image_requirements"],
                    )
                self.store.save_draft(
                    job_id, draft["title"], draft["body"], risk["level"], risk, draft.get("prompt_version", ""), draft.get("draft_meta", {})
                )
                reviewed = self.store.release_claim(job_id, owner, "review_required", "review_requested", detail={"risk": risk["level"]})
                if self.config.get("delivery", {}).get("auto_stage_review_required"):
                    reviewed = self.stage_drafts(job_id, owner=owner, already_locked=True)
                # Approval tokens are issued only by the authenticated review
                # command. They must never be written to logs or notifications.
                self.notifier.send("review_required", reviewed)
                return self._hydrate(reviewed)
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

    def publish(self, job_id):
        job = self._hydrate(self.store.get_job(job_id))
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
                for platform in job["platforms"]:
                    self.store.enqueue_delivery(job_id, platform, "publish", {"state": job["state"]})
                processed = self.process_delivery_queue(owner=owner, already_locked=True, limit=len(job["platforms"]))
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
            # Explicit staging is a recovery request. Requeue stale completed
            # records, while process_delivery_queue still enforces idempotency
            # against an existing published/drafted receipt.
            self.store.enqueue_delivery(job_id, platform, "stage", {"state": job["state"], "retry": True})
        self.process_delivery_queue(owner=owner, already_locked=already_locked, limit=1)
        return self._hydrate(self.store.get_job(job_id))

    def process_delivery_queue(self, limit=1, owner=None, already_locked=False):
        processed = 0
        owner = owner or self._worker_id()
        workflow_id = "wf_delivery_queue"
        with strict_workflow_lock(self.store, owner, workflow_id, self.lock_timeout_seconds, self.strict_serial and not already_locked):
            while processed < int(limit):
                item = self.store.claim_delivery(owner, 300)
                if not item:
                    break
                job = self._hydrate(self.store.get_job(item["job_id"]))
                platform = item["platform"]
                action = item.get("action", "publish")
                runner = WorkflowStepRunner(self.store, f"wf_{item['job_id']}", item["job_id"], platform=platform, notifier=self.notifier)
                prior = next((delivery for delivery in job["deliveries"] if delivery["platform"] == platform), None)
                if prior and prior["status"] in {"drafted", "published", "handoff_pending"}:
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
                    lambda: format_for_platform(job, platform),
                    depends_on=[],
                    require_output=True,
                )
                try:
                    result = self._deliver(platform, delivery_job, action)
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
                            "FAILED_RETRYABLE",
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
                        self.store.complete_delivery(item["id"], owner, "queued", result.error)
                        processed += 1
                        continue
                    if result.status == "handoff_pending":
                        handoff_gate = self._post_delivery_handoff_gate(delivery_job, platform)
                        if not handoff_gate.get("passed", True):
                            result = DeliveryResult(False, "blocked", result.external_id, error="handoff contract gate failed: " + json.dumps(handoff_gate, ensure_ascii=False))
                            self._save_delivery_result(item["job_id"], platform, result)
                            runner.store.save_workflow_step(
                                runner.workflow_id,
                                runner.job_id,
                                runner.platform,
                                "publish_or_create_draft",
                                "BLOCKED",
                                required=True,
                                depends_on=["run_platform_pre_publish_gate"],
                                reason_code="handoff_contract_failed",
                                message=result.error,
                                gate_result=handoff_gate,
                            )
                            report = write_platform_report(self.store, self.data_dir, f"wf_{item['job_id']}", job, platform, "blocked", result.__dict__, result.error)
                            runner.succeeded("generate_platform_report", report, depends_on=["publish_or_create_draft"])
                            self._send_platform_report(job, platform, report)
                            runner.succeeded("send_completion_report", {"report_path": report["path"]}, depends_on=["generate_platform_report"])
                            self.store.complete_delivery(item["id"], owner, "queued", result.error)
                            processed += 1
                            continue
                    runner.succeeded("publish_or_create_draft", {"status": result.status, "external_id_present": bool(result.external_id)}, depends_on=["run_platform_pre_publish_gate"])
                    self._save_delivery_result(item["job_id"], platform, result)
                    self._complete_execution_trace(job, platform, result)
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
                    self.store.complete_delivery(item["id"], owner, "completed", str(exc))
                except Exception as exc:
                    self.store.complete_delivery(item["id"], owner, "queued", redact_secrets(exc))
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
            jobs = self.store.list_jobs(limit=limit, state=state)
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

    def _enrich_brief(self, job, hygiene=None):
        brief = dict(job.get("brief", {}))
        platforms = list(job.get("platforms", []))
        topic = job.get("topic", "")
        platform_history = self.store.historical_performance(platforms, "")
        topic_history = self.store.historical_performance(platforms, topic)
        historical = dict(platform_history)
        historical["topic_history"] = topic_history
        brief.setdefault("historical_feedback", historical)
        brief.setdefault("platform_historical_feedback", platform_history)
        brief.setdefault("topic_historical_feedback", topic_history)
        brief.setdefault("cluster_memory", topic_history.get("clusters", []) or platform_history.get("clusters", []))
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
        hygiene = audit_topic(job.get("topic", ""), candidates, self.content_hygiene_cfg)
        self.store.record_event(job["id"], "content_hygiene_checked", {"content_hygiene": hygiene})
        return hygiene

    def _publisher_config(self, platform):
        publishers = self.config.get("publishers", {}) or {}
        return (publishers.get("platforms", {}) or {}).get(platform) or publishers.get("default", {}) or {}

    def _delivery_intent_payload(self, platform, job, action):
        formatted = job.get("platform_payload") or format_for_platform(job, platform)
        cfg = self._publisher_config(platform)
        alias = str(cfg.get("account_name") or cfg.get("account_id") or cfg.get("account") or "default")
        media_hashes = []
        for artifact in job.get("artifacts") or []:
            checksum = str(artifact.get("checksum") or "")
            path = Path(str(artifact.get("path") or ""))
            if not checksum and path.is_file():
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if checksum:
                media_hashes.append(checksum)
        description = str(formatted.get("description") or formatted.get("caption") or formatted.get("text") or formatted.get("markdown") or job.get("body") or "")
        scheduled_at = str(
            job.get("scheduled_at")
            or job.get("schedule_at")
            or (job.get("brief") or {}).get("scheduled_at")
            or cfg.get("scheduled_at")
            or cfg.get("schedule_at")
            or ""
        )
        return {
            "job_id": str(job.get("id") or ""),
            "platform": platform,
            "internal_account_alias": alias,
            "action": action,
            "payload": formatted,
            "media_hashes": media_hashes,
            "expected_title": str(formatted.get("title") or job.get("title") or ""),
            "expected_description": description,
            "scheduled_at": scheduled_at,
            "idempotency_key": f"delivery:{job.get('id', '')}:{platform}:{action}",
            "absence_window_seconds": int((self.config.get("delivery") or {}).get("absence_window_seconds", 3600)),
        }

    @staticmethod
    def _result_metadata(result):
        metadata = getattr(result, "metadata", None) or getattr(result, "details", None) or {}
        return metadata if isinstance(metadata, dict) else {}

    @staticmethod
    def _unknown_status(exc):
        text = str(exc).casefold()
        if any(token in text for token in ("auth", "login", "cookie", "conflict", "inconclusive")):
            return "unknown_requires_review"
        return "unknown"

    def _deliver(self, platform, job, action="publish", intent=None):
        if str(platform).casefold() == "juejin":
            # The store keeps local paths/checksums; merge the renderer-written
            # public URLs only at delivery time so the publisher receives the
            # same versioned article media contract that was generated.
            contract_path = self.data_dir / "artifacts" / str(job.get("id") or "") / "article_media_contract.json"
            if not contract_path.is_file():
                return DeliveryResult(False, "blocked", error="juejin article media contract missing")
            if contract_path.is_file():
                try:
                    contract = json.loads(contract_path.read_text(encoding="utf-8"))
                    handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
                    pre_delivery = validate_handoff_contract(handoff, require_target_renderer=False)
                    if not pre_delivery.get("passed"):
                        return DeliveryResult(False, "blocked", error="juejin media pre-delivery gate failed: " + json.dumps(pre_delivery, ensure_ascii=False))
                    by_path = {str(row.get("path")): row for row in contract.get("assets") or [] if isinstance(row, dict)}
                    delivery_job = dict(job)
                    artifacts = []
                    for artifact in job.get("artifacts") or []:
                        enriched = dict(artifact)
                        source = by_path.get(str(artifact.get("path")))
                        if source:
                            enriched.update({"url": source.get("public_url"), "public_url": source.get("public_url"), "source_url": source.get("source_url"), "license": source.get("license"), "kind": "cover" if source.get("role") == "cover" else "image"})
                        artifacts.append(enriched)
                    delivery_job["artifacts"] = artifacts
                    metadata = dict(job.get("draft_meta") or {})
                    metadata["section_image_map"] = contract.get("section_image_map") or []
                    metadata["article_media_contract"] = contract
                    metadata["article_media_contract_path"] = str(contract_path)
                    delivery_job["draft_meta"] = metadata
                    if isinstance(job.get("platform_payload"), dict):
                        payload = dict(job["platform_payload"])
                        payload["section_image_map"] = metadata["section_image_map"]
                        public_artifacts = delivery_job.get("artifacts") or []
                        cover = next((item.get("public_url") for item in public_artifacts if item.get("kind") == "cover" and item.get("public_url")), "")
                        inline = [item.get("public_url") for item in public_artifacts if item.get("kind") == "image" and item.get("public_url")]
                        payload["cover_image"] = cover
                        payload["inline_image_urls"] = inline
                        payload["public_inline_image_urls"] = inline
                        delivery_job["platform_payload"] = payload
                    job = delivery_job
                except (OSError, json.JSONDecodeError) as exc:
                    return DeliveryResult(False, "blocked", error=f"juejin article media contract unreadable:{type(exc).__name__}")
        intent = intent or self.publication_ledger.create_delivery_intent(self._delivery_intent_payload(platform, job, action))
        intent_id = intent["intent_id"]
        if intent.get("status") == "unknown_requires_review":
            return DeliveryResult(False, "unknown_requires_review", error=intent.get("review_reason") or "delivery requires review")
        if intent.get("status") == "unknown" and not intent.get("retry_allowed"):
            return DeliveryResult(False, "unknown", error="delivery outcome is unknown; poll immutable identity before retry")
        decision = delivery_health_decision(platform, self.config, action)
        if not decision.ok:
            self.publication_ledger.record_delivery_result(intent_id, {"status": "blocked", "error": decision.error()})
            return DeliveryResult(False, "blocked", error=decision.error())
        attempt = self.publication_ledger.begin_attempt(intent_id, self._worker_id())
        publisher = build_publisher(platform, self.config, self.data_dir)
        callback_events = {}
        callback = getattr(publisher, "set_delivery_callback", None)
        if callable(callback):
            def on_delivery_event(event):
                if isinstance(event, dict):
                    callback_events.update(event)
                return self.publication_ledger.record_delivery_callback(intent_id, event)

            callback(on_delivery_event)
        try:
            result = publisher.deliver(job, platform)
        except Exception as exc:
            status = self._unknown_status(exc)
            message = redact_secrets(exc)
            self.publication_ledger.finish_attempt(intent_id, attempt["attempt_id"], status, error=message)
            return DeliveryResult(False, status, error=message)
        metadata = dict(callback_events)
        metadata.update(self._result_metadata(result))
        if str(platform).casefold() == "juejin" and result.ok:
            contract_path = self.data_dir / "artifacts" / str(job.get("id") or "") / "article_media_contract.json"
            try:
                in_memory = (job.get("draft_meta") or {}).get("article_media_contract")
                contract = in_memory if isinstance(in_memory, dict) else json.loads(contract_path.read_text(encoding="utf-8"))
                handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
                renderer_evidence = metadata.get("target_renderer_evidence") or metadata.get("editor_postcheck")
                if isinstance(renderer_evidence, dict):
                    handoff["target_renderer_evidence"] = renderer_evidence
                post_delivery = validate_handoff_contract(handoff)
                contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError) as exc:
                post_delivery = {"passed": False, "failures": [f"handoff_contract_unreadable:{type(exc).__name__}"]}
            if not post_delivery.get("passed"):
                result = DeliveryResult(
                    False, "blocked", result.external_id,
                    "juejin renderer visibility gate failed: " + json.dumps(post_delivery, ensure_ascii=False),
                )
                metadata["postcheck"] = post_delivery
        if not result.ok and result.status not in {"blocked", "drafted", "handoff_pending", "review_required", "unknown_requires_review", "scheduled"}:
            status = self._unknown_status(RuntimeError(result.error or result.status))
            result = DeliveryResult(False, status, result.external_id, result.error)
        verified_identity = None
        if result.status == "published" and not metadata.get("verification"):
            result = DeliveryResult(False, "unknown_requires_review", result.external_id, "publisher returned published without URL/content/account/time verification")
        elif result.status == "published":
            verified_identity = self.publication_ledger.register_verified_publication({"intent_id": intent_id, "platform": platform, **metadata["verification"]})
            if not verified_identity.get("passed"):
                result = DeliveryResult(False, "unknown_requires_review", result.external_id, "publisher returned invalid publication verification: " + str(verified_identity.get("reason") or "unknown"))
        if platform.casefold() == "kuaishou" and result.status == "scheduled":
            postcheck = self.publication_ledger.validate_kuaishou_scheduled_postcheck(intent, metadata.get("postcheck") or metadata)
            if not postcheck["passed"]:
                result = DeliveryResult(False, "unknown_requires_review", result.external_id, "Kuaishou scheduled management-page postcheck failed")
                metadata = {"postcheck": postcheck}
        self.publication_ledger.finish_attempt(intent_id, attempt["attempt_id"], result.status, external_id=result.external_id, error=result.error, metadata=metadata)
        if not (result.status == "published" and verified_identity and verified_identity.get("passed")):
            self.publication_ledger.record_delivery_result(intent_id, {"status": result.status, "external_id": result.external_id, "error": result.error})
        return result

    def _save_delivery_result(self, job_id, platform, result):
        key = hashlib.sha256(f"{job_id}:{platform}".encode()).hexdigest()
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
                        verification_level="postcheck_required" if result.status == "handoff_pending" else "publisher_result",
                        platform_content_id=result.external_id,
                    ),
                    job_id=job_id,
                )
                if result.status in {"handoff_pending", "drafted"}:
                    register_review_tasks(self.store, package_id, platform, job_id=job_id)

    def _complete_execution_trace(self, job, platform, result):
        meta = dict(job.get("draft_meta") or {})
        pending = meta.get("execution_trace") if isinstance(meta.get("execution_trace"), dict) else {}
        if not pending:
            return
        trace = complete_delivery_trace(
            pending,
            platform=platform,
            result={"ok": result.ok, "status": result.status, "external_id": result.external_id, "error": result.error},
        )
        meta["execution_trace"] = trace
        self.store.save_draft(
            job["id"], job.get("title") or "", job.get("body") or "", job.get("risk_level") or "pass",
            job.get("risk") or {}, job.get("prompt_version") or "", meta,
        )
        if (job.get("brief") or {}).get("automated_workflow") and not trace.get("passed"):
            raise RuntimeError("canonical execution trace failed: " + ", ".join(trace.get("failures") or []))

    def _send_platform_report(self, job, platform, report):
        payload = dict(job)
        payload["state"] = report.get("summary", {}).get("status", job.get("state", ""))
        payload["report_path"] = report.get("path", "")
        payload["title"] = f"{job.get('title') or job.get('topic', '')} [{platform}]"
        self.notifier.send("platform_report", payload)

    @staticmethod
    def _enforce_target_platform_strategy(draft, job):
        meta = draft.setdefault("draft_meta", {})
        strategy = meta.setdefault("strategy", {})
        target_platforms = [str(item).casefold() for item in (job.get("platforms") or [])]
        if not target_platforms:
            return {"changed": False, "target_platforms": []}
        before = list(strategy.get("primary_platforms") or [])
        changed = [str(item).casefold() for item in before] != target_platforms
        strategy["primary_platforms"] = target_platforms
        strategy["platforms"] = target_platforms
        if len(target_platforms) == 1:
            strategy["platform"] = target_platforms[0]
        article_platforms = {"juejin", "zhihu", "wechat", "weixin"}
        if set(target_platforms) & article_platforms and str(meta.get("content_form") or strategy.get("content_form") or "article").casefold() not in {"short_video", "tweet"}:
            meta["content_form"] = "article"
            strategy["content_form"] = "article"
            planned = list(meta.get("media_plan") or strategy.get("asset_plan") or [])
            for item in ("cover", "article"):
                if item not in planned:
                    planned.append(item)
            meta["media_plan"] = planned
            strategy["asset_plan"] = planned
        return {"changed": changed, "before": before, "target_platforms": target_platforms}

    def _validate_draft_structure(self, draft):
        if not isinstance(draft, dict):
            raise RuntimeError("content generator did not return a structured draft")
        if not str(draft.get("title", "")).strip():
            raise RuntimeError("content generator produced no title")
        if not str(draft.get("body", "")).strip():
            raise RuntimeError("content generator produced no body")

    def _humanize_draft(self, job_id, draft):
        try:
            from .humanizer import humanize_text
            style_hint = draft.get("draft_meta", {}).get("strategy", {}).get("tone", "")
            h_result = humanize_text(draft["title"], draft["body"], style_hint=style_hint)
            if h_result.get("ok") and h_result.get("patterns_detected"):
                draft["title"] = h_result["title"]
                draft["body"] = h_result["body"]
                self.store.record_event(job_id, "humanized", {
                    "patterns_found": list(h_result["patterns_detected"].keys()),
                    "score": h_result.get("score", 0),
                })
        except ImportError:
            self.store.record_event(job_id, "humanize_skipped", {"reason": "module_not_available"})
        except Exception as exc:
            self.store.record_event(job_id, "humanize_failed", {"error": redact_secrets(exc)})

    def _generate_optional_media(self, job_id, kind, runner, depends_on, step_name=None):
        cfg = self.config.get("media", {}).get(kind, {})
        step = step_name or f"generate_{kind}"
        job = self.store.get_job(job_id)
        required = self._media_required(kind, cfg, job)
        if not cfg.get("enabled", False):
            if required and kind == "image":
                # Article platforms may use the built-in content-card renderer
                # even when an external image provider is unavailable.
                self.media.config.setdefault("image", {})["enabled"] = True
                cfg = self.media.config["image"]
            else:
                if required:
                    runner.block(step, f"{kind}_required_but_not_enabled", f"{kind} generation is required by platform strategy but not enabled", depends_on=depends_on)
                runner.skipped(step, f"{kind}_not_enabled", f"{kind} generation is not enabled by config", required=False, depends_on=depends_on)
                return None
        try:
            artifact = runner.run(step, lambda: self.media.generate(kind, self.store.get_job(job_id)), required=required, depends_on=depends_on)
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
                self.store.add_artifact(job_id, "illustration", art.get("prompt_path", ""), "")
            return artifact
        if kind == "wechat_format":
            self.store.add_artifact(job_id, "wechat_format", artifact.get("html_path", ""), artifact.get("validated", False))
            self.store.record_event(job_id, "wechat_formatted", {"theme": artifact.get("theme", ""), "validated": artifact.get("validated", False)})
            return artifact
        if kind == "magazine_format":
            self.store.add_artifact(job_id, "magazine_format", artifact.get("html_path", ""), artifact.get("style", ""))
            self.store.record_event(job_id, "magazine_formatted", {"style": artifact.get("style", "")})
            return artifact
        if kind == "image" and artifact.get("images"):
            for item in artifact.get("images", []):
                self.store.add_artifact(job_id, item.get("kind") or "image", item.get("path", ""), item.get("checksum", ""))
            mapping_path = Path(artifact["path"]).parent / "section_image_map.json"
            if mapping_path.is_file():
                self.store.add_artifact(job_id, "section_image_map", mapping_path, "")
            contract_path = Path(str(artifact.get("article_media_contract") or ""))
            if contract_path.is_file():
                self.store.add_artifact(job_id, "article_media_contract", contract_path, "")
            return artifact
        self.store.add_artifact(job_id, artifact["kind"], artifact["path"], artifact.get("checksum", ""))
        return artifact


    def _media_required(self, kind, cfg, job):
        if bool((cfg or {}).get("required", False)):
            return True
        platforms = {str(item).casefold() for item in (job or {}).get("platforms", [])}
        draft_meta = (job or {}).get("draft_meta") or {}
        media_plan = {str(item).casefold() for item in draft_meta.get("media_plan", [])}
        if kind == "image" and bool(self.config.get("strict_media_contract", False)) and platforms.intersection({"juejin", "zhihu", "wechat", "weixin"}):
            return bool(media_plan.intersection({"cover", "article", "inline_images", "project_screenshot"})) or bool(draft_meta.get("content_form") in {"article", "long_article"})
        if kind != "video":
            return False
        plan = draft_meta.get("video_toolchain_plan") or {}
        return bool(plan.get("required"))

    def _validate_image_requirements(self, job_id, runner, generated_image=None):
        image_cfg = self.config.get("media", {}).get("image", {})
        job = self.store.get_job(job_id)
        required = self._media_required("image", image_cfg, job)
        artifacts = [item for item in self.store.artifacts(job_id) if item.get("kind") == "image"]
        if not required and not image_cfg.get("enabled", False):
            runner.skipped("validate_image_requirements", "image_not_required", "current config does not require images", required=False, depends_on=["generate_or_collect_images"])
            return
        minimum = int(image_cfg.get("min_count", 2 if required and {str(item).casefold() for item in job.get("platforms", [])}.intersection({"juejin", "zhihu"}) else (1 if required else 0)))
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

    def _quality_gate(self, job_id, draft, risk, geo, *, phase="rendered", platforms=None):
        if phase == "rendered":
            self._recover_video_render_evidence(job_id, draft)
        dm = draft.get("draft_meta", {})
        gate = {"passed": True, "gates": {}}
        g1 = risk.get("level", "pass") != "block"
        gate["gates"]["G1_risk_compliance"] = {"passed": g1, "level": risk.get("level", "pass")}
        platforms = list(platforms or dm.get("strategy", {}).get("primary_platforms", []))
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
        g3 = qg.get("passed", True)
        failed_dimensions = list(qg.get("failed_dimensions", []) or [])
        if not g3 and not failed_dimensions:
            # Some pre-populated/manual drafts carry an aggregate false value
            # without a failed dimension. Do not invent a failure when the
            # scorer produced no actionable reason.
            g3 = True
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
        planned_artifacts = list(dm.get("media_plan", []) or [])
        actual_artifacts = []
        try:
            actual_artifacts = [item for item in self.store.artifacts(job_id) if Path(item.get("path", "")).is_file() and Path(item.get("path", "")).stat().st_size > 0]
        except (OSError, KeyError):
            actual_artifacts = []
        platforms_set = {str(item).casefold() for item in platforms}
        article_media_required = bool(platforms_set.intersection({"juejin", "zhihu", "wechat", "weixin"}) and (planned_artifacts or dm.get("content_form") in {"article", "long_article"}))
        actual_images = [item for item in actual_artifacts if item.get("kind") == "image"]
        required_image_count = 2 if platforms_set.intersection({"juejin", "zhihu"}) else 1
        if phase == "generation":
            g4 = True
            g4_deferred = True
        elif article_media_required:
            g4 = len(actual_images) >= required_image_count
            g4_deferred = False
        elif "short_video" == dm.get("content_form", ""):
            g4 = len(actual_artifacts) > 0
            g4_deferred = False
        else:
            g4 = True
            g4_deferred = False
        gate["gates"]["G4_media_assets"] = {"passed": g4, "deferred": g4_deferred, "plan": planned_artifacts, "actual_count": len(actual_artifacts), "actual_image_count": len(actual_images), "required_image_count": required_image_count if article_media_required else 0}
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
        media_contract = self._media_contract_quality_gate(job_id, draft, list(platforms), phase=phase)
        if media_contract:
            gate["gates"]["G6_media_contracts"] = media_contract
        platform_quality = self._generation_platform_quality_gate(job_id, draft, list(platforms), phase=phase)
        if platform_quality:
            gate["gates"]["G6_platform_quality"] = platform_quality
        gate["passed"] = all(g["passed"] for g in gate["gates"].values())
        gate["score"] = sum(1 for g in gate["gates"].values() if g["passed"])
        gate["total"] = len(gate["gates"])
        return gate

    def _media_contract_quality_gate(self, job_id, draft, platforms, *, phase="generation"):
        """Run renderer and handoff validators on the production delivery path."""
        if phase != "rendered":
            return None
        meta = draft.get("draft_meta") or {}
        normalized = {str(item).casefold() for item in platforms}
        checks = {}
        artifact_dir = self.data_dir / "artifacts" / str(job_id)

        if "juejin" in normalized:
            contract_path = artifact_dir / "article_media_contract.json"
            contract = {}
            try:
                contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.is_file() else {}
            except (OSError, json.JSONDecodeError):
                contract = {}
            handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
            checks["handoff_contract"] = validate_handoff_contract(handoff, require_target_renderer=False)

        plan = meta.get("video_toolchain_plan") if isinstance(meta.get("video_toolchain_plan"), dict) else {}
        video_artifact = meta.get("video_artifact") if isinstance(meta.get("video_artifact"), dict) else {}
        video_required = bool(plan.get("required") or video_artifact or meta.get("scene_manifest"))
        if video_required:
            manifest = meta.get("scene_manifest") if isinstance(meta.get("scene_manifest"), dict) else {}
            if not manifest:
                manifest_path = artifact_dir / "scene_manifest.json"
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
                except (OSError, json.JSONDecodeError):
                    manifest = {}
            observed = meta.get("observed_scene_evidence") if isinstance(meta.get("observed_scene_evidence"), dict) else {}
            if not observed:
                observed_path = artifact_dir / "scene_observed_evidence.json"
                try:
                    observed = json.loads(observed_path.read_text(encoding="utf-8")) if observed_path.is_file() else {}
                except (OSError, json.JSONDecodeError):
                    observed = {}
            checks["scene_manifest"] = validate_scene_manifest_contract(manifest, observed=observed)
            bgm = meta.get("bgm_source") or meta.get("bgm") or {}
            checks["bgm"] = validate_bgm_contract(bgm, recent_fingerprints=meta.get("recent_bgm_fingerprints") or [])
            checks["tts"] = validate_tts_fingerprint(meta.get("tts_fingerprint") or meta.get("tts_config"))
            video_path = str(video_artifact.get("path") or manifest.get("output") or "")
            checks["ffprobe"] = probe_final_video(video_path)

        if not checks:
            return None
        failures = {name: value for name, value in checks.items() if not value.get("passed")}
        return {"passed": not failures, "phase": phase, "checks": checks, "failures": failures}

    @staticmethod
    def _post_delivery_handoff_gate(job, platform):
        if str(platform).casefold() != "juejin":
            return {"passed": True, "skipped": True}
        contract = (job.get("draft_meta") or {}).get("article_media_contract")
        if not isinstance(contract, dict):
            return {"passed": False, "failures": ["article_media_contract_missing"]}
        handoff = contract.get("handoff_contract") if isinstance(contract.get("handoff_contract"), dict) else contract
        return validate_handoff_contract(handoff)

    def _recover_video_render_evidence(self, job_id, draft):
        """Recover renderer evidence when an optional later media step fails."""
        meta = draft.setdefault("draft_meta", {})
        if meta.get("render_manifest") or meta.get("video_artifact"):
            return
        artifact_dir = self.data_dir / "artifacts" / str(job_id)
        manifest_path = artifact_dir / "video_toolchain_runner_manifest.json"
        if not manifest_path.is_file():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(manifest, dict) or manifest.get("status") != "rendered":
            return
        output = Path(str(manifest.get("output") or ""))
        if not output.is_file():
            return
        packet = {}
        packet_path = artifact_dir / "packet.json"
        if packet_path.is_file():
            try:
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                packet = {}
        self._attach_video_render_evidence(
            draft,
            {
                "path": str(output),
                "checksum": hashlib.sha256(output.read_bytes()).hexdigest(),
                "render_manifest": manifest,
                "render_packet": packet,
            },
        )

    def _generation_platform_quality_gate(self, job_id, draft, platforms, *, phase="generation"):
        if not self.require_gate_pass:
            return None
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
                # Generation only proves that the selected stack is planned.
                # Require terminal tool execution after assets/rendering, when
                # the renderer and publishers have emitted real evidence.
                packet["runtime_execution_required"] = phase == "rendered"
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
            else:
                result = self._platform_quality_validator(normalized, packet)
            if result:
                results[normalized] = result
        if not results:
            return None
        return {
            "passed": all(result.get("passed") for result in results.values()),
            "mode": "enforce",
            "platforms": list(results.keys()),
            "results": results,
        }

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
        meta = packet if isinstance(packet, dict) else {}
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
        artifact_dir = output.parent if output.is_file() else None
        if artifact_dir and not audio:
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-show_entries", "format=duration", "-of", "json", str(output)],
                    capture_output=True, text=True, timeout=8, check=False,
                )
                payload = json.loads(probe.stdout or "{}")
                streams = payload.get("streams") or []
                audio = {"stream_count": sum(1 for item in streams if item.get("codec_type") == "audio"), "duration": float((payload.get("format") or {}).get("duration") or 0)}
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        if artifact_dir and not bgm:
            try:
                candidate = artifact_dir / "bgm_source.json"
                if candidate.is_file():
                    bgm = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        if artifact_dir and not subtitle:
            try:
                srt = artifact_dir / "narration.srt"
                if srt.is_file():
                    cue_count = len([line for line in srt.read_text(encoding="utf-8", errors="ignore").splitlines() if re.match(r"^\d+$", line.strip())])
                    subtitle = {"cue_count": cue_count}
                    captions = captions or {"position": "lower_third", "burned_in": True, "font_size": 44, "max_chars_per_line": 16, "max_lines": 1, "margin_v": 350}
            except OSError:
                pass
        if artifact_dir and not backgrounds:
            backgrounds = [{"path": str(path)} for path in sorted((artifact_dir / "backgrounds").glob("bg_*.png"))]
        required_tools = {
            "cinema_composition.storyboard",
            "shotcraft_moves.shot_plan_for_text",
            "kuaishou_render.render_cards",
            "kuaishou_render.download_bgm",
            "kuaishou_render.gen_subtitles",
            "kuaishou_render.encode_final",
        }
        forbidden_bgm = {"synthetic", "procedural", "generated_tone", "midi", "generated_synthetic_bgm"}
        gates = {
            "rendered_output": {"passed": output.is_file() and output.stat().st_size > 0 and str(manifest.get("output") or "") == str(output)},
            "renderer_manifest": {"passed": manifest.get("ok") is True and manifest.get("status") == "rendered" and bool(plan.get("required"))},
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
            "cinematic_fallback": {"passed": not bool(meta.get("degraded") or meta.get("fallback_used"))},
        }
        failures = [name for name, value in gates.items() if not value["passed"]]
        return {"passed": not failures, "phase": "rendered", "gates": gates, "failed_dimensions": failures}

    @staticmethod
    def _attach_video_render_evidence(draft, artifact):
        """Merge renderer-written measurements into the final quality packet."""
        meta = draft.setdefault("draft_meta", {})
        manifest = artifact.get("render_manifest")
        if isinstance(manifest, dict):
            meta["render_manifest"] = manifest
            nested_manifest = manifest.get("tool_invocation_manifest")
            if isinstance(nested_manifest, dict) and nested_manifest:
                meta["renderer_tool_invocation_manifest"] = nested_manifest
        renderer_packet = artifact.get("render_packet")
        if isinstance(renderer_packet, dict):
            for key in ("audio_probe", "subtitle", "burned_captions", "background_assets", "bgm", "bgm_source"):
                if key in renderer_packet:
                    meta[key] = renderer_packet[key]
            manifest = renderer_packet.get("tool_invocation_manifest")
            if isinstance(manifest, dict) and manifest:
                meta["renderer_tool_invocation_manifest"] = manifest
        for key in ("degraded", "fallback_used", "fallback_reason", "quality_gate", "scene_manifest", "observed_scene_evidence", "tts_fingerprint"):
            if key in artifact:
                meta[key] = artifact[key]
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
        draft_meta = draft.get("draft_meta") or {}
        strategy = draft_meta.get("strategy") or {}
        packet = {}
        for source in (strategy, draft_meta, draft):
            if isinstance(source, dict):
                packet.update(source)
        packet.setdefault("id", job_id)
        packet.setdefault("title", draft.get("title", ""))
        packet.setdefault("body", draft.get("body", ""))
        packet.setdefault("platform", platform)
        packet.setdefault("platforms", platforms)
        if "strategy_brief" not in packet and isinstance(strategy, dict):
            packet["strategy_brief"] = strategy
        if "content_type" not in packet and packet.get("content_form"):
            packet["content_type"] = packet["content_form"]
        return packet

    @staticmethod
    def _platform_quality_validator(platform, packet):
        if platform in {"wechat", "weixin", "wechat_official"}:
            return validate_wechat_auto_packet(packet)
        if platform == "kuaishou":
            return validate_kuaishou_auto_packet(packet)
        if platform == "shipinhao":
            return validate_shipinhao_auto_packet(packet)
        if platform == "bilibili":
            return validate_bilibili_auto_packet(packet)
        if platform == "douyin":
            if packet.get("content_line") == "tiktok_hot_localized_repost":
                failures = validate_douyin_tiktok_repost_packet(packet, require_visual_review=True)
                return {"passed": not failures, "failed_dimensions": failures}
            return validate_douyin_auto_packet(packet)
        if platform in {"xiaohongshu", "rednote"}:
            return validate_xiaohongshu_auto_packet(packet)
        if platform in {"juejin", "zhihu", "devto", "telegraph", "writeas", "buttondown"}:
            return validate_platform_article_packet(packet, platform)
        return None

    @staticmethod
    def _worker_id():
        return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
