"""Durable delivery intents, verified publication identities, and metric windows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


VERIFIED_LEVELS = {"url_verified", "postcheck_verified", "management_page_verified"}
NON_PUBLICATION_STATUSES = {"drafted", "handoff_pending", "handoff_ready", "review_required", "scheduled", "created"}
REQUIRED_METRICS = ("views", "likes", "comments", "shares", "favorites", "saves", "followers", "follows")
REVIEW_RESULTS = {"auth_failed", "authentication_failed", "conflict", "conflicting_match", "inconclusive", "query_failed"}


@dataclass(frozen=True)
class PublicationIdentity:
    platform: str
    internal_account_alias: str
    platform_content_id: str
    canonical_url: str
    published_at: str
    verification_level: str
    identity_source: str


class _ManagedConnection(sqlite3.Connection):
    """Close SQLite handles after the transaction context exits on Windows."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    return _now(value).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _description_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def verification_level_for_source(source: str) -> str:
    normalized = str(source or "").casefold()
    if "management" in normalized:
        return "management_page_verified"
    if any(token in normalized for token in ("postcheck", "api", "browser")):
        return "postcheck_verified"
    if any(token in normalized for token in ("url_probe", "public_url", "canonical_url")):
        return "url_verified"
    return ""


class PublicationLedger:
    """SQLite state machine shared by delivery, postcheck, and metric collection."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30, factory=_ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS delivery_intents (
                    intent_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL,
                    internal_account_alias TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    media_hashes_json TEXT NOT NULL DEFAULT '[]',
                    expected_title TEXT NOT NULL DEFAULT '',
                    expected_description TEXT NOT NULL DEFAULT '',
                    expected_description_digest TEXT NOT NULL DEFAULT '',
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    absence_window_seconds INTEGER NOT NULL DEFAULT 3600,
                    status TEXT NOT NULL DEFAULT 'created',
                    retry_allowed INTEGER NOT NULL DEFAULT 0,
                    review_reason TEXT NOT NULL DEFAULT '',
                    unknown_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL REFERENCES delivery_intents(intent_id),
                    attempt_no INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    external_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(intent_id, attempt_no)
                );
                CREATE TABLE IF NOT EXISTS delivery_leases (
                    intent_id TEXT PRIMARY KEY REFERENCES delivery_intents(intent_id),
                    attempt_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_retries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent_id TEXT NOT NULL REFERENCES delivery_intents(intent_id),
                    reason TEXT NOT NULL,
                    eligible_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publication_identities (
                    id INTEGER PRIMARY KEY,
                    platform TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    internal_account_alias TEXT NOT NULL DEFAULT '',
                    platform_content_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    verification_level TEXT NOT NULL,
                    identity_source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(platform, account_id, platform_content_id)
                );
                CREATE TABLE IF NOT EXISTS metric_windows (
                    id INTEGER PRIMARY KEY,
                    identity_id INTEGER NOT NULL REFERENCES publication_identities(id),
                    hours INTEGER NOT NULL,
                    due_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    invalidated_reason TEXT NOT NULL DEFAULT '',
                    UNIQUE(identity_id, hours)
                );
                CREATE TABLE IF NOT EXISTS metric_observations (
                    id INTEGER PRIMARY KEY,
                    window_id INTEGER NOT NULL REFERENCES metric_windows(id),
                    platform TEXT NOT NULL DEFAULT '',
                    internal_account_alias TEXT NOT NULL DEFAULT '',
                    platform_content_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'unknown',
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_collection_attempts (
                    id INTEGER PRIMARY KEY,
                    window_id INTEGER NOT NULL REFERENCES metric_windows(id),
                    state TEXT NOT NULL,
                    error TEXT NOT NULL,
                    attempted_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS metric_collection_leases (
                    window_id INTEGER PRIMARY KEY REFERENCES metric_windows(id),
                    attempt_id INTEGER NOT NULL REFERENCES metric_collection_attempts(id),
                    owner TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_collection_retries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    window_id INTEGER NOT NULL REFERENCES metric_windows(id),
                    reason TEXT NOT NULL,
                    eligible_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._migrate(conn)

    @staticmethod
    def _ensure_column(conn, table: str, name: str, definition: str):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _migrate(self, conn):
        self._ensure_column(conn, "publication_identities", "internal_account_alias", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "metric_windows", "invalidated_reason", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column(conn, "metric_collection_attempts", "finished_at", "TEXT NOT NULL DEFAULT ''")
        for name, definition in {
            "platform": "TEXT NOT NULL DEFAULT ''",
            "internal_account_alias": "TEXT NOT NULL DEFAULT ''",
            "platform_content_id": "TEXT NOT NULL DEFAULT ''",
            "confidence": "TEXT NOT NULL DEFAULT 'unknown'",
        }.items():
            self._ensure_column(conn, "metric_observations", name, definition)

    def create_delivery_intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        platform = str(payload.get("platform") or "").strip()
        alias = str(payload.get("internal_account_alias") or payload.get("account_alias") or payload.get("account_id") or "").strip()
        action = str(payload.get("action") or "publish").strip()
        if not platform or not alias or not action:
            raise ValueError("delivery intent requires platform, internal account alias, and action")
        body = payload.get("payload") if "payload" in payload else payload.get("platform_payload", {})
        body = body if isinstance(body, dict) else {"value": body}
        media_hashes = list(payload.get("media_hashes") or [])
        expected_title = str(payload.get("expected_title") or body.get("title") or "")
        expected_description = str(payload.get("expected_description") or body.get("description") or body.get("caption") or body.get("text") or body.get("markdown") or "")
        scheduled_at = str(payload.get("scheduled_at") or payload.get("schedule") or "")
        immutable = {
            "job_id": str(payload.get("job_id") or ""),
            "platform": platform,
            "internal_account_alias": alias,
            "action": action,
            "payload_hash": str(payload.get("payload_hash") or _digest(body)),
            "payload_json": _json(body),
            "media_hashes_json": _json(media_hashes),
            "expected_title": expected_title,
            "expected_description": expected_description,
            "expected_description_digest": str(payload.get("expected_description_digest") or _description_digest(expected_description)),
            "scheduled_at": scheduled_at,
            "absence_window_seconds": int(payload.get("absence_window_seconds") or 3600),
        }
        idempotency_key = str(payload.get("idempotency_key") or (
            f"delivery:{immutable['job_id']}:{platform}:{action}"
            if immutable["job_id"]
            else _digest({k: immutable[k] for k in immutable if k != "payload_json"})
        ))
        intent_id = str(payload.get("intent_id") or f"di_{idempotency_key[:32]}")
        now = _iso()
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM delivery_intents WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                row = dict(existing)
                for key in immutable:
                    if str(row.get(key, "")) != str(immutable[key]):
                        raise ValueError("delivery intent is immutable")
                return row
            conn.execute(
                """INSERT INTO delivery_intents(
                    intent_id,idempotency_key,job_id,platform,internal_account_alias,action,payload_hash,payload_json,
                    media_hashes_json,expected_title,expected_description,expected_description_digest,scheduled_at,
                    absence_window_seconds,status,retry_allowed,review_reason,unknown_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    intent_id, idempotency_key, immutable["job_id"], immutable["platform"], immutable["internal_account_alias"],
                    immutable["action"], immutable["payload_hash"], immutable["payload_json"], immutable["media_hashes_json"],
                    immutable["expected_title"], immutable["expected_description"], immutable["expected_description_digest"],
                    immutable["scheduled_at"], immutable["absence_window_seconds"], "created", 0, "", "", now, now,
                ),
            )
            return dict(conn.execute("SELECT * FROM delivery_intents WHERE intent_id=?", (intent_id,)).fetchone())

    create_intent = create_delivery_intent

    def get_delivery_intent(self, intent_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM delivery_intents WHERE intent_id=?", (str(intent_id),)).fetchone()
        if not row:
            raise KeyError(f"delivery intent not found: {intent_id}")
        result = dict(row)
        result["media_hashes"] = json.loads(result.pop("media_hashes_json") or "[]")
        result["payload"] = json.loads(result.pop("payload_json") or "{}")
        result["retry_allowed"] = bool(result["retry_allowed"])
        return result

    get_intent = get_delivery_intent

    def begin_attempt(self, intent_id: str, owner: str, lease_seconds: int = 300, now: datetime | str | None = None) -> dict[str, Any]:
        started = _now(now)
        attempt_id = f"da_{uuid.uuid4().hex}"
        expires = _iso(started + timedelta(seconds=int(lease_seconds)))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            intent = conn.execute("SELECT * FROM delivery_intents WHERE intent_id=?", (intent_id,)).fetchone()
            if not intent:
                raise KeyError(f"delivery intent not found: {intent_id}")
            if intent["status"] not in {"created", "retry_eligible"}:
                raise ValueError(f"delivery intent is not retryable: {intent['status']}")
            lease = conn.execute("SELECT * FROM delivery_leases WHERE intent_id=?", (intent_id,)).fetchone()
            if lease and _now(lease["expires_at"]) > started:
                raise ValueError(f"delivery intent is already leased by {lease['owner']}")
            if lease:
                conn.execute("DELETE FROM delivery_leases WHERE intent_id=?", (intent_id,))
            row = conn.execute("SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_no FROM delivery_attempts WHERE intent_id=?", (intent_id,)).fetchone()
            attempt_no = int(row["next_no"])
            conn.execute("INSERT INTO delivery_attempts(attempt_id,intent_id,attempt_no,state,started_at) VALUES(?,?,?,?,?)", (attempt_id, intent_id, attempt_no, "started", _iso(started)))
            conn.execute("INSERT INTO delivery_leases(intent_id,attempt_id,owner,expires_at) VALUES(?,?,?,?)", (intent_id, attempt_id, str(owner), expires))
            conn.execute("UPDATE delivery_intents SET status='in_flight', retry_allowed=0, updated_at=? WHERE intent_id=?", (_iso(started), intent_id))
        return {"attempt_id": attempt_id, "intent_id": intent_id, "attempt_no": attempt_no, "owner": str(owner), "expires_at": expires}

    start_attempt = begin_attempt

    def finish_attempt(self, intent_id: str, attempt_id: str, state: str, external_id: str = "", error: str = "", metadata: dict[str, Any] | None = None, now: datetime | str | None = None) -> dict[str, Any]:
        normalized = str(state or "unknown").strip().casefold()
        if normalized in REVIEW_RESULTS or normalized == "unknown_requires_review":
            intent_state, retry_allowed, reason = "unknown_requires_review", 0, normalized
        elif normalized in {"timeout", "crash", "unknown"}:
            intent_state, retry_allowed, reason = "unknown", 0, normalized
        else:
            intent_state, retry_allowed, reason = normalized, 0, ""
        finished = _iso(now)
        with self._connect() as conn:
            updated = conn.execute("UPDATE delivery_attempts SET state=?,external_id=?,error=?,metadata_json=?,finished_at=? WHERE attempt_id=? AND intent_id=?", (normalized, str(external_id or ""), str(error or ""), _json(metadata or {}), finished, attempt_id, intent_id))
            if updated.rowcount != 1:
                raise KeyError(f"delivery attempt not found: {attempt_id}")
            conn.execute("DELETE FROM delivery_leases WHERE intent_id=? AND attempt_id=?", (intent_id, attempt_id))
            conn.execute("UPDATE delivery_intents SET status=?,retry_allowed=?,review_reason=?,unknown_at=?,updated_at=? WHERE intent_id=?", (intent_state, retry_allowed, reason, finished if intent_state == "unknown" else "", finished, intent_id))
        return self.get_delivery_intent(intent_id)

    record_attempt = finish_attempt

    def record_delivery_callback(self, intent_id: str, event: dict[str, Any]) -> dict[str, Any]:
        state = str(event.get("status") or event.get("state") or "").casefold()
        if state in REVIEW_RESULTS or state == "unknown_requires_review":
            with self._connect() as conn:
                conn.execute("UPDATE delivery_intents SET status='unknown_requires_review',retry_allowed=0,review_reason=?,updated_at=? WHERE intent_id=?", (state, _iso(), intent_id))
        return self.get_delivery_intent(intent_id)

    def poll_delivery(self, intent_id: str, poller: Callable[[dict[str, Any]], dict[str, Any]], now: datetime | str | None = None) -> dict[str, Any]:
        intent = self.get_delivery_intent(intent_id)
        try:
            result = poller(intent) or {}
        except Exception as exc:
            return self._set_review(intent_id, "query_failed", str(exc))
        state = str(result.get("status") or result.get("state") or "inconclusive").casefold()
        if state in REVIEW_RESULTS or state in {"unknown", "error"}:
            return self._set_review(intent_id, state, str(result.get("reason") or "polling inconclusive"))
        if state in {"present", "found", "published", "scheduled", "drafted"}:
            if state == "published" and result.get("verification"):
                return self.record_delivery_result(intent_id, result)
            with self._connect() as conn:
                conn.execute("UPDATE delivery_intents SET status=?,retry_allowed=0,updated_at=? WHERE intent_id=?", (state, _iso(now), intent_id))
            return self.get_delivery_intent(intent_id)
        if state != "absent":
            return self._set_review(intent_id, "inconclusive", "poller returned an unrecognized state")
        checked_at = _now(now)
        unknown_at = _now(intent.get("unknown_at") or checked_at)
        eligible_at = unknown_at + timedelta(seconds=int(intent["absence_window_seconds"]))
        eligible = checked_at >= eligible_at
        with self._connect() as conn:
            conn.execute("UPDATE delivery_intents SET status=?,retry_allowed=?,updated_at=? WHERE intent_id=?", ("retry_eligible" if eligible else "unknown", int(eligible), _iso(checked_at), intent_id))
            if eligible:
                conn.execute("INSERT INTO delivery_retries(intent_id,reason,eligible_at,created_at) VALUES(?,?,?,?)", (intent_id, "full_absence_window", _iso(eligible_at), _iso(checked_at)))
        return self.get_delivery_intent(intent_id)

    poll_intent = poll_delivery

    def poll_unknown_deliveries(self, poller: Callable[[dict[str, Any]], dict[str, Any]], now: datetime | str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            intents = [dict(row) for row in conn.execute("SELECT * FROM delivery_intents WHERE status='unknown' ORDER BY updated_at").fetchall()]
        report = {"status": "ok", "polled": 0, "retry_eligible": 0, "requires_review": 0}
        for intent in intents:
            result = self.poll_delivery(intent["intent_id"], poller, now=now)
            report["polled"] += 1
            if result["status"] == "retry_eligible":
                report["retry_eligible"] += 1
            elif result["status"] == "unknown_requires_review":
                report["requires_review"] += 1
        return report

    def _set_review(self, intent_id: str, reason: str, error: str) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("UPDATE delivery_intents SET status='unknown_requires_review',retry_allowed=0,review_reason=?,updated_at=? WHERE intent_id=?", (f"{reason}:{error}"[:500], _iso(), intent_id))
        return self.get_delivery_intent(intent_id)

    def can_retry(self, intent_id: str) -> bool:
        return bool(self.get_delivery_intent(intent_id)["retry_allowed"])

    def record_delivery_result(self, intent_id: str, result: dict[str, Any]) -> dict[str, Any]:
        status = str(result.get("status") or "unknown").casefold()
        if status in NON_PUBLICATION_STATUSES:
            with self._connect() as conn:
                conn.execute("UPDATE delivery_intents SET status=?,retry_allowed=0,updated_at=? WHERE intent_id=?", (status, _iso(), intent_id))
            return self.get_delivery_intent(intent_id)
        if status == "published" and result.get("verification"):
            identity = self.register_verified_publication({"intent_id": intent_id, **result["verification"]})
            if not identity.get("passed"):
                return self._set_review(intent_id, "publication_verification_failed", str(identity.get("reason") or "invalid publication identity"))
            return {"status": "published", "identity": identity, "intent_id": intent_id}
        if status in REVIEW_RESULTS:
            return self._set_review(intent_id, status, str(result.get("error") or ""))
        with self._connect() as conn:
            conn.execute("UPDATE delivery_intents SET status=?,retry_allowed=0,updated_at=? WHERE intent_id=?", (status, _iso(), intent_id))
        return self.get_delivery_intent(intent_id)

    def _identity_fields(self, payload: dict[str, Any]) -> dict[str, str]:
        verification = payload.get("verification") or {}
        return {
            "platform": str(payload.get("platform") or verification.get("platform") or "").strip(),
            "alias": str(payload.get("internal_account_alias") or payload.get("account_alias") or verification.get("account_alias") or "").strip(),
            "content_id": str(payload.get("platform_content_id") or payload.get("content_id") or verification.get("content_id") or "").strip(),
            "url": str(payload.get("canonical_url") or payload.get("url") or verification.get("url") or "").strip(),
            "published_at": str(payload.get("published_at") or verification.get("published_at") or "").strip(),
            "source": str(payload.get("identity_source") or payload.get("source") or verification.get("source") or "").strip(),
        }

    def register_verified_publication(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = self._identity_fields(payload)
        verification = payload.get("verification") or {}
        if not all(fields.values()) or not fields["url"].startswith(("http://", "https://")):
            return {"passed": False, "reason": "publication_identity_fields_missing"}
        if verification and any(str(verification.get(key) or "") != fields[value] for key, value in (("account_alias", "alias"), ("content_id", "content_id"), ("url", "url"), ("published_at", "published_at"))):
            return {"passed": False, "reason": "publication_verification_mismatch"}
        try:
            _now(fields["published_at"])
        except ValueError:
            return {"passed": False, "reason": "publication_time_invalid"}
        level = str(payload.get("verification_level") or verification_level_for_source(fields["source"]))
        if level not in VERIFIED_LEVELS:
            return {"passed": False, "reason": "publication_not_independently_verified"}
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO publication_identities(platform,account_id,internal_account_alias,platform_content_id,canonical_url,published_at,verification_level,identity_source,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)", (fields["platform"], fields["alias"], fields["alias"], fields["content_id"], fields["url"], _iso(fields["published_at"]), level, fields["source"], _json(payload)))
            row = conn.execute("SELECT * FROM publication_identities WHERE platform=? AND account_id=? AND platform_content_id=?", (fields["platform"], fields["alias"], fields["content_id"])).fetchone()
            for hours in (1, 24, 72):
                conn.execute("INSERT OR IGNORE INTO metric_windows(identity_id,hours,due_at,state) VALUES(?,?,?,'pending')", (row["id"], hours, _iso(_now(fields["published_at"]) + timedelta(hours=hours))))
            if payload.get("intent_id"):
                conn.execute("UPDATE delivery_intents SET status='published',retry_allowed=0,updated_at=? WHERE intent_id=?", (_iso(), str(payload["intent_id"])))
            return {"passed": True, "identity_id": row["id"], "platform": fields["platform"], "internal_account_alias": fields["alias"], "platform_content_id": fields["content_id"], "canonical_url": row["canonical_url"], "published_at": row["published_at"]}

    def register_identity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compatibility API for already postchecked records."""
        payload = dict(payload)
        alias = payload.get("internal_account_alias") or payload.get("account_id")
        payload.setdefault("internal_account_alias", alias)
        payload.setdefault("account_alias", alias)
        payload.setdefault("verification", {"account_alias": alias, "content_id": payload.get("platform_content_id"), "url": payload.get("canonical_url"), "published_at": payload.get("published_at"), "source": payload.get("identity_source")})
        payload.setdefault("verification_level", payload.get("verification_level") or "postcheck_verified")
        return self.register_verified_publication(payload)

    def identities(self, platform: str = "") -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM publication_identities", []
        if platform:
            sql += " WHERE platform=?"
            args.append(platform)
        sql += " ORDER BY id"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]

    def due_windows(self, identity_id: int | None = None, include_all: bool = False) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM metric_windows", []
        clauses = []
        if not include_all:
            clauses.append("state='pending'")
        if identity_id is not None:
            clauses.append("identity_id=?")
            args.append(int(identity_id))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY due_at"
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]

    def record_metrics(self, window_id: int, metrics: dict[str, Any] | None, source: str = "collector", confidence: str = "unknown", platform: str = "", internal_account_alias: str = "", platform_content_id: str = "", observed_at: datetime | str | None = None) -> dict[str, Any]:
        metrics = metrics if isinstance(metrics, dict) else {}
        state = "collected" if any(key in metrics and metrics[key] is not None for key in REQUIRED_METRICS) else "insufficient"
        with self._connect() as conn:
            window = conn.execute("SELECT * FROM metric_windows WHERE id=?", (int(window_id),)).fetchone()
            if not window:
                raise KeyError(f"metric window not found: {window_id}")
            identity = conn.execute("SELECT * FROM publication_identities WHERE id=?", (window["identity_id"],)).fetchone()
            platform = platform or identity["platform"]
            internal_account_alias = internal_account_alias or identity["internal_account_alias"] or identity["account_id"]
            platform_content_id = platform_content_id or identity["platform_content_id"]
            conn.execute("UPDATE metric_windows SET state=? WHERE id=?", (state, int(window_id)))
            conn.execute("INSERT INTO metric_observations(window_id,platform,internal_account_alias,platform_content_id,state,metrics_json,source,confidence,observed_at) VALUES(?,?,?,?,?,?,?,?,?)", (int(window_id), platform, internal_account_alias, platform_content_id, state, _json(metrics), str(source), str(confidence), _iso(observed_at)))
        return {"state": state, "window_id": int(window_id)}

    def observations(self, identity_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT o.*, w.identity_id FROM metric_observations o JOIN metric_windows w ON w.id=o.window_id"
        args: list[Any] = []
        if identity_id is not None:
            sql += " WHERE w.identity_id=?"
            args.append(int(identity_id))
        sql += " ORDER BY o.id"
        with self._connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, tuple(args)).fetchall()]
        for row in rows:
            row["metrics"] = json.loads(row.pop("metrics_json") or "{}")
        return rows

    def analysis_ready_publications(self) -> list[dict[str, Any]]:
        """Return only publications with complete, collected 1h/24h/72h evidence."""
        ready: list[dict[str, Any]] = []
        with self._connect() as conn:
            identities = [dict(row) for row in conn.execute("SELECT * FROM publication_identities ORDER BY id")]
            for identity in identities:
                windows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM metric_windows WHERE identity_id=? ORDER BY hours",
                        (identity["id"],),
                    )
                ]
                if {int(row["hours"]) for row in windows} != {1, 24, 72}:
                    continue
                if any(row["state"] != "collected" for row in windows):
                    continue
                metrics_by_window: dict[str, Any] = {}
                complete = True
                for window in windows:
                    observation = conn.execute(
                        "SELECT * FROM metric_observations WHERE window_id=? AND state='collected' ORDER BY id DESC LIMIT 1",
                        (window["id"],),
                    ).fetchone()
                    if observation is None:
                        complete = False
                        break
                    metrics_by_window[str(window["hours"])] = json.loads(observation["metrics_json"] or "{}")
                if not complete:
                    continue
                metadata = json.loads(identity.get("metadata_json") or "{}")
                ready.append(
                    {
                        "identity_id": identity["id"],
                        "platform": identity["platform"],
                        "internal_account_alias": identity["internal_account_alias"] or identity["account_id"],
                        "platform_content_id": identity["platform_content_id"],
                        "published_at": identity["published_at"],
                        "attribution": metadata.get("attribution") or {},
                        "metrics_by_window": metrics_by_window,
                    }
                )
        return ready

    def invalidate_window(self, window_id: int, reason: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE metric_windows SET state='invalidated',invalidated_reason=? WHERE id=?", (str(reason), int(window_id)))

    def begin_metric_collection(self, window_id: int, owner: str = "metric-collector", lease_seconds: int = 300, now: datetime | str | None = None) -> dict[str, Any]:
        started = _now(now)
        expires = _iso(started + timedelta(seconds=int(lease_seconds)))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            window = conn.execute("SELECT * FROM metric_windows WHERE id=?", (int(window_id),)).fetchone()
            if not window:
                raise KeyError(f"metric window not found: {window_id}")
            if window["state"] != "pending":
                raise ValueError(f"metric window is not pending: {window['state']}")
            lease = conn.execute("SELECT * FROM metric_collection_leases WHERE window_id=?", (int(window_id),)).fetchone()
            if lease and _now(lease["expires_at"]) > started:
                raise ValueError(f"metric window is already leased by {lease['owner']}")
            if lease:
                conn.execute("DELETE FROM metric_collection_leases WHERE window_id=?", (int(window_id),))
            conn.execute("INSERT INTO metric_collection_attempts(window_id,state,error,attempted_at) VALUES(?,?,?,?)", (int(window_id), "started", "", _iso(started)))
            attempt_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute("INSERT INTO metric_collection_leases(window_id,attempt_id,owner,expires_at) VALUES(?,?,?,?)", (int(window_id), attempt_id, str(owner), expires))
        return {"attempt_id": attempt_id, "window_id": int(window_id), "owner": str(owner), "expires_at": expires}

    def finish_metric_collection(self, window_id: int, attempt_id: int, state: str, error: str = "", now: datetime | str | None = None, retry_after_seconds: int = 0) -> None:
        finished = _iso(now)
        with self._connect() as conn:
            updated = conn.execute("UPDATE metric_collection_attempts SET state=?,error=?,finished_at=? WHERE id=? AND window_id=?", (str(state), str(error or ""), finished, int(attempt_id), int(window_id)))
            if updated.rowcount != 1:
                raise KeyError(f"metric collection attempt not found: {attempt_id}")
            conn.execute("DELETE FROM metric_collection_leases WHERE window_id=? AND attempt_id=?", (int(window_id), int(attempt_id)))
            if str(error or ""):
                eligible_at = _iso(_now(now) + timedelta(seconds=max(0, int(retry_after_seconds))))
                conn.execute("INSERT INTO metric_collection_retries(window_id,reason,eligible_at,created_at) VALUES(?,?,?,?)", (int(window_id), str(error)[:300], eligible_at, finished))

    def metric_attempt_count(self, window_id: int) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT count(*) FROM metric_collection_attempts WHERE window_id=?", (int(window_id),)).fetchone()[0])

    def metric_retry_due(self, window_id: int, now: datetime | str | None = None) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT eligible_at FROM metric_collection_retries WHERE window_id=? ORDER BY id DESC LIMIT 1",
                (int(window_id),),
            ).fetchone()
        return row is None or _now(row["eligible_at"]) <= _now(now)

    @staticmethod
    def validate_kuaishou_scheduled_postcheck(intent: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
        evidence = evidence or {}
        account = str(evidence.get("account_alias") or evidence.get("account") or "")
        title = str(evidence.get("title") or "")
        description = str(evidence.get("description") or evidence.get("full_description") or "")
        description_digest = str(evidence.get("description_digest") or "")
        schedule = str(evidence.get("scheduled_at") or evidence.get("schedule_time") or "")
        evidence_path = str(evidence.get("screenshot_path") or evidence.get("evidence_path") or "")
        dom = evidence.get("dom") or evidence.get("dom_html") or evidence.get("dom_snapshot")
        checks = {
            "account": account == str(intent.get("internal_account_alias") or ""),
            "title": title == str(intent.get("expected_title") or ""),
            "description": description == str(intent.get("expected_description") or "") or description_digest == str(intent.get("expected_description_digest") or ""),
            "scheduled_at": schedule == str(intent.get("scheduled_at") or ""),
            "evidence": bool(evidence_path or dom),
        }
        return {"passed": all(checks.values()), "checks": checks, "evidence": evidence}
