"""Immutable champion–challenger control plane for owned content outcomes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import exp, log1p
from pathlib import Path
from typing import Any

MIN_TOTAL = 120
MIN_HOLDOUT_PER_ARM = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _aware(value: Any) -> datetime | None:
    try:
        item = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return item.astimezone(timezone.utc) if item.tzinfo else None
    except ValueError:
        return None


def _scope(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(key) or "").strip() for key in ("platform", "account_id", "lane", "content_form"))


class LearningRegistry:
    """File-backed append-only control records; no credentials are persisted."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": "learning_registry_v1", "policies": [], "approvals": [], "assignments": [], "outcomes": [], "evaluations": [], "events": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != "learning_registry_v1":
            raise ValueError("learning_registry_invalid")
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.with_suffix(self.path.suffix + ".tmp")
        target.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        target.replace(self.path)

    def _find(self, kind: str, identifier: str, key: str) -> dict[str, Any] | None:
        return next((row for row in self.data[kind] if row.get(key) == identifier), None)

    def create_policy(self, *, platform: str, account_id: str, lane: str, content_form: str, treatment_vector: dict[str, Any], rollback_target_policy_version_id: str | None = None) -> dict[str, Any]:
        if not all((platform, account_id, lane, content_form)) or not isinstance(treatment_vector, dict) or not treatment_vector:
            raise ValueError("policy_scope_or_treatment_missing")
        if rollback_target_policy_version_id and not self._find("policies", rollback_target_policy_version_id, "policy_version_id"):
            raise ValueError("rollback_target_missing")
        payload = {"platform": platform, "account_id": account_id, "lane": lane, "content_form": content_form, "treatment_vector": treatment_vector, "rollback_target_policy_version_id": rollback_target_policy_version_id}
        policy_id = f"policy:{_hash(payload)[:16]}"
        record = {"version": "learning_policy_v1", "policy_version_id": policy_id, **payload, "status": "draft", "created_at": _now()}
        record["policy_hash"] = _hash(record)
        self.data["policies"].append(record); self._save()
        return record

    def approve(self, *, policy_version_id: str, approver_id: str, max_exposure: float, expires_in_days: int = 30) -> dict[str, Any]:
        policy = self._find("policies", policy_version_id, "policy_version_id")
        if not policy or not approver_id or not (0 < float(max_exposure) <= 0.5):
            raise ValueError("approval_invalid")
        record = {"approval_id": f"approval:{_hash([policy_version_id, approver_id, _now()])[:16]}", "policy_version_id": policy_version_id, "approver_id": approver_id, "scope": _scope(policy), "max_exposure": float(max_exposure), "approved_at": _now(), "expires_at": (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(timespec="seconds")}
        record["approval_hash"] = _hash(record)
        policy["status"] = "approved"; self.data["approvals"].append(record); self._save()
        return record

    def active_policy(self, *, scope: tuple[str, str, str, str]) -> dict[str, Any] | None:
        return next((row for row in self.data["policies"] if _scope(row) == tuple(scope) and row.get("status") == "active"), None)

    def activate(self, *, policy_version_id: str, approval_id: str) -> dict[str, Any]:
        policy = self._find("policies", policy_version_id, "policy_version_id")
        approval = self._find("approvals", approval_id, "approval_id")
        if not policy or not approval or approval.get("policy_version_id") != policy_version_id or _aware(approval.get("expires_at")) <= datetime.now(timezone.utc):
            raise ValueError("activation_approval_invalid")
        if not policy.get("rollback_target_policy_version_id"):
            raise ValueError("activation_rollback_target_missing")
        target = self._find("policies", policy["rollback_target_policy_version_id"], "policy_version_id")
        if not target or _scope(target) != _scope(policy):
            raise ValueError("activation_rollback_target_invalid")
        current = self.active_policy(scope=_scope(policy))
        if current and current["policy_version_id"] != policy_version_id:
            current["status"] = "approved"
        target["status"] = "approved"
        policy["status"] = "active"
        event = {"event_type": "activation", "policy_version_id": policy_version_id, "approval_id": approval_id, "previous_policy_version_id": current.get("policy_version_id") if current else None, "created_at": _now()}
        event["event_hash"] = _hash(event)
        self.data["events"].append(event); self._save()
        return event

    def rollback(self, *, policy_version_id: str, reason: str) -> dict[str, Any]:
        policy = self._find("policies", policy_version_id, "policy_version_id")
        if not policy or policy.get("status") != "active" or not str(reason).strip():
            raise ValueError("rollback_invalid")
        target = self._find("policies", str(policy.get("rollback_target_policy_version_id") or ""), "policy_version_id")
        if not target or _scope(target) != _scope(policy):
            raise ValueError("rollback_target_invalid")
        policy["status"] = "rolled_back"; target["status"] = "active"
        event = {"event_type": "rollback", "policy_version_id": policy_version_id, "rollback_target_policy_version_id": target["policy_version_id"], "reason": reason, "created_at": _now()}
        event["event_hash"] = _hash(event)
        self.data["events"].append(event); self._save()
        return event

    def assign(self, *, job_id: str, policy_version_id: str, approval_id: str | None, arm: str | None = None) -> dict[str, Any]:
        existing = self._find("assignments", job_id, "job_id")
        if existing: return existing
        policy = self._find("policies", policy_version_id, "policy_version_id")
        if not policy: raise ValueError("policy_missing")
        is_treatment = arm == "treatment"
        if is_treatment:
            if policy.get("status") not in {"approved", "active"}:
                raise ValueError("policy_not_approved")
            approval = self._find("approvals", str(approval_id), "approval_id")
            if not approval or approval["policy_version_id"] != policy_version_id or _aware(approval["expires_at"]) <= datetime.now(timezone.utc):
                raise ValueError("treatment_approval_invalid")
        arm = arm or "control"
        if arm not in {"control", "treatment"}: raise ValueError("assignment_arm_invalid")
        record = {"assignment_id": f"assignment:{_hash([job_id, policy_version_id, arm])[:16]}", "job_id": job_id, "policy_version_id": policy_version_id, "approval_id": approval_id if is_treatment else None, "arm": arm, "created_at": _now()}
        record["assignment_hash"] = _hash(record)
        self.data["assignments"].append(record); self._save()
        return record

    def record_outcome(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw) if isinstance(raw, dict) else {}
        reasons: list[str] = []
        required = ("platform", "account_id", "lane", "content_form", "content_id", "job_id", "publish_receipt_id", "policy_version_id", "assignment_id", "metric_window", "published_at", "observed_at", "authorization_ref", "raw_response_hash")
        if any(not str(row.get(key) or "").strip() for key in required): reasons.append("owned_outcome_required_field_missing")
        if row.get("source_class") != "authorized_owned_analytics": reasons.append("owned_outcome_source_not_authorized")
        if row.get("native_verified") is not True or row.get("strategy_eligible") is not True: reasons.append("owned_outcome_not_strategy_eligible")
        if row.get("metric_window") != "72h": reasons.append("owned_outcome_window_not_72h")
        published, observed = _aware(row.get("published_at")), _aware(row.get("observed_at"))
        if not published or not observed or observed < published or observed > published + timedelta(hours=96): reasons.append("owned_outcome_timestamp_invalid")
        if len(str(row.get("raw_response_hash") or "")) != 64: reasons.append("owned_outcome_raw_hash_invalid")
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        for key in ("views", "likes", "comments", "shares", "saves", "follows"):
            try:
                if float(metrics.get(key, -1)) < 0: reasons.append("owned_outcome_metric_invalid")
            except (TypeError, ValueError): reasons.append("owned_outcome_metric_invalid")
        if float(metrics.get("likes", 0) or 0) >= float(metrics.get("views", 0) or 0) and float(metrics.get("views", 0) or 0) > 0: reasons.append("likes_not_less_than_views")
        assignment = self._find("assignments", str(row.get("assignment_id") or ""), "assignment_id")
        policy = self._find("policies", str(row.get("policy_version_id") or ""), "policy_version_id")
        if not assignment or not policy or assignment.get("job_id") != row.get("job_id") or assignment.get("policy_version_id") != row.get("policy_version_id"): reasons.append("owned_outcome_assignment_unmapped")
        if policy and _scope(policy) != _scope(row): reasons.append("owned_outcome_scope_mismatch")
        key = (row.get("content_id"), row.get("metric_window"))
        duplicate = next((item for item in self.data["outcomes"] if (item.get("content_id"), item.get("metric_window")) == key), None)
        if duplicate and duplicate.get("raw_response_hash") != row.get("raw_response_hash"): reasons.append("owned_outcome_conflicting_snapshot")
        if reasons: return {"accepted": False, "reason_codes": sorted(set(reasons))}
        if duplicate: return {"accepted": True, "outcome_id": duplicate["outcome_id"], "idempotent": True}
        record = {"outcome_id": f"outcome:{_hash([row['content_id'], row['raw_response_hash']])[:16]}", **row, "recorded_at": _now()}
        record["outcome_hash"] = _hash(record); self.data["outcomes"].append(record); self._save()
        return {"accepted": True, "outcome_id": record["outcome_id"], "idempotent": False}

    def evaluate(self, *, policy_version_id: str) -> dict[str, Any]:
        policy = self._find("policies", policy_version_id, "policy_version_id")
        if not policy: raise ValueError("policy_missing")
        scope = _scope(policy)
        candidate = [x for x in self.data["outcomes"] if _scope(x) == scope]
        treatments = [x for x in candidate if x["policy_version_id"] == policy_version_id and self._find("assignments", x["assignment_id"], "assignment_id")["arm"] == "treatment"]
        controls = [x for x in candidate if self._find("assignments", x["assignment_id"], "assignment_id")["arm"] == "control"]
        rows = sorted(treatments + controls, key=lambda x: x["published_at"])
        reasons=[]
        if len(rows) < MIN_TOTAL or len(treatments) < MIN_TOTAL//2 or len(controls) < MIN_TOTAL//2: reasons.append("minimum_cohort_not_met")
        holdout = rows[-24:] if len(rows) >= 24 else []
        h_t=[x for x in holdout if x in treatments]; h_c=[x for x in holdout if x in controls]
        if len(h_t)<MIN_HOLDOUT_PER_ARM or len(h_c)<MIN_HOLDOUT_PER_ARM: reasons.append("holdout_arm_minimum_not_met")
        if reasons: return {"version":"learning_evaluation_v1", "passed":False, "reason_codes":reasons}
        t=sum(log1p(float(x["metrics"]["views"])) for x in h_t)/len(h_t); c=sum(log1p(float(x["metrics"]["views"])) for x in h_c)/len(h_c)
        uplift=exp(t-c)-1
        passed=uplift >= .10
        approval = next((item for item in self.data["approvals"] if item.get("policy_version_id") == policy_version_id and ((_aware(item.get("expires_at")) or datetime.min.replace(tzinfo=timezone.utc)) > datetime.now(timezone.utc))), None)
        record={"version":"learning_evaluation_v1", "registry_record_type":"learning_registry_evaluation_v1", "registry_verified":True, "authorized":True, "holdout_passed":passed, "policy_enabled":bool(approval), "rollback_ref":policy.get("rollback_target_policy_version_id"), "rollback_policy_version_id":policy.get("rollback_target_policy_version_id"), "approval_id":approval.get("approval_id") if approval else None, "minimum_sample_count":MIN_TOTAL, "sample_count":len(rows), "method_version":"owned_holdout_log_views_v1", "policy_version_id":policy_version_id,"scope":scope,"holdout_outcome_ids_hash":_hash(sorted(x["outcome_id"] for x in holdout)),"treatment_n":len(h_t),"control_n":len(h_c),"metric":"log1p(views_72h)","relative_uplift":round(uplift,6),"passed":passed,"reason_codes":[] if passed else ["minimum_uplift_not_met"],"evaluated_at":_now()}
        record["evaluation_hash"]=_hash(record)
        if passed: record["assertion"]={"version":"owned_outcome_assertion_v1","assertion_id":f"assertion:{record['evaluation_hash'][:16]}","policy_version_id":policy_version_id,"claim_text":"满足预注册的自有内容 72 小时表现阈值","evaluation_hash":record["evaluation_hash"]}
        self.data["evaluations"].append(record); self._save(); return record
