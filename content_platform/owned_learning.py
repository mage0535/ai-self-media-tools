"""SQLite-only control plane for approved owned-content experiments.

This module never consumes public intelligence.  It is intentionally fail-closed:
missing registration, approval, receipt, native evidence, 72h window, or quality
proof prevents an outcome from influencing any learning decision.
"""
from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .owned_learning_verifier import claim_digest, verify_claim


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _scope_values(scope: tuple[str, str, str, str]) -> tuple[str, str, str, str]:
    if len(scope) != 4 or not all(str(value).strip() for value in scope):
        raise ValueError("scope_invalid")
    return (str(scope[0]).strip(), str(scope[1]).strip(), str(scope[2]).strip(), str(scope[3]).strip())


class OwnedLearningStore:
    """Deep module: one interface for policy, assignment, outcome and health."""

    SCHEMA_VERSION = 2

    def __init__(self, path: str | Path, *, automation_enabled: bool = False):
        self.path = Path(path)
        self.automation_enabled = bool(automation_enabled)
        self._init()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            if str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).casefold() != "wal":
                raise RuntimeError("owned_learning_wal_required")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS owned_learning_schema_migrations (
                    version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_policies (
                    policy_id TEXT PRIMARY KEY, platform TEXT NOT NULL, account_id TEXT NOT NULL,
                    lane TEXT NOT NULL, content_form TEXT NOT NULL, treatment_json TEXT NOT NULL,
                    rollback_policy_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    policy_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_approvals (
                    approval_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES owned_learning_policies(policy_id),
                    approver_id TEXT NOT NULL, max_exposure REAL NOT NULL, expires_at TEXT NOT NULL,
                    approval_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_experiments (
                    experiment_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES owned_learning_policies(policy_id),
                    approval_id TEXT NOT NULL REFERENCES owned_learning_approvals(approval_id),
                    platform TEXT NOT NULL, account_id TEXT NOT NULL, lane TEXT NOT NULL, content_form TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_experiment_per_scope
                  ON owned_learning_experiments(platform, account_id, lane, content_form) WHERE state='active';
                CREATE TABLE IF NOT EXISTS owned_learning_assignments (
                    job_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE,
                    experiment_id TEXT NOT NULL, policy_id TEXT NOT NULL REFERENCES owned_learning_policies(policy_id),
                    approval_id TEXT NOT NULL, arm TEXT NOT NULL CHECK(arm IN ('control','treatment')),
                    assignment_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_events (
                    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL, previous_digest TEXT NOT NULL DEFAULT '', event_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS owned_learning_events_no_update
                  BEFORE UPDATE ON owned_learning_events BEGIN SELECT RAISE(ABORT, 'owned_learning_events_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS owned_learning_events_no_delete
                  BEFORE DELETE ON owned_learning_events BEGIN SELECT RAISE(ABORT, 'owned_learning_events_append_only'); END;
                CREATE TABLE IF NOT EXISTS owned_learning_experiment_cards (
                    card_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES owned_learning_policies(policy_id),
                    scope_json TEXT NOT NULL, primary_metric TEXT NOT NULL, minimum_per_arm INTEGER NOT NULL,
                    minimum_effect REAL NOT NULL, quality_gate_digest TEXT NOT NULL, randomization_salt TEXT NOT NULL,
                    analysis_method TEXT NOT NULL, stop_rule TEXT NOT NULL, card_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_experiment_approvals (
                    approval_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES owned_learning_experiment_cards(card_id),
                    policy_digest TEXT NOT NULL, rollback_policy_digest TEXT NOT NULL, approver_id TEXT NOT NULL,
                    max_exposure REAL NOT NULL, expires_at TEXT NOT NULL, state TEXT NOT NULL,
                    approval_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owned_learning_strict_experiments (
                    experiment_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES owned_learning_experiment_cards(card_id),
                    approval_id TEXT NOT NULL REFERENCES owned_learning_experiment_approvals(approval_id),
                    state TEXT NOT NULL, created_at TEXT NOT NULL, activated_at TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '', account_id TEXT NOT NULL DEFAULT '', lane TEXT NOT NULL DEFAULT '', content_form TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS owned_learning_authorization_grants (
                    grant_id TEXT PRIMARY KEY, platform TEXT NOT NULL, account_id TEXT NOT NULL,
                    scope_json TEXT NOT NULL, evidence_digest TEXT NOT NULL, expires_at TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL,
                    issuer TEXT NOT NULL DEFAULT '', nonce TEXT NOT NULL DEFAULT '', claim_digest TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS owned_learning_grant_nonce_unique
                  ON owned_learning_authorization_grants(issuer, nonce) WHERE issuer<>'' AND nonce<>'';
                CREATE TABLE IF NOT EXISTS owned_learning_sealed_receipts (
                    receipt_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE REFERENCES owned_learning_assignments(assignment_id),
                    job_id TEXT NOT NULL, platform TEXT NOT NULL, account_id TEXT NOT NULL,
                    platform_content_id TEXT NOT NULL UNIQUE, quality_gate_digest TEXT NOT NULL,
                    evidence_digest TEXT NOT NULL, issuer TEXT NOT NULL, nonce TEXT NOT NULL,
                    claim_digest TEXT NOT NULL UNIQUE, verified_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    state TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS owned_learning_receipt_nonce_unique
                  ON owned_learning_sealed_receipts(issuer, nonce);
                CREATE TABLE IF NOT EXISTS owned_learning_analytics_claims (
                    claim_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL REFERENCES owned_learning_sealed_receipts(receipt_id),
                    response_digest TEXT NOT NULL, observed_at TEXT NOT NULL, published_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL, issuer TEXT NOT NULL, nonce TEXT NOT NULL,
                    claim_digest TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS owned_learning_analytics_nonce_unique
                  ON owned_learning_analytics_claims(issuer, nonce);
                CREATE TABLE IF NOT EXISTS owned_learning_outcomes (
                    outcome_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE REFERENCES owned_learning_assignments(assignment_id),
                    receipt_id TEXT NOT NULL UNIQUE, platform_content_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                    published_at TEXT NOT NULL, raw_evidence_sha256 TEXT NOT NULL, authorization_grant_id TEXT NOT NULL,
                    quality_gate_digest TEXT NOT NULL, metrics_json TEXT NOT NULL, outcome_digest TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_content_window ON owned_learning_outcomes(platform_content_id, observed_at);
                CREATE TABLE IF NOT EXISTS owned_learning_evaluations (
                    evaluation_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, status TEXT NOT NULL,
                    estimate REAL NOT NULL, ci_lower REAL NOT NULL, ci_upper REAL NOT NULL, sample_control INTEGER NOT NULL,
                    sample_treatment INTEGER NOT NULL, evaluation_digest TEXT NOT NULL, valid_until TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            # Forward-compatible schema evolution: r18 files may already contain
            # the grant table without verifier provenance columns.
            existing_grant_columns = {row[1] for row in conn.execute("PRAGMA table_info(owned_learning_authorization_grants)").fetchall()}
            for name, definition in {"issuer": "TEXT NOT NULL DEFAULT ''", "nonce": "TEXT NOT NULL DEFAULT ''", "claim_digest": "TEXT NOT NULL DEFAULT ''"}.items():
                if name not in existing_grant_columns:
                    conn.execute(f"ALTER TABLE owned_learning_authorization_grants ADD COLUMN {name} {definition}")
            strict_columns = {row[1] for row in conn.execute("PRAGMA table_info(owned_learning_strict_experiments)").fetchall()}
            for name in ("platform", "account_id", "lane", "content_form"):
                if name not in strict_columns:
                    conn.execute(f"ALTER TABLE owned_learning_strict_experiments ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            # Backfill legacy rows from their immutable card scope before enforcing
            # the physical partial-unique scope invariant.
            conn.execute("""UPDATE owned_learning_strict_experiments SET
                platform=json_extract(c.scope_json, '$[0]'), account_id=json_extract(c.scope_json, '$[1]'),
                lane=json_extract(c.scope_json, '$[2]'), content_form=json_extract(c.scope_json, '$[3]')
                FROM owned_learning_experiment_cards c
                WHERE c.card_id=owned_learning_strict_experiments.card_id
                  AND owned_learning_strict_experiments.platform=''""")
            conn.execute("DROP INDEX IF EXISTS one_strict_active_experiment_per_scope")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_strict_active_experiment_per_scope ON owned_learning_strict_experiments(platform, account_id, lane, content_form) WHERE state='active'")
            checksum = _digest({"schema": self.SCHEMA_VERSION, "module": "owned_learning"})
            conn.execute("INSERT OR IGNORE INTO owned_learning_schema_migrations VALUES(?,?,?)", (self.SCHEMA_VERSION, checksum, _now()))
            conn.commit()
        finally:
            conn.close()

    def _event(self, conn: sqlite3.Connection, event_type: str, entity_id: str, payload: dict[str, Any]) -> None:
        previous = conn.execute("SELECT event_digest FROM owned_learning_events ORDER BY rowid DESC LIMIT 1").fetchone()
        created_at = _now()
        record = {"event_type": event_type, "entity_id": entity_id, "payload": payload, "previous_digest": previous["event_digest"] if previous else "", "created_at": created_at}
        conn.execute("INSERT INTO owned_learning_events VALUES(?,?,?,?,?,?,?)", (f"event:{uuid.uuid4().hex}", event_type, entity_id, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), record["previous_digest"], _digest(record), created_at))

    def create_policy(self, *, platform: str, account_id: str, lane: str, content_form: str, treatment_vector: dict[str, Any], rollback_policy_id: str = "") -> dict[str, Any]:
        scope = _scope_values((platform, account_id, lane, content_form))
        if not isinstance(treatment_vector, dict) or not treatment_vector:
            raise ValueError("treatment_vector_missing")
        policy_id, created_at = f"policy:{uuid.uuid4().hex}", _now()
        payload = {"policy_id": policy_id, "scope": scope, "treatment_vector": treatment_vector, "rollback_policy_id": rollback_policy_id, "created_at": created_at}
        with self._connect() as conn:
            if rollback_policy_id and not conn.execute("SELECT 1 FROM owned_learning_policies WHERE policy_id=?", (rollback_policy_id,)).fetchone():
                raise ValueError("rollback_policy_missing")
            conn.execute("INSERT INTO owned_learning_policies VALUES(?,?,?,?,?,?,?,?,?,?)", (policy_id, *scope, json.dumps(treatment_vector, ensure_ascii=False, sort_keys=True), rollback_policy_id, "draft", _digest(payload), created_at))
            self._event(conn, "PolicyCreated", policy_id, payload)
        return {**payload, "policy_digest": _digest(payload)}

    def register_authorization_grant(self, *, claim: dict[str, Any]) -> dict[str, Any]:
        """Persist a verifier-signed, scope-bound authorization claim.

        Ordinary content workers cannot manufacture a grant: absent an externally
        provisioned verifier secret, ``verify_claim`` rejects before any DB write.
        """
        payload = verify_claim(claim, expected_kind="owned_analytics_grant")
        scope = _scope_values(tuple(payload.get("scope") or ()))
        if payload.get("platform") != scope[0] or payload.get("account_id") != scope[1] or not str(payload.get("evidence_digest") or "").strip():
            raise ValueError("authorization_grant_invalid")
        grant_id, created_at = f"grant:{uuid.uuid4().hex}", _now()
        digest = claim_digest(payload)
        with self._connect() as conn:
            conn.execute("INSERT INTO owned_learning_authorization_grants(grant_id,platform,account_id,scope_json,evidence_digest,expires_at,state,created_at,issuer,nonce,claim_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (grant_id, scope[0], scope[1], json.dumps(scope), str(payload["evidence_digest"]), str(payload["expires_at"]), "active", created_at, str(payload["issuer"]), str(payload["nonce"]), digest))
            self._event(conn, "AuthorizationGrantRegistered", grant_id, {"claim_digest": digest, "scope": scope, "issuer": payload["issuer"]})
        return {"grant_id": grant_id, "scope": scope, "claim_digest": digest, "expires_at": payload["expires_at"]}

    def seal_verified_postcheck(self, *, claim: dict[str, Any]) -> dict[str, Any]:
        """Create the only receipt form accepted by owned outcome intake."""
        payload = verify_claim(claim, expected_kind="owned_postcheck")
        required = ("receipt_id", "assignment_id", "job_id", "platform", "account_id", "platform_content_id", "quality_gate_digest", "evidence_digest", "verified_at")
        if any(not str(payload.get(key) or "").strip() for key in required):
            raise ValueError("postcheck_claim_invalid")
        digest, created_at = claim_digest(payload), _now()
        with self._connect() as conn:
            assignment = conn.execute("SELECT * FROM owned_learning_assignments WHERE assignment_id=?", (payload["assignment_id"],)).fetchone()
            if not assignment or assignment["job_id"] != payload["job_id"]:
                raise ValueError("postcheck_assignment_mismatch")
            strict = conn.execute("SELECT c.scope_json,c.quality_gate_digest FROM owned_learning_strict_experiments e JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id WHERE e.experiment_id=? AND e.state='active'", (assignment["experiment_id"],)).fetchone()
            if not strict or tuple(json.loads(strict["scope_json"]))[:2] != (payload["platform"], payload["account_id"]) or strict["quality_gate_digest"] != payload["quality_gate_digest"]:
                raise ValueError("postcheck_scope_or_quality_mismatch")
            conn.execute("INSERT INTO owned_learning_sealed_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (payload["receipt_id"], payload["assignment_id"], payload["job_id"], payload["platform"], payload["account_id"], payload["platform_content_id"], payload["quality_gate_digest"], payload["evidence_digest"], payload["issuer"], payload["nonce"], digest, payload["verified_at"], payload["expires_at"], "verified", created_at))
            self._event(conn, "OwnedPostcheckSealed", payload["receipt_id"], {"assignment_id": payload["assignment_id"], "claim_digest": digest})
        return {"receipt_id": payload["receipt_id"], "claim_digest": digest, "verified_at": payload["verified_at"]}

    def register_analytics_claim(self, *, claim: dict[str, Any]) -> dict[str, Any]:
        """Persist signed native analytics evidence before outcome derivation."""
        payload = verify_claim(claim, expected_kind="owned_analytics_72h")
        required = ("receipt_id", "response_digest", "observed_at", "published_at")
        if any(not str(payload.get(key) or "").strip() for key in required) or not isinstance(payload.get("metrics"), dict):
            raise ValueError("analytics_claim_invalid")
        digest, claim_id, created_at = claim_digest(payload), f"analytics:{uuid.uuid4().hex}", _now()
        with self._connect() as conn:
            receipt = conn.execute("SELECT * FROM owned_learning_sealed_receipts WHERE receipt_id=? AND state='verified'", (payload["receipt_id"],)).fetchone()
            if not receipt or receipt["expires_at"] <= _now():
                raise ValueError("analytics_receipt_invalid")
            conn.execute("INSERT INTO owned_learning_analytics_claims VALUES(?,?,?,?,?,?,?,?,?,?,?)", (claim_id, payload["receipt_id"], payload["response_digest"], payload["observed_at"], payload["published_at"], json.dumps(payload["metrics"], sort_keys=True), payload["issuer"], payload["nonce"], digest, payload["expires_at"], created_at))
            self._event(conn, "OwnedAnalyticsSealed", claim_id, {"receipt_id": payload["receipt_id"], "claim_digest": digest})
        return {"claim_id": claim_id, "receipt_id": payload["receipt_id"], "claim_digest": digest}

    # Legacy methods remain for historical test fixtures; production must use card methods below.
    def approve(self, *, policy_id: str, approver_id: str, max_exposure: float, expires_in_days: int = 30) -> dict[str, Any]:
        if not approver_id or not (0 < float(max_exposure) <= 0.5): raise ValueError("approval_invalid")
        with self._connect() as conn:
            if not conn.execute("SELECT 1 FROM owned_learning_policies WHERE policy_id=?", (policy_id,)).fetchone(): raise ValueError("policy_missing")
            approval_id, created_at = f"approval:{uuid.uuid4().hex}", _now(); expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(timespec="seconds")
            payload = {"approval_id": approval_id, "policy_id": policy_id, "approver_id": approver_id, "max_exposure": float(max_exposure), "expires_at": expires_at, "created_at": created_at}
            conn.execute("INSERT INTO owned_learning_approvals VALUES(?,?,?,?,?,?,?)", (approval_id, policy_id, approver_id, float(max_exposure), expires_at, _digest(payload), created_at)); self._event(conn, "LegacyPolicyApproved", approval_id, payload)
        return {**payload, "approval_digest": _digest(payload)}

    def activate(self, *, policy_id: str, approval_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            policy = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (policy_id,)).fetchone(); approval = conn.execute("SELECT * FROM owned_learning_approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not policy or not approval or approval["policy_id"] != policy_id or approval["expires_at"] <= _now() or not policy["rollback_policy_id"]: raise ValueError("activation_invalid")
            scope = tuple(policy[k] for k in ("platform", "account_id", "lane", "content_form")); target = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (policy["rollback_policy_id"],)).fetchone()
            if not target or tuple(target[k] for k in ("platform", "account_id", "lane", "content_form")) != scope: raise ValueError("rollback_policy_invalid")
            experiment_id, now = f"experiment:{uuid.uuid4().hex}", _now(); conn.execute("INSERT INTO owned_learning_experiments VALUES(?,?,?,?,?,?,?,?,?,?)", (experiment_id, policy_id, approval_id, *scope, "active", now, now)); conn.execute("UPDATE owned_learning_policies SET status='active' WHERE policy_id=?", (policy_id,)); self._event(conn, "LegacyExperimentActivated", experiment_id, {"policy_id": policy_id, "approval_id": approval_id})
        return {"experiment_id": experiment_id, "policy_id": policy_id, "approval_id": approval_id, "state": "active", "scope": scope}

    def create_experiment_card(self, *, policy_id: str, primary_metric: str, minimum_per_arm: int, minimum_effect: float, quality_gate_digest: str, randomization_salt: str, analysis_method: str, stop_rule: str) -> dict[str, Any]:
        required = [primary_metric, quality_gate_digest, randomization_salt, analysis_method, stop_rule]
        if not all(isinstance(x, str) and x.strip() for x in required) or int(minimum_per_arm) < 2 or float(minimum_effect) < 0:
            raise ValueError("experiment_card_invalid")
        with self._connect() as conn:
            policy = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (policy_id,)).fetchone()
            if not policy or not policy["rollback_policy_id"]: raise ValueError("experiment_card_invalid")
            scope = tuple(policy[k] for k in ("platform", "account_id", "lane", "content_form")); card_id, created_at = f"card:{uuid.uuid4().hex}", _now()
            payload = {"card_id": card_id, "policy_id": policy_id, "scope": scope, "primary_metric": primary_metric, "minimum_per_arm": int(minimum_per_arm), "minimum_effect": float(minimum_effect), "quality_gate_digest": quality_gate_digest, "randomization_salt": randomization_salt, "analysis_method": analysis_method, "stop_rule": stop_rule, "created_at": created_at}
            conn.execute("INSERT INTO owned_learning_experiment_cards VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (card_id, policy_id, json.dumps(scope), primary_metric, int(minimum_per_arm), float(minimum_effect), quality_gate_digest, randomization_salt, analysis_method, stop_rule, _digest(payload), created_at)); self._event(conn, "ExperimentCardRegistered", card_id, payload)
        return {**payload, "card_digest": _digest(payload)}

    def approve_experiment(self, *, card_id: str, approver_id: str, max_exposure: float, expires_in_days: int = 30) -> dict[str, Any]:
        if not approver_id or not (0 < float(max_exposure) <= 0.5): raise ValueError("approval_invalid")
        with self._connect() as conn:
            card = conn.execute("SELECT * FROM owned_learning_experiment_cards WHERE card_id=?", (card_id,)).fetchone()
            if not card: raise ValueError("experiment_card_missing")
            policy = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (card["policy_id"],)).fetchone(); rollback = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (policy["rollback_policy_id"],)).fetchone() if policy else None
            if not policy or not rollback: raise ValueError("rollback_policy_invalid")
            approval_id, created_at = f"approval:{uuid.uuid4().hex}", _now(); expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat(timespec="seconds")
            payload = {"approval_id": approval_id, "card_id": card_id, "policy_digest": policy["policy_digest"], "rollback_policy_digest": rollback["policy_digest"], "approver_id": approver_id, "max_exposure": float(max_exposure), "expires_at": expires_at, "created_at": created_at}
            conn.execute("INSERT INTO owned_learning_experiment_approvals VALUES(?,?,?,?,?,?,?,?,?,?)", (approval_id, card_id, policy["policy_digest"], rollback["policy_digest"], approver_id, float(max_exposure), expires_at, "approved", _digest(payload), created_at)); self._event(conn, "ExperimentApproved", approval_id, payload)
        return {**payload, "approval_digest": _digest(payload)}

    def activate_experiment(self, *, card_id: str, approval_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            card = conn.execute("SELECT * FROM owned_learning_experiment_cards WHERE card_id=?", (card_id,)).fetchone(); approval = conn.execute("SELECT * FROM owned_learning_experiment_approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not card or not approval or approval["card_id"] != card_id or approval["state"] != "approved" or approval["expires_at"] <= _now(): raise ValueError("activation_invalid")
            policy = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (card["policy_id"],)).fetchone()
            if not policy or approval["policy_digest"] != policy["policy_digest"]: raise ValueError("activation_invalid")
            scope = tuple(json.loads(card["scope_json"]))
            active_cards = conn.execute("""SELECT c.scope_json FROM owned_learning_strict_experiments e
                JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id WHERE e.state='active'""").fetchall()
            if any(tuple(json.loads(item["scope_json"])) == scope for item in active_cards):
                raise ValueError("experiment_scope_already_active")
            experiment_id, now = f"experiment:{uuid.uuid4().hex}", _now()
            conn.execute("INSERT INTO owned_learning_strict_experiments(experiment_id,card_id,approval_id,state,created_at,activated_at,platform,account_id,lane,content_form) VALUES(?,?,?,?,?,?,?,?,?,?)", (experiment_id, card_id, approval_id, "active", now, now, *scope))
            self._event(conn, "ExperimentActivated", experiment_id, {"card_id": card_id, "approval_id": approval_id, "scope": scope})
        return {"experiment_id": experiment_id, "card_id": card_id, "approval_id": approval_id, "state": "active"}

    def _projection(self, row: sqlite3.Row, *, bucket: float) -> dict[str, Any]:
        return {"assignment_id": row["assignment_id"], "job_id": row["job_id"], "experiment_id": row["experiment_id"], "policy_id": row["policy_id"], "approval_id": row["approval_id"], "arm": row["arm"], "bucket": bucket, "created_at": row["created_at"]}

    def decide(self, *, job_id: str, scope: tuple[str, str, str, str]) -> dict[str, Any]:
        with self._connect() as conn:
            return self.decide_in_transaction(conn, job_id=job_id, scope=scope, allow_legacy=True)

    def decide_in_transaction(self, conn: sqlite3.Connection, *, job_id: str, scope: tuple[str, str, str, str], allow_legacy: bool = False) -> dict[str, Any]:
        """Assign within the caller's BEGIN IMMEDIATE transaction.

        Pipeline.create uses this seam so the job record and its frozen decision
        commit or roll back together.
        """
        scope = _scope_values(scope)
        existing = conn.execute("SELECT * FROM owned_learning_assignments WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            return self._projection(existing, bucket=int(_digest([job_id, existing["experiment_id"]])[:16], 16) / float(0xFFFFFFFFFFFFFFFF))
        strict = conn.execute("""SELECT e.*,c.policy_id,c.scope_json,c.randomization_salt,a.max_exposure,a.expires_at
            FROM owned_learning_strict_experiments e JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id
            JOIN owned_learning_experiment_approvals a ON a.approval_id=e.approval_id WHERE e.state='active'""").fetchall()
        candidate = next((r for r in strict if tuple(json.loads(r["scope_json"])) == scope and r["expires_at"] > _now()), None)
        if candidate:
            experiment_id, policy_id, approval_id, exposure, salt = candidate["experiment_id"], candidate["policy_id"], candidate["approval_id"], float(candidate["max_exposure"]), candidate["randomization_salt"]
        elif allow_legacy:
            legacy = conn.execute("SELECT * FROM owned_learning_experiments WHERE platform=? AND account_id=? AND lane=? AND content_form=? AND state='active'", scope).fetchone()
            if not legacy:
                raise ValueError("experiment_not_active")
            approval = conn.execute("SELECT * FROM owned_learning_approvals WHERE approval_id=?", (legacy["approval_id"],)).fetchone()
            if not approval or approval["expires_at"] <= _now():
                raise ValueError("approval_expired")
            experiment_id, policy_id, approval_id, exposure, salt = legacy["experiment_id"], legacy["policy_id"], approval["approval_id"], float(approval["max_exposure"]), legacy["experiment_id"]
        else:
            raise ValueError("experiment_not_active")
        total = conn.execute("SELECT COUNT(*) n FROM owned_learning_assignments WHERE experiment_id=?", (experiment_id,)).fetchone()["n"]
        treated = conn.execute("SELECT COUNT(*) n FROM owned_learning_assignments WHERE experiment_id=? AND arm='treatment'", (experiment_id,)).fetchone()["n"]
        bucket = int(_digest([job_id, salt])[:16], 16) / float(0xFFFFFFFFFFFFFFFF)
        cap = int((total + 1) * exposure)
        arm = "treatment" if bucket < exposure and treated < cap else "control"
        assignment_id, created_at = f"assignment:{uuid.uuid4().hex}", _now()
        payload = {"assignment_id": assignment_id, "job_id": job_id, "experiment_id": experiment_id, "policy_id": policy_id, "approval_id": approval_id, "arm": arm, "bucket": bucket, "created_at": created_at}
        conn.execute("INSERT INTO owned_learning_assignments VALUES(?,?,?,?,?,?,?,?)", (job_id, assignment_id, experiment_id, policy_id, approval_id, arm, _digest(payload), created_at))
        self._event(conn, "AssignmentCreated", assignment_id, payload)
        return payload

    def record_outcome(self, *, authorization_grant_id: str, analytics_claim_id: str) -> dict[str, Any]:
        """Derive one outcome exclusively from sealed verifier records.

        No caller-provided receipt, timestamps, quality digest, raw evidence or
        metrics are accepted here; those values are read back from immutable
        signed-claim projections.
        """
        if not authorization_grant_id or not analytics_claim_id:
            raise ValueError("outcome_evidence_invalid")
        with self._connect() as conn:
            analytics = conn.execute("SELECT * FROM owned_learning_analytics_claims WHERE claim_id=?", (analytics_claim_id,)).fetchone()
            receipt = conn.execute("SELECT * FROM owned_learning_sealed_receipts WHERE receipt_id=?", (analytics["receipt_id"],)).fetchone() if analytics else None
            if not analytics or not receipt or receipt["state"] != "verified" or receipt["expires_at"] <= _now():
                raise ValueError("outcome_evidence_invalid")
            assignment = conn.execute("SELECT * FROM owned_learning_assignments WHERE assignment_id=?", (receipt["assignment_id"],)).fetchone()
            strict = conn.execute("SELECT e.*,c.primary_metric,c.quality_gate_digest,c.scope_json FROM owned_learning_strict_experiments e JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id WHERE e.experiment_id=? AND e.state='active'", (assignment["experiment_id"],)).fetchone() if assignment else None
            grant = conn.execute("SELECT * FROM owned_learning_authorization_grants WHERE grant_id=?", (authorization_grant_id,)).fetchone()
            metrics = json.loads(analytics["metrics_json"] or "{}")
            if not assignment or not strict or not grant or grant["state"] != "active" or grant["expires_at"] <= _now() or tuple(json.loads(grant["scope_json"])) != tuple(json.loads(strict["scope_json"])) or receipt["quality_gate_digest"] != strict["quality_gate_digest"] or receipt["job_id"] != assignment["job_id"] or strict["primary_metric"] not in metrics:
                raise ValueError("outcome_evidence_invalid")
            observed, published = _parse_time(analytics["observed_at"]), _parse_time(analytics["published_at"])
            elapsed = (observed - published).total_seconds()
            if observed > datetime.now(timezone.utc) + timedelta(minutes=5) or elapsed < 72 * 3600 or elapsed > 72 * 3600 + 300:
                raise ValueError("outcome_window_invalid")
            outcome_id, created_at = f"outcome:{uuid.uuid4().hex}", _now()
            payload = {"outcome_id": outcome_id, "assignment_id": assignment["assignment_id"], "receipt_id": receipt["receipt_id"], "platform_content_id": receipt["platform_content_id"], "observed_at": analytics["observed_at"], "published_at": analytics["published_at"], "raw_evidence_sha256": analytics["response_digest"], "authorization_grant_id": authorization_grant_id, "quality_gate_digest": receipt["quality_gate_digest"], "metrics": metrics, "created_at": created_at}
            conn.execute("INSERT INTO owned_learning_outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (outcome_id, assignment["assignment_id"], receipt["receipt_id"], receipt["platform_content_id"], analytics["observed_at"], analytics["published_at"], analytics["response_digest"], authorization_grant_id, receipt["quality_gate_digest"], json.dumps(metrics, sort_keys=True), _digest(payload), created_at))
            self._event(conn, "OwnedOutcomeRecorded", outcome_id, {"receipt_id": receipt["receipt_id"], "analytics_claim_id": analytics_claim_id, "outcome_digest": _digest(payload)})
        return {**payload, "outcome_digest": _digest(payload)}

    def evaluate_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT e.*,c.primary_metric,c.minimum_per_arm,c.minimum_effect FROM owned_learning_strict_experiments e JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id WHERE e.experiment_id=?", (experiment_id,)).fetchone()
            if not row: raise ValueError("experiment_missing")
            outcomes = conn.execute("SELECT a.arm,o.metrics_json FROM owned_learning_assignments a JOIN owned_learning_outcomes o ON o.assignment_id=a.assignment_id WHERE a.experiment_id=?", (experiment_id,)).fetchall(); metric = row["primary_metric"]
            groups = {"control": [], "treatment": []}
            for item in outcomes:
                groups[item["arm"]].append(float(json.loads(item["metrics_json"]).get(metric, 0) or 0))
            n0, n1 = len(groups["control"]), len(groups["treatment"]); estimate=ci_lower=ci_upper=0.0; status="inconclusive"
            if n0 >= row["minimum_per_arm"] and n1 >= row["minimum_per_arm"] and sum(groups["control"]) > 0:
                estimate = sum(groups["treatment"])/n1 / (sum(groups["control"])/n0) - 1; rng = random.Random(_digest([experiment_id, metric, n0, n1])); samples=[]
                for _ in range(400): samples.append(sum(rng.choice(groups["treatment"]) for _ in range(n1))/n1 / (sum(rng.choice(groups["control"]) for _ in range(n0))/n0) - 1)
                samples.sort(); ci_lower, ci_upper = samples[9], samples[389]; status = "pass" if ci_lower >= float(row["minimum_effect"]) else "fail"
            evaluation_id, created_at = f"evaluation:{uuid.uuid4().hex}", _now(); valid_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds"); payload = {"evaluation_id": evaluation_id, "experiment_id": experiment_id, "status": status, "estimate": estimate, "ci_lower": ci_lower, "ci_upper": ci_upper, "sample_control": n0, "sample_treatment": n1, "valid_until": valid_until, "created_at": created_at}
            conn.execute("INSERT INTO owned_learning_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?)", (evaluation_id, experiment_id, status, estimate, ci_lower, ci_upper, n0, n1, _digest(payload), valid_until, created_at)); self._event(conn, "ExperimentEvaluated", evaluation_id, payload)
        return {**payload, "evaluation_digest": _digest(payload), "eligible_for_automation": status == "pass", "allow_automated_learning": status == "pass" and self.automation_enabled}

    def verify_event_chain(self) -> dict[str, Any]:
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        try:
            previous = ""
            for row in conn.execute("SELECT * FROM owned_learning_events ORDER BY rowid"):
                payload = json.loads(row["payload_json"]); record = {"event_type": row["event_type"], "entity_id": row["entity_id"], "payload": payload, "previous_digest": previous, "created_at": row["created_at"]}
                if row["previous_digest"] != previous or row["event_digest"] != _digest(record): return {"valid": False, "reason": "event_chain_invalid"}
                previous = row["event_digest"]
            return {"valid": True, "head": previous}
        finally: conn.close()

    def _verify_control_plane(self, conn: sqlite3.Connection, experiment_id: str) -> tuple[bool, str, sqlite3.Row | None]:
        row = conn.execute("""SELECT e.*,c.policy_id,c.scope_json,c.card_digest,c.quality_gate_digest,
            a.state approval_state,a.expires_at approval_expires,a.policy_digest approved_policy_digest,
            a.rollback_policy_digest,a.approval_digest
            FROM owned_learning_strict_experiments e
            JOIN owned_learning_experiment_cards c ON c.card_id=e.card_id
            JOIN owned_learning_experiment_approvals a ON a.approval_id=e.approval_id
            WHERE e.experiment_id=?""", (experiment_id,)).fetchone()
        if not row or row["state"] != "active" or row["approval_state"] != "approved" or row["approval_expires"] <= _now():
            return False, "experiment_or_approval_inactive", row
        policy = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (row["policy_id"],)).fetchone()
        rollback = conn.execute("SELECT * FROM owned_learning_policies WHERE policy_id=?", (policy["rollback_policy_id"],)).fetchone() if policy else None
        if not policy or not rollback or tuple(policy[k] for k in ("platform", "account_id", "lane", "content_form")) != tuple(rollback[k] for k in ("platform", "account_id", "lane", "content_form")):
            return False, "rollback_policy_invalid", row
        policy_payload = {"policy_id": policy["policy_id"], "scope": tuple(policy[k] for k in ("platform", "account_id", "lane", "content_form")), "treatment_vector": json.loads(policy["treatment_json"]), "rollback_policy_id": policy["rollback_policy_id"], "created_at": policy["created_at"]}
        if policy["policy_digest"] != _digest(policy_payload) or row["approved_policy_digest"] != policy["policy_digest"] or row["rollback_policy_digest"] != rollback["policy_digest"]:
            return False, "policy_digest_drift", row
        card = conn.execute("SELECT * FROM owned_learning_experiment_cards WHERE card_id=?", (row["card_id"],)).fetchone()
        card_payload = {"card_id": card["card_id"], "policy_id": card["policy_id"], "scope": tuple(json.loads(card["scope_json"])), "primary_metric": card["primary_metric"], "minimum_per_arm": card["minimum_per_arm"], "minimum_effect": card["minimum_effect"], "quality_gate_digest": card["quality_gate_digest"], "randomization_salt": card["randomization_salt"], "analysis_method": card["analysis_method"], "stop_rule": card["stop_rule"], "created_at": card["created_at"]}
        if card["card_digest"] != _digest(card_payload):
            return False, "card_digest_drift", row
        approval = conn.execute("SELECT * FROM owned_learning_experiment_approvals WHERE approval_id=?", (row["approval_id"],)).fetchone()
        approval_payload = {"approval_id": approval["approval_id"], "card_id": approval["card_id"], "policy_digest": approval["policy_digest"], "rollback_policy_digest": approval["rollback_policy_digest"], "approver_id": approval["approver_id"], "max_exposure": approval["max_exposure"], "expires_at": approval["expires_at"], "created_at": approval["created_at"]}
        if approval["approval_digest"] != _digest(approval_payload):
            return False, "approval_digest_drift", row
        return True, "ok", row

    def rollback_experiment(self, *, experiment_id: str, reason: str, actor: str) -> dict[str, Any]:
        if not str(reason).strip() or not str(actor).strip():
            raise ValueError("rollback_invalid")
        with self._connect() as conn:
            valid, _, row = self._verify_control_plane(conn, experiment_id)
            if not row:
                raise ValueError("experiment_missing")
            conn.execute("UPDATE owned_learning_strict_experiments SET state='rolled_back' WHERE experiment_id=? AND state='active'", (experiment_id,))
            self._event(conn, "ExperimentRolledBack", experiment_id, {"reason": reason, "actor": actor, "control_plane_valid_before_rollback": valid})
        return {"experiment_id": experiment_id, "state": "rolled_back", "reason": reason}

    def resolve_treatment(self, *, assignment_id: str, scope: tuple[str, str, str, str], explicit_enable: bool = False) -> dict[str, Any]:
        """Return a minimal server-side policy projection, defaulting to control."""
        scope = _scope_values(scope)
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        try:
            assignment = conn.execute("SELECT * FROM owned_learning_assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
            if not assignment or assignment["arm"] != "treatment" or not explicit_enable:
                return {"arm": "control", "reason": "treatment_not_explicitly_enabled"}
            valid, reason, row = self._verify_control_plane(conn, assignment["experiment_id"])
            health = self.strategy_health(assignment["experiment_id"])
            if not valid or row is None or not health.get("allow_automated_learning") or tuple(json.loads(row["scope_json"])) != scope:
                return {"arm": "control", "reason": reason if not valid else "health_not_pass"}
            policy = conn.execute("SELECT treatment_json,policy_digest FROM owned_learning_policies WHERE policy_id=?", (assignment["policy_id"],)).fetchone()
            return {"arm": "treatment", "policy_digest": policy["policy_digest"], "treatment": json.loads(policy["treatment_json"])}
        finally:
            conn.close()

    def strategy_health(self, experiment_id: str) -> dict[str, Any]:
        chain = self.verify_event_chain()
        if not chain["valid"]: return {"experiment_id": experiment_id, "status": "revoked", "allow_automated_learning": False, "reason": chain["reason"]}
        conn = sqlite3.connect(self.path); conn.row_factory = sqlite3.Row
        try:
            valid, reason, _ = self._verify_control_plane(conn, experiment_id)
            if not valid:
                return {"experiment_id": experiment_id, "status": "revoked", "allow_automated_learning": False, "reason": reason}
            evaluation = conn.execute("SELECT * FROM owned_learning_evaluations WHERE experiment_id=? ORDER BY created_at DESC LIMIT 1", (experiment_id,)).fetchone()
            if not evaluation: return {"experiment_id": experiment_id, "status": "pending", "allow_automated_learning": False}
            if evaluation["valid_until"] <= _now(): return {"experiment_id": experiment_id, "status": "stale", "allow_automated_learning": False}
            return {"experiment_id": experiment_id, "evaluation_id": evaluation["evaluation_id"], "status": evaluation["status"], "eligible_for_automation": evaluation["status"] == "pass", "allow_automated_learning": evaluation["status"] == "pass" and self.automation_enabled, "evaluation_digest": evaluation["evaluation_digest"], "event_chain_head": chain["head"]}
        finally: conn.close()

    def tamper_for_test(self, experiment_id: str) -> None:
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("DROP TRIGGER owned_learning_events_no_update"); conn.execute("UPDATE owned_learning_events SET payload_json='{}' WHERE rowid=(SELECT min(rowid) FROM owned_learning_events)"); conn.commit()
        finally: conn.close()
