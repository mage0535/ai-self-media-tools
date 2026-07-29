import hashlib
import os
import time
import uuid
from pathlib import Path

from .compliance import ComplianceChecker
from .content_hygiene import audit_topic
from .content_policy import generated_media_kinds_for_job
from .delivery_health import delivery_health_decision
from .formatters import format_for_platform
from .generator import DraftGenerator
from .humanize import naturalize_copy
from .intelligence import GLOBAL_EN_PLATFORMS, build_generation_context
from .media import MediaBridge
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
from .profiles import resolve_profile
from .publishers import build_publisher
from .resource import ResourceGuard
from .review import ReviewTokens
from .risk import RiskFilter, redact_secrets
from .seo import geo_check
from .wechat_toolchain import prepare_wechat_professional_draft, requires_wechat_toolchain
from .workflow_runtime import (
    WorkflowBlocked,
    WorkflowStepRunner,
    strict_workflow_lock,
    write_platform_report,
)


class Pipeline:
    def __init__(self, store, config=None):
        self.store = store
        self.config = config or {}
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
                runner.succeeded("run_operation_strategy", {"historical_feedback": bool(brief.get("historical_feedback"))}, depends_on=["load_content_strategy"])
                # Check if job has pre-populated body content (manually written, not a stub)
                existing_body = (job.get("body") or "").strip()
                if len(existing_body) > 100:
                    # Use pre-populated content directly; run naturalize_copy for quality scoring
                    ctx = build_generation_context(job["topic"], brief)
                    rewrite = naturalize_copy(existing_body, ctx)
                    draft = {
                        "title": job.get("title") or job["topic"],
                        "body": rewrite["body"],
                        "provider": "pre_populated",
                        "prompt_version": self.generator.PROMPT_VERSION,
                        "draft_meta": {
                            k: v for k, v in ctx.items()
                            if k in {"trend_stage", "trend_angle", "reference_titles", "style",
                                      "source_summary", "source_catalog", "topic_clusters",
                                      "niche_report", "viral_score", "strategy",
                                      "image_prompt", "video_prompt", "hashtags",
                                      "geo_score", "geo_details"}
                        },
                    }
                    draft["draft_meta"]["quality_scores"] = rewrite["quality_scores"]
                    draft["draft_meta"]["quality_gate"] = rewrite["quality_gate"]
                    draft["draft_meta"]["rewrite_notes"] = rewrite["rewrite_notes"]
                    draft["draft_meta"]["content_form"] = brief.get("content_form") or ctx.get("strategy", {}).get("content_form", "long_article")
                    draft["draft_meta"]["media_plan"] = ctx.get("strategy", {}).get("asset_plan", [])
                    # Record generate_content step for audit completeness
                    runner.succeeded("generate_content", {
                        "provider": "pre_populated",
                        "body_chars": len(draft["body"]),
                        "title": draft["title"],
                        "quality_gate_passed": rewrite["quality_gate"]["passed"],
                    }, depends_on=["run_operation_strategy"])
                else:
                    draft = runner.run("generate_content", lambda: self.generator.generate(job["topic"], brief), depends_on=["run_operation_strategy"], require_output=True)
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
                draft.setdefault("draft_meta", {}).setdefault("strategy", {}).setdefault("primary_platforms", job["platforms"])
                runner.succeeded("validate_content_structure", {"title_present": bool(draft.get("title")), "body_chars": len(str(draft.get("body", "")))}, depends_on=["generate_content"])
                self._persist_intelligence(job_id, draft.get("draft_meta", {}))
                text = draft["title"] + "\n" + draft["body"]
                geo = runner.run("run_fact_check", lambda: geo_check(text), depends_on=["validate_content_structure"], require_output=True)
                self.store.save_geo_score(job_id, geo)
                risk = runner.run("run_safety_gate", lambda: self.risk.evaluate(text), depends_on=["run_fact_check"], require_output=True)
                risk["content_hygiene"] = hygiene
                compliance = self.compliance.evaluate(text, job["brief"], job["platforms"])
                risk["compliance"] = compliance
                if risk["level"] == "pass" and compliance["level"] == "review":
                    risk["level"] = "review"
                if risk["level"] == "block":
                    runner.block("run_safety_gate", "safety_gate_blocked", "content safety gate blocked this job", risk)
                gate = self._quality_gate(job_id, draft, risk, geo)
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
                for kind in generated_media_kinds_for_job(self.store.get_job(job_id), self.config):
                    self._generate_optional_media(job_id, kind, runner, ["validate_image_requirements"])
                reviewed = self.store.release_claim(job_id, owner, "review_required", "review_requested", detail={"risk": risk["level"]})
                if self.config.get("delivery", {}).get("auto_stage_review_required"):
                    reviewed = self.stage_drafts(job_id, owner=owner, already_locked=True)
                notify_job = dict(reviewed)
                notify_job["review_actions"] = {
                    "approve": self.review_tokens.issue(job_id, "approve", self.review_ttl),
                    "reject": self.review_tokens.issue(job_id, "reject", self.review_ttl),
                }
                self.notifier.send("review_required", notify_job)
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
            self.store.enqueue_delivery(job_id, platform, "stage", {"state": job["state"]})
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
                    self.store.complete_delivery(item["id"], owner, "completed")
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
                    runner.succeeded("publish_or_create_draft", {"status": result.status, "external_id_present": bool(result.external_id)}, depends_on=["run_platform_pre_publish_gate"])
                    self._save_delivery_result(item["job_id"], platform, result)
                    runner.succeeded("verify_publish_result", {"status": result.status, "requires_postcheck": result.status in {"drafted", "handoff_pending"}}, depends_on=["publish_or_create_draft"])
                    runner.succeeded("record_publish_receipt", {"status": result.status}, depends_on=["verify_publish_result"])
                    queue_state = "completed" if result.ok or result.status in {"blocked", "drafted", "published", "handoff_pending"} else "queued"
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
        historical = self.store.historical_performance(platforms, topic)
        brief.setdefault("historical_feedback", historical)
        brief.setdefault("cluster_memory", historical.get("clusters", []))
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

    def _deliver(self, platform, job, action="publish"):
        decision = delivery_health_decision(platform, self.config, action)
        if not decision.ok:
            return DeliveryResult(False, "blocked", error=decision.error())
        cfg = self.config.get("delivery", {})
        max_attempts = max(1, int(cfg.get("max_attempts", 2)))
        backoff = float(cfg.get("backoff_seconds", 0.2))
        result = DeliveryResult(False, "failed", error="delivery not attempted")
        for attempt in range(max_attempts):
            try:
                result = build_publisher(platform, self.config, self.data_dir).deliver(job, platform)
            except Exception as exc:
                result = DeliveryResult(False, "failed", error=redact_secrets(exc))
            if result.ok or result.status == "blocked":
                return result
            if attempt + 1 < max_attempts and backoff:
                time.sleep(backoff * (2**attempt))
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
        self.store.add_artifact(job_id, artifact["kind"], artifact["path"], artifact.get("checksum", ""))
        return artifact


    @staticmethod
    def _media_required(kind, cfg, job):
        if bool((cfg or {}).get("required", False)):
            return True
        if kind != "video":
            return False
        plan = ((job or {}).get("draft_meta") or {}).get("video_toolchain_plan") or {}
        return bool(plan.get("required"))

    def _validate_image_requirements(self, job_id, runner, generated_image=None):
        image_cfg = self.config.get("media", {}).get("image", {})
        required = bool(image_cfg.get("required", False))
        artifacts = [item for item in self.store.artifacts(job_id) if item.get("kind") == "image"]
        if not required and not image_cfg.get("enabled", False):
            runner.skipped("validate_image_requirements", "image_not_required", "current config does not require images", required=False, depends_on=["generate_or_collect_images"])
            return
        minimum = int(image_cfg.get("min_count", 1 if required else 0))
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

    def _quality_gate(self, job_id, draft, risk, geo):
        dm = draft.get("draft_meta", {})
        gate = {"passed": True, "gates": {}}
        g1 = risk.get("level", "pass") != "block"
        gate["gates"]["G1_risk_compliance"] = {"passed": g1, "level": risk.get("level", "pass")}
        g2 = geo.get("score", 0) >= 40
        gate["gates"]["G2_geo"] = {"passed": g2, "score": geo.get("score", 0)}
        qg = dm.get("quality_gate", {})
        g3 = qg.get("passed", True)
        gate["gates"]["G3_anti_generic"] = {"passed": g3, "failed": qg.get("failed_dimensions", [])}
        artifacts = dm.get("media_plan", [])
        g4 = len(artifacts) > 0 if "short_video" == dm.get("content_form", "") else True
        gate["gates"]["G4_media_assets"] = {"passed": g4, "plan": artifacts}
        platforms = dm.get("strategy", {}).get("primary_platforms", [])
        g5 = len(platforms) > 0
        gate["gates"]["G5_format"] = {"passed": g5, "platforms": platforms}
        platform_quality = self._generation_platform_quality_gate(job_id, draft, list(platforms))
        if platform_quality:
            gate["gates"]["G6_platform_quality"] = platform_quality
        gate["passed"] = all(g["passed"] for g in gate["gates"].values())
        gate["score"] = sum(1 for g in gate["gates"].values() if g["passed"])
        gate["total"] = len(gate["gates"])
        return gate

    def _generation_platform_quality_gate(self, job_id, draft, platforms):
        if not self.require_gate_pass:
            return None
        results = {}
        for platform in platforms:
            normalized = str(platform or "").casefold()
            packet = self._generation_platform_packet(job_id, draft, platforms, normalized)
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
