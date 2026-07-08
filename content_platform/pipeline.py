import hashlib
import os
import time
import uuid
from pathlib import Path

from .compliance import ComplianceChecker
from .formatters import format_for_platform
from .generator import DraftGenerator
from .media import MediaBridge
from .models import DeliveryResult
from .notify import Notifier
from .profiles import resolve_profile
from .publishers import build_publisher
from .resource import ResourceGuard
from .review import ReviewTokens
from .risk import RiskFilter, redact_secrets


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

    def create(self, topic, platforms, brief=None, profile="default", topic_fingerprint=""):
        resolved = resolve_profile(self.config.get("profiles", {}), profile, brief or {})
        return self.store.create_job(topic, platforms, resolved, profile, topic_fingerprint)

    def run(self, job_id, force=False):
        job = self.store.get_job(job_id)
        if job["state"] != "created" and not force:
            return self._hydrate(job)
        if force and job["state"] not in {"created", "failed", "blocked", "rejected"}:
            raise ValueError(f"cannot force generation from state: {job['state']}")
        owner = self._worker_id()
        if not self.store.claim(job_id, {job["state"]}, owner, 900, "generating"):
            raise RuntimeError("job is already claimed by another worker")
        try:
            job = self.store.get_job(job_id)
            draft = self.generator.generate(job["topic"], self._enrich_brief(job))
            self._persist_intelligence(job_id, draft.get("draft_meta", {}))
            text = draft["title"] + "\n" + draft["body"]
            risk = self.risk.evaluate(text)
            compliance = self.compliance.evaluate(text, job["brief"], job["platforms"])
            risk["compliance"] = compliance
            if risk["level"] == "pass" and compliance["level"] == "review":
                risk["level"] = "review"
            if risk["level"] == "pass" and not draft.get("draft_meta", {}).get("quality_gate", {}).get("passed", True):
                risk["level"] = "review"
                risk.setdefault("quality_gate", draft["draft_meta"]["quality_gate"])
            self.store.save_draft(
                job_id, draft["title"], draft["body"], risk["level"], risk, draft.get("prompt_version", ""), draft.get("draft_meta", {})
            )
            if risk["level"] == "block":
                blocked = self.store.release_claim(job_id, owner, "blocked", "risk_blocked", detail={"hits": risk["hits"]})
                self.notifier.send("blocked", blocked)
                return self._hydrate(blocked)
            for kind in ("image", "video", "audio"):
                try:
                    artifact = self.media.generate(kind, self.store.get_job(job_id))
                    if artifact:
                        self.store.add_artifact(job_id, artifact["kind"], artifact["path"], artifact["checksum"])
                except Exception as exc:
                    self.store.record_event(job_id, "media_failed", {"kind": kind, "error": redact_secrets(exc)})
            reviewed = self.store.release_claim(job_id, owner, "review_required", "review_requested", detail={"risk": risk["level"]})
            if self.config.get("delivery", {}).get("auto_stage_review_required"):
                reviewed = self.stage_drafts(job_id)
            notify_job = dict(reviewed)
            notify_job["review_actions"] = {
                "approve": self.review_tokens.issue(job_id, "approve", self.review_ttl),
                "reject": self.review_tokens.issue(job_id, "reject", self.review_ttl),
            }
            self.notifier.send("review_required", notify_job)
            return self._hydrate(reviewed)
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
        if not self.store.claim(job_id, {job["state"]}, owner, 300, "publishing"):
            raise RuntimeError("job is already claimed by another worker")
        try:
            for platform in job["platforms"]:
                self.store.enqueue_delivery(job_id, platform, "publish", {"state": job["state"]})
            processed = self.process_delivery_queue()
            hydrated = self._hydrate(self.store.get_job(job_id))
            successes = sum(1 for delivery in hydrated["deliveries"] if delivery["status"] in {"drafted", "published", "handoff_pending"})
            final_state = "published" if successes == len(job["platforms"]) else "partial"
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

    def stage_drafts(self, job_id):
        job = self._hydrate(self.store.get_job(job_id))
        if job["state"] not in {"review_required", "approved", "partial", "published"}:
            raise PermissionError(f"job must be reviewable before draft staging, got: {job['state']}")
        for platform in job["platforms"]:
            self.store.enqueue_delivery(job_id, platform, "stage", {"state": job["state"]})
        self.process_delivery_queue()
        return self._hydrate(self.store.get_job(job_id))

    def process_delivery_queue(self, limit=100):
        processed = 0
        owner = self._worker_id()
        while processed < int(limit):
            item = self.store.claim_delivery(owner, 300)
            if not item:
                break
            job = self._hydrate(self.store.get_job(item["job_id"]))
            prior = next((delivery for delivery in job["deliveries"] if delivery["platform"] == item["platform"]), None)
            if prior and prior["status"] in {"drafted", "published", "handoff_pending"}:
                self.store.complete_delivery(item["id"], owner, "completed")
                processed += 1
                continue
            delivery_job = dict(job)
            delivery_job["platform_payload"] = format_for_platform(job, item["platform"])
            try:
                result = self._deliver(item["platform"], delivery_job)
                self._save_delivery_result(item["job_id"], item["platform"], result)
                queue_state = "completed" if result.ok or result.status in {"blocked", "drafted", "published", "handoff_pending"} else "queued"
                self.store.complete_delivery(item["id"], owner, queue_state, result.error)
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

    def _enrich_brief(self, job):
        brief = dict(job.get("brief", {}))
        platforms = list(job.get("platforms", []))
        topic = job.get("topic", "")
        historical = self.store.historical_performance(platforms, topic)
        brief.setdefault("historical_feedback", historical)
        brief.setdefault("cluster_memory", historical.get("clusters", []))
        return brief

    def _deliver(self, platform, job):
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

    @staticmethod
    def _worker_id():
        return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
