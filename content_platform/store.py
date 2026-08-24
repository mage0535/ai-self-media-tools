import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _performance_has_growth_signal(row):
    platform = str(row.get("platform", "") or "")
    views = float(row.get("views", 0) or 0)
    likes = float(row.get("likes", 0) or 0)
    comments = float(row.get("comments", 0) or 0)
    shares = float(row.get("shares", 0) or 0)
    saves = float(row.get("saves", 0) or 0)
    follows = float(row.get("follows", 0) or 0)
    extra = row.get("extra_metrics") or {}
    if row.get("job_source") == "performance_cycle" and extra.get("strategy_eligible") is not True:
        return False
    if extra.get("strategy_eligible") is False:
        return False
    if platform == "tiktok" and views and follows == views and float(extra.get("works", 0) or 0) == views and likes + comments + shares + saves <= 50:
        return False
    if platform == "tiktok" and views == 0 and likes + comments + shares + saves == 0:
        return False
    return any(
        float(row.get(key, 0) or 0) > 0
        for key in (
            "views",
            "likes",
            "comments",
            "shares",
            "saves",
            "follows",
            "completion_rate",
            "three_second_view_rate",
            "avg_watch_seconds",
        )
    )


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.init()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).casefold():
                conn.close()
                raise
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    platforms_json TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT '',
                    risk_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    event TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, kind, path)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    actor TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    error TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, platform)
                );
                CREATE TABLE IF NOT EXISTS topic_history (
                    fingerprint TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    PRIMARY KEY(fingerprint, platform)
                );
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL,
                    views INTEGER NOT NULL DEFAULT 0,
                    likes INTEGER NOT NULL DEFAULT 0,
                    comments INTEGER NOT NULL DEFAULT 0,
                    shares INTEGER NOT NULL DEFAULT 0,
                    saves INTEGER NOT NULL DEFAULT 0,
                    follows INTEGER NOT NULL DEFAULT 0,
                    completion_rate REAL NOT NULL DEFAULT 0,
                    three_second_view_rate REAL NOT NULL DEFAULT 0,
                    avg_watch_seconds REAL NOT NULL DEFAULT 0,
                    extra_metrics_json TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL,
                    UNIQUE(job_id, platform)
                );
                CREATE TABLE IF NOT EXISTS source_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    source_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    account_handle TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    account_handle TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idea_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    topic TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    content_form TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_name TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS delivery_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL,
                    action TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    lease_owner TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, platform, action)
                );
                CREATE TABLE IF NOT EXISTS topic_clusters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    cluster_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS draft_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    risk_level TEXT NOT NULL DEFAULT '',
                    draft_meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS geo_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    score INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    platforms TEXT NOT NULL DEFAULT '[]',
                    brief TEXT NOT NULL DEFAULT '{}',
                    profile TEXT NOT NULL DEFAULT 'default',
                    cron TEXT NOT NULL DEFAULT '@daily',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    label TEXT NOT NULL DEFAULT '',
                    next_run TEXT NOT NULL DEFAULT '',
                    last_run TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_packages (
                    content_package_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    account_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'created',
                    content_type TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publish_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_package_id TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    verification_level TEXT NOT NULL DEFAULT '',
                    platform_content_id TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_package_id TEXT NOT NULL DEFAULT '',
                    job_id TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    review_point_hours INTEGER NOT NULL DEFAULT 0,
                    purpose TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'pending',
                    due_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL DEFAULT '',
                    workflow_id TEXT NOT NULL DEFAULT '',
                    heartbeat_at TEXT NOT NULL DEFAULT '',
                    lease_expires_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL DEFAULT '',
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    required INTEGER NOT NULL DEFAULT 1,
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    attempt INTEGER NOT NULL DEFAULT 0,
                    reason_code TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    input_json TEXT NOT NULL DEFAULT '{}',
                    output_json TEXT NOT NULL DEFAULT '{}',
                    gate_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, platform, step_name)
                );
                CREATE TABLE IF NOT EXISTS workflow_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    report_path TEXT NOT NULL DEFAULT '',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, platform)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
                CREATE INDEX IF NOT EXISTS idx_delivery_queue_state ON delivery_queue(state, id);
                CREATE INDEX IF NOT EXISTS idx_topic_clusters_key ON topic_clusters(cluster_key, id);
                CREATE INDEX IF NOT EXISTS idx_draft_versions_job ON draft_versions(job_id, id);
                CREATE INDEX IF NOT EXISTS idx_content_packages_job ON content_packages(job_id, platform);
                CREATE INDEX IF NOT EXISTS idx_publish_receipts_job ON publish_receipts(job_id, platform);
                CREATE INDEX IF NOT EXISTS idx_review_tasks_state ON review_tasks(state, due_at);
                CREATE INDEX IF NOT EXISTS idx_workflow_steps_job ON workflow_steps(job_id, platform, id);
                CREATE INDEX IF NOT EXISTS idx_workflow_reports_job ON workflow_reports(job_id, platform);
                """
            )
            self._migrate_topic_history_platform_scope(conn)
            for name, definition in {
                "profile": "TEXT NOT NULL DEFAULT 'default'",
                "prompt_version": "TEXT NOT NULL DEFAULT ''",
                "draft_meta_json": "TEXT NOT NULL DEFAULT '{}'",
                "lease_owner": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT NOT NULL DEFAULT ''",
                "topic_fingerprint": "TEXT NOT NULL DEFAULT ''",
                "acceptance_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "jobs", name, definition)
            for name, definition in {
                "idempotency_key": "TEXT NOT NULL DEFAULT ''",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                self._ensure_column(conn, "deliveries", name, definition)
            for name, definition in {
                "topic": "TEXT NOT NULL DEFAULT ''",
                "title": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "content_packages", name, definition)
            for name, definition in {
                "url": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "publish_receipts", name, definition)
            for name, definition in {
                "saves": "INTEGER NOT NULL DEFAULT 0",
                "follows": "INTEGER NOT NULL DEFAULT 0",
                "completion_rate": "REAL NOT NULL DEFAULT 0",
                "three_second_view_rate": "REAL NOT NULL DEFAULT 0",
                "avg_watch_seconds": "REAL NOT NULL DEFAULT 0",
                "extra_metrics_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                self._ensure_column(conn, "performance", name, definition)


    def _migrate_topic_history_platform_scope(self, conn):
        rows = conn.execute("PRAGMA table_info(topic_history)").fetchall()
        columns = [row[1] for row in rows]
        pk_columns = [row[1] for row in sorted((row for row in rows if row[5]), key=lambda row: row[5])]
        if "platform" in columns and pk_columns == ["fingerprint", "platform"]:
            return
        conn.execute(
            """CREATE TABLE IF NOT EXISTS topic_history_v2 (
                fingerprint TEXT NOT NULL,
                platform TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                job_id TEXT NOT NULL,
                used_at TEXT NOT NULL,
                PRIMARY KEY(fingerprint, platform)
            )"""
        )
        platform_expr = "platform" if "platform" in columns else "''"
        conn.execute(
            f"""INSERT OR REPLACE INTO topic_history_v2(fingerprint, platform, title, source, job_id, used_at)
            SELECT fingerprint, COALESCE({platform_expr}, ''), title, source, job_id, used_at FROM topic_history"""
        )
        conn.execute("DROP TABLE topic_history")
        conn.execute("ALTER TABLE topic_history_v2 RENAME TO topic_history")

    def init_db(self):
        self.init()

    def create_job(self, topic, platforms, brief=None, profile="default", topic_fingerprint=""):
        topic = str(topic).strip()
        platforms = list(dict.fromkeys(str(p).strip() for p in platforms if str(p).strip()))
        if not topic or not platforms:
            raise ValueError("topic and at least one platform are required")
        job_id = uuid.uuid4().hex[:16]
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO jobs(id,topic,brief_json,platforms_json,state,created_at,updated_at,profile,topic_fingerprint)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (job_id, topic, json.dumps(brief or {}, ensure_ascii=False), json.dumps(platforms, ensure_ascii=False), "created", now, now, profile, topic_fingerprint),
            )
            self._event(conn, job_id, "job_created", {"platforms": platforms})
        return self.get_job(job_id)

    def get_job(self, job_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(f"job not found: {job_id}")
        return self._job(row)

    def list_jobs(self, limit=50, state=None):
        sql, args = "SELECT * FROM jobs", []
        if state:
            sql += " WHERE state=?"
            args.append(state)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self.connect() as conn:
            return [self._job(row) for row in conn.execute(sql, args)]

    def content_candidates(self, limit=200, states=None, exclude_job_id=""):
        states = tuple(states or ("review_required", "approved", "published", "partial", "created"))
        sql = "SELECT * FROM jobs"
        args = []
        if states:
            placeholders = ",".join("?" for _ in states)
            sql += f" WHERE state IN ({placeholders})"
            args.extend(states)
        if exclude_job_id:
            sql += " AND id<>?" if states else " WHERE id<>?"
            args.append(exclude_job_id)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        args.append(int(limit))
        with self.connect() as conn:
            return [self._job(row) for row in conn.execute(sql, args)]

    def save_draft(self, job_id, title, body, risk_level, risk, prompt_version="", draft_meta=None):
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET title=?,body=?,risk_level=?,risk_json=?,prompt_version=?,draft_meta_json=?,updated_at=? WHERE id=?",
                (title, body, risk_level, json.dumps(risk, ensure_ascii=False), prompt_version, json.dumps(draft_meta or {}, ensure_ascii=False), utc_now(), job_id),
            )
            conn.execute(
                "INSERT INTO draft_versions(job_id,title,body,risk_level,draft_meta_json,created_at) VALUES(?,?,?,?,?,?)",
                (job_id, title, body, risk_level, json.dumps(draft_meta or {}, ensure_ascii=False), utc_now()),
            )
            self._event(conn, job_id, "draft_saved", {"risk_level": risk_level})

    def save_workflow_acceptance(self, job_id, acceptance):
        """Persist the exact quality decision consumed by delivery gates."""
        payload = dict(acceptance or {})
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET acceptance_json=?,updated_at=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), utc_now(), job_id),
            )
            self._event(conn, job_id, "workflow_acceptance_saved", {"passed": bool(payload.get("passed")), "failures": payload.get("failures", [])})
        return self.get_job(job_id)

    def transition(self, job_id, expected, new_state, event, detail=None):
        expected = tuple(set(expected))
        if not expected:
            raise ValueError("expected states cannot be empty")
        with self.connect() as conn:
            placeholders = ",".join("?" for _ in expected)
            cursor = conn.execute(
                f"UPDATE jobs SET state=?,updated_at=? WHERE id=? AND state IN ({placeholders})",
                (new_state, utc_now(), job_id, *expected),
            )
            if cursor.rowcount != 1:
                row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not row:
                    raise KeyError(f"job not found: {job_id}")
                raise ValueError(f"invalid transition: {row['state']} -> {new_state}")
            self._event(conn, job_id, event, detail or {})
        return self.get_job(job_id)

    def claim(self, job_id, allowed_states, owner, ttl_seconds, new_state):
        allowed = tuple(set(allowed_states))
        if not allowed or not owner:
            raise ValueError("claim requires states and owner")
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in allowed)
            cursor = conn.execute(
                f"""UPDATE jobs SET state=?,lease_owner=?,lease_expires_at=?,attempts=attempts+1,updated_at=?
                WHERE id=? AND state IN ({placeholders}) AND (lease_owner='' OR lease_expires_at<=? OR lease_owner=?)""",
                (new_state, owner, expires, now, job_id, *allowed, now, owner),
            )
            if cursor.rowcount == 1:
                self._event(conn, job_id, "job_claimed", {"owner": owner, "state": new_state, "expires_at": expires})
                return True
            return False

    def release_claim(self, job_id, owner, new_state, event, error="", detail=None):
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE jobs SET state=?,lease_owner='',lease_expires_at='',last_error=?,updated_at=?
                WHERE id=? AND lease_owner=?""",
                (new_state, str(error), utc_now(), job_id, owner),
            )
            if cursor.rowcount != 1:
                raise ValueError("job claim is not owned by caller")
            self._event(conn, job_id, event, detail or {"error": str(error)})
        return self.get_job(job_id)

    def recover_stale(self):
        now, recovered = utc_now(), 0
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id,state FROM jobs WHERE state IN ('generating','publishing') AND lease_expires_at<>'' AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            for row in rows:
                new_state = "failed" if row["state"] == "generating" else "partial"
                conn.execute(
                    "UPDATE jobs SET state=?,lease_owner='',lease_expires_at='',last_error='stale lease recovered',updated_at=? WHERE id=?",
                    (new_state, now, row["id"]),
                )
                self._event(conn, row["id"], "stale_job_recovered", {"from": row["state"], "to": new_state})
                recovered += 1

            deliveries = conn.execute(
                """SELECT id,job_id,state,attempts,error FROM delivery_queue
                WHERE state='processing' AND lease_expires_at<>'' AND lease_expires_at<=?""",
                (now,),
            ).fetchall()
            for row in deliveries:
                attempts = int(row["attempts"] or 0)
                terminal = attempts >= 3
                new_state = "failed" if terminal else "queued"
                error = row["error"] or "stale delivery lease recovered"
                if terminal and "stale delivery failed after max attempts" not in error:
                    error = f"stale delivery failed after max attempts: {error}"
                conn.execute(
                    """UPDATE delivery_queue
                    SET state=?, lease_owner='', lease_expires_at='', error=?, updated_at=?
                    WHERE id=?""",
                    (new_state, error, now, row["id"]),
                )
                self._event(
                    conn,
                    row["job_id"],
                    "stale_delivery_recovered",
                    {"queue_id": row["id"], "from": row["state"], "to": new_state, "attempts": attempts},
                )
                recovered += 1
        return recovered

    def record_event(self, job_id, event, detail=None):
        with self.connect() as conn:
            self._event(conn, job_id, event, detail or {})

    def acquire_workflow_lock(self, owner, workflow_id, ttl_seconds=1800, lock_name="global"):
        owner = str(owner or "").strip()
        workflow_id = str(workflow_id or "").strip()
        if not owner or not workflow_id:
            raise ValueError("workflow lock requires owner and workflow_id")
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM workflow_locks WHERE lock_name=?", (lock_name,)).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO workflow_locks(lock_name,owner,workflow_id,heartbeat_at,lease_expires_at,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (lock_name, owner, workflow_id, now, expires, now, now),
                )
                return True
            if row["owner"] in ("", owner) or row["lease_expires_at"] <= now:
                conn.execute(
                    """UPDATE workflow_locks SET owner=?,workflow_id=?,heartbeat_at=?,lease_expires_at=?,updated_at=?
                    WHERE lock_name=?""",
                    (owner, workflow_id, now, expires, now, lock_name),
                )
                return True
            return False

    def heartbeat_workflow_lock(self, owner, ttl_seconds=1800, lock_name="global"):
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds")
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE workflow_locks SET heartbeat_at=?,lease_expires_at=?,updated_at=? WHERE lock_name=? AND owner=?",
                (now, expires, now, lock_name, owner),
            )
            return cursor.rowcount == 1

    def release_workflow_lock(self, owner, lock_name="global"):
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE workflow_locks SET owner='',workflow_id='',heartbeat_at='',lease_expires_at='',updated_at=? WHERE lock_name=? AND owner=?",
                (utc_now(), lock_name, owner),
            )
            return cursor.rowcount == 1

    def workflow_lock(self, lock_name="global"):
        rows = self._rows("SELECT * FROM workflow_locks WHERE lock_name=?", (lock_name,))
        return rows[0] if rows else {}

    def save_workflow_step(
        self,
        workflow_id,
        job_id,
        platform,
        step_name,
        status,
        required=True,
        depends_on=None,
        attempt=0,
        reason_code="",
        message="",
        input_payload=None,
        output_payload=None,
        gate_result=None,
        started_at="",
        finished_at="",
        duration_ms=0,
    ):
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO workflow_steps(
                    workflow_id,job_id,platform,step_name,status,required,depends_on_json,attempt,reason_code,message,
                    input_json,output_json,gate_json,started_at,finished_at,duration_ms,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform,step_name) DO UPDATE SET
                    workflow_id=excluded.workflow_id,
                    status=excluded.status,
                    required=excluded.required,
                    depends_on_json=excluded.depends_on_json,
                    attempt=excluded.attempt,
                    reason_code=excluded.reason_code,
                    message=excluded.message,
                    input_json=excluded.input_json,
                    output_json=excluded.output_json,
                    gate_json=excluded.gate_json,
                    started_at=CASE WHEN excluded.started_at<>'' THEN excluded.started_at ELSE workflow_steps.started_at END,
                    finished_at=excluded.finished_at,
                    duration_ms=excluded.duration_ms,
                    updated_at=excluded.updated_at""",
                (
                    workflow_id,
                    job_id,
                    platform or "",
                    step_name,
                    status,
                    1 if required else 0,
                    json.dumps(depends_on or [], ensure_ascii=False),
                    int(attempt or 0),
                    str(reason_code or ""),
                    str(message or ""),
                    json.dumps(input_payload or {}, ensure_ascii=False),
                    json.dumps(output_payload or {}, ensure_ascii=False),
                    json.dumps(gate_result or {}, ensure_ascii=False),
                    started_at or "",
                    finished_at or "",
                    int(duration_ms or 0),
                    now,
                    now,
                ),
            )
            self._event(conn, job_id, f"workflow_step_{status.lower()}", {
                "workflow_id": workflow_id,
                "platform": platform or "",
                "step": step_name,
                "required": bool(required),
                "reason_code": reason_code or "",
                "message": message or "",
            })

    def workflow_steps(self, job_id, platform=None):
        sql = "SELECT * FROM workflow_steps WHERE job_id=?"
        args = [job_id]
        if platform is not None:
            sql += " AND platform=?"
            args.append(platform or "")
        sql += " ORDER BY id"
        rows = self._rows(sql, tuple(args))
        for row in rows:
            row["depends_on"] = json.loads(row.pop("depends_on_json", "[]"))
            row["input"] = json.loads(row.pop("input_json", "{}"))
            row["output"] = json.loads(row.pop("output_json", "{}"))
            row["gate"] = json.loads(row.pop("gate_json", "{}"))
            row["required"] = bool(row["required"])
        return rows

    def save_workflow_report(self, workflow_id, job_id, platform, status, report_path, summary):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO workflow_reports(workflow_id,job_id,platform,status,report_path,summary_json,created_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform) DO UPDATE SET
                    workflow_id=excluded.workflow_id,
                    status=excluded.status,
                    report_path=excluded.report_path,
                    summary_json=excluded.summary_json,
                    created_at=excluded.created_at""",
                (workflow_id, job_id, platform or "", status, str(report_path or ""), json.dumps(summary or {}, ensure_ascii=False), utc_now()),
            )

    def workflow_reports(self, job_id=None, platform=None):
        sql = "SELECT * FROM workflow_reports"
        clauses, args = [], []
        if job_id:
            clauses.append("job_id=?")
            args.append(job_id)
        if platform is not None:
            clauses.append("platform=?")
            args.append(platform or "")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        rows = self._rows(sql, tuple(args))
        for row in rows:
            row["summary"] = json.loads(row.pop("summary_json", "{}"))
        return rows

    def record_approval(self, job_id, actor, decision, note):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO approvals(job_id,actor,decision,note,created_at) VALUES(?,?,?,?,?)",
                (job_id, actor, decision, note, utc_now()),
            )
            self._event(conn, job_id, "approval_recorded", {"actor": actor, "decision": decision})

    def add_artifact(self, job_id, kind, path, checksum=""):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO artifacts(job_id,kind,path,checksum,created_at) VALUES(?,?,?,?,?)",
                (job_id, kind, str(path), checksum, utc_now()),
            )

    def save_delivery(self, job_id, platform, status, external_id="", error="", idempotency_key=""):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO deliveries(job_id,platform,status,external_id,error,updated_at,idempotency_key,attempts)
                VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(job_id,platform) DO UPDATE SET
                status=CASE WHEN deliveries.status IN ('drafted','published') THEN deliveries.status ELSE excluded.status END,
                external_id=CASE WHEN deliveries.status IN ('drafted','published') THEN deliveries.external_id ELSE excluded.external_id END,
                error=CASE WHEN deliveries.status IN ('drafted','published') THEN deliveries.error ELSE excluded.error END,
                updated_at=excluded.updated_at,idempotency_key=excluded.idempotency_key,attempts=deliveries.attempts+1""",
                (job_id, platform, status, external_id, error, utc_now(), idempotency_key),
            )
            self._event(conn, job_id, "delivery_updated", {"platform": platform, "status": status, "error": error})

    def events(self, job_id):
        return self._rows("SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,))

    def artifacts(self, job_id):
        return self._rows("SELECT * FROM artifacts WHERE job_id=? ORDER BY id", (job_id,))

    def deliveries(self, job_id):
        return self._rows("SELECT * FROM deliveries WHERE job_id=? ORDER BY id", (job_id,))

    def deliveries_all(self):
        return self._rows("SELECT * FROM deliveries ORDER BY updated_at DESC, id DESC", ())

    def draft_versions(self, job_id):
        rows = self._rows("SELECT * FROM draft_versions WHERE job_id=? ORDER BY id", (job_id,))
        for row in rows:
            row["draft_meta"] = json.loads(row.pop("draft_meta_json", "{}"))
        return rows

    def record_performance(
        self,
        job_id,
        platform,
        views=0,
        likes=0,
        comments=0,
        shares=0,
        saves=0,
        follows=0,
        completion_rate=0.0,
        three_second_view_rate=0.0,
        avg_watch_seconds=0.0,
        extra_metrics=None,
    ):
        extra_metrics = extra_metrics or {}
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO performance(
                    job_id,platform,views,likes,comments,shares,saves,follows,
                    completion_rate,three_second_view_rate,avg_watch_seconds,extra_metrics_json,recorded_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform) DO UPDATE SET views=excluded.views,likes=excluded.likes,
                comments=excluded.comments,shares=excluded.shares,saves=excluded.saves,follows=excluded.follows,
                completion_rate=excluded.completion_rate,three_second_view_rate=excluded.three_second_view_rate,
                avg_watch_seconds=excluded.avg_watch_seconds,extra_metrics_json=excluded.extra_metrics_json,recorded_at=excluded.recorded_at""",
                (
                    job_id,
                    platform,
                    int(views),
                    int(likes),
                    int(comments),
                    int(shares),
                    int(saves),
                    int(follows),
                    float(completion_rate),
                    float(three_second_view_rate),
                    float(avg_watch_seconds),
                    json.dumps(extra_metrics, ensure_ascii=False, sort_keys=True),
                    utc_now(),
                ),
            )

    def performance(self, job_id=None):
        if job_id:
            rows = self._rows(
                """SELECT p.*, json_extract(j.brief_json, '$.source') AS job_source
                FROM performance p LEFT JOIN jobs j ON j.id=p.job_id
                WHERE p.job_id=? ORDER BY p.platform""",
                (job_id,),
            )
        else:
            rows = self._rows(
                """SELECT p.*, json_extract(j.brief_json, '$.source') AS job_source
                FROM performance p LEFT JOIN jobs j ON j.id=p.job_id
                ORDER BY p.recorded_at DESC""",
                (),
            )
        for row in rows:
            try:
                extra_metrics = json.loads(row.pop("extra_metrics_json", "{}") or "{}")
            except json.JSONDecodeError:
                extra_metrics = {}
            row["extra_metrics"] = extra_metrics if isinstance(extra_metrics, dict) else {}
        return rows

    def feedback_summary(self):
        count_by_platform = {}
        extra_count_by_platform = {}
        rate_fields = ("completion_rate", "three_second_view_rate", "avg_watch_seconds")
        summary = {
            "platforms": {},
            "totals": {
                "views": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "saves": 0,
                "follows": 0,
                "engagement": 0,
                "completion_rate": 0.0,
                "three_second_view_rate": 0.0,
                "avg_watch_seconds": 0.0,
            },
        }
        for row in self.performance():
            if not _performance_has_growth_signal(row):
                continue
            platform = row["platform"]
            platform_entry = summary["platforms"].setdefault(
                platform,
                {
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "saves": 0,
                    "follows": 0,
                    "engagement": 0,
                    "completion_rate": 0.0,
                    "three_second_view_rate": 0.0,
                    "avg_watch_seconds": 0.0,
                    "sample_count": 0,
                    "extra_metrics": {},
                },
            )
            count_by_platform[platform] = count_by_platform.get(platform, 0) + 1
            platform_entry["sample_count"] = count_by_platform[platform]
            for key in ("views", "likes", "comments", "shares", "saves", "follows"):
                value = int(row.get(key, 0))
                platform_entry[key] += value
                summary["totals"][key] += value
            for key in rate_fields:
                platform_entry[key] += float(row.get(key, 0) or 0)
                summary["totals"][key] += float(row.get(key, 0) or 0)
            for key, value in (row.get("extra_metrics") or {}).items():
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                platform_entry["extra_metrics"][key] = platform_entry["extra_metrics"].get(key, 0.0) + numeric
                extra_count_by_platform[(platform, key)] = extra_count_by_platform.get((platform, key), 0) + 1
            engagement = platform_entry["likes"] + platform_entry["comments"] + platform_entry["shares"] + platform_entry["saves"]
            platform_entry["engagement"] = engagement
        total_rows = sum(count_by_platform.values())
        for platform, count in count_by_platform.items():
            for key in rate_fields:
                summary["platforms"][platform][key] = round(summary["platforms"][platform][key] / max(1, count), 4)
        for (platform, key), count in extra_count_by_platform.items():
            summary["platforms"][platform]["extra_metrics"][key] = round(summary["platforms"][platform]["extra_metrics"][key] / max(1, count), 4)
        if total_rows:
            for key in rate_fields:
                summary["totals"][key] = round(summary["totals"][key] / total_rows, 4)
        summary["totals"]["engagement"] = (
            summary["totals"]["likes"] + summary["totals"]["comments"] + summary["totals"]["shares"] + summary["totals"]["saves"]
        )
        return summary

    def save_source_items(self, job_id, items):
        with self.connect() as conn:
            conn.execute("DELETE FROM source_items WHERE job_id=?", (job_id,))
            for item in items or []:
                conn.execute(
                    """INSERT INTO source_items(job_id,source_type,platform,account_handle,display_name,title,body,url,source,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        job_id,
                        str(item.get("source_type", "")),
                        str(item.get("platform", "")),
                        str(item.get("account_handle", "")),
                        str(item.get("display_name", "")),
                        str(item.get("title", "")),
                        str(item.get("body", "")),
                        str(item.get("url", "")),
                        str(item.get("source", "")),
                        utc_now(),
                    ),
                )

    def source_items(self, job_id=None):
        if job_id:
            return self._rows("SELECT * FROM source_items WHERE job_id=? ORDER BY id", (job_id,))
        return self._rows("SELECT * FROM source_items ORDER BY id", ())

    def save_account_snapshots(self, job_id, accounts):
        with self.connect() as conn:
            conn.execute("DELETE FROM account_snapshots WHERE job_id=?", (job_id,))
            for account in accounts or []:
                conn.execute(
                    """INSERT INTO account_snapshots(job_id,account_handle,platform,display_name,sample_count,payload_json,created_at)
                    VALUES(?,?,?,?,?,?,?)""",
                    (
                        job_id,
                        str(account.get("account_handle", "")),
                        str(account.get("platform", "")),
                        str(account.get("display_name", "")),
                        int(account.get("sample_count", 0)),
                        json.dumps(account, ensure_ascii=False),
                        utc_now(),
                    ),
                )

    def account_snapshots(self, job_id=None):
        rows = self._rows("SELECT * FROM account_snapshots WHERE job_id=? ORDER BY id", (job_id,)) if job_id else self._rows("SELECT * FROM account_snapshots ORDER BY id", ())
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def save_idea_candidates(self, job_id, ideas):
        with self.connect() as conn:
            conn.execute("DELETE FROM idea_candidates WHERE job_id=?", (job_id,))
            for idea in ideas or []:
                conn.execute(
                    """INSERT INTO idea_candidates(job_id,topic,score,content_form,payload_json,created_at)
                    VALUES(?,?,?,?,?,?)""",
                    (
                        job_id,
                        str(idea.get("topic", "")),
                        float(idea.get("score", 0)),
                        str(idea.get("content_form", "")),
                        json.dumps(idea, ensure_ascii=False),
                        utc_now(),
                    ),
                )

    def idea_candidates(self, job_id=None):
        rows = self._rows("SELECT * FROM idea_candidates WHERE job_id=? ORDER BY score DESC,id" , (job_id,)) if job_id else self._rows("SELECT * FROM idea_candidates ORDER BY score DESC,id", ())
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def save_topic_clusters(self, job_id, clusters):
        with self.connect() as conn:
            conn.execute("DELETE FROM topic_clusters WHERE job_id=?", (job_id,))
            for cluster in clusters or []:
                conn.execute(
                    """INSERT INTO topic_clusters(job_id,cluster_key,label,score,payload_json,created_at)
                    VALUES(?,?,?,?,?,?)""",
                    (
                        job_id,
                        str(cluster.get("cluster_key", "")),
                        str(cluster.get("label", "")),
                        float(cluster.get("score", 0)),
                        json.dumps(cluster, ensure_ascii=False),
                        utc_now(),
                    ),
                )

    def topic_clusters(self, job_id=None):
        rows = self._rows("SELECT * FROM topic_clusters WHERE job_id=? ORDER BY score DESC,id", (job_id,)) if job_id else self._rows("SELECT * FROM topic_clusters ORDER BY score DESC,id", ())
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def related_topic_clusters(self, topic, limit=5):
        tokens = {token for token in str(topic or "").casefold().replace("-", " ").split() if token}
        matched = []
        for row in self.topic_clusters():
            payload = row.get("payload", {})
            haystack = " ".join(
                [
                    str(row.get("cluster_key", "")),
                    str(row.get("label", "")),
                    " ".join(str(signal) for signal in payload.get("topic_signals", [])),
                ]
            ).casefold()
            overlap = sum(1 for token in tokens if token in haystack)
            if overlap:
                matched.append((overlap, row))
        matched.sort(key=lambda item: (-item[0], -float(item[1].get("score", 0))))
        return [row for _, row in matched[:limit]]

    def historical_performance(self, platforms=None, topic=None):
        summary = {"platforms": {}, "clusters": []}
        platforms = [str(platform) for platform in (platforms or []) if str(platform).strip()]
        with self.connect() as conn:
            args = []
            sql = """SELECT p.platform,
                AVG(p.views) avg_views,
                AVG(p.likes + p.comments + p.shares + p.saves) avg_engagement,
                AVG(p.saves) avg_saves,
                AVG(p.follows) avg_follows,
                AVG(p.completion_rate) avg_completion_rate,
                AVG(p.three_second_view_rate) avg_three_second_view_rate,
                AVG(p.avg_watch_seconds) avg_watch_seconds,
                COUNT(*) sample_count
                FROM performance p
                JOIN jobs j ON j.id = p.job_id"""
            clauses = []
            clauses.append(
                "(p.views > 0 OR p.likes > 0 OR p.comments > 0 OR p.shares > 0 OR p.saves > 0 OR p.follows > 0 OR "
                "p.completion_rate > 0 OR p.three_second_view_rate > 0 OR p.avg_watch_seconds > 0)"
            )
            # Account snapshots are retained for auditability but must never
            # become evidence for content-level ranking or growth strategy.
            clauses.append("COALESCE(json_extract(p.extra_metrics_json, '$.strategy_eligible'), 1) != 0")
            # Older snapshots predate the explicit eligibility field. Their
            # creator/public page source is still only an account aggregate,
            # so exclude it until a verified content export replaces it.
            clauses.append(
                "(COALESCE(json_extract(p.extra_metrics_json, '$.metric_source'), '') "
                "NOT IN ('creator_backend_page', 'public_page', 'wechat_backend_cookie') "
                "OR json_extract(p.extra_metrics_json, '$.strategy_eligible') = 1)"
            )
            clauses.append(
                "(COALESCE(json_extract(j.brief_json, '$.source'), '') != 'performance_cycle' "
                "OR json_extract(p.extra_metrics_json, '$.strategy_eligible') = 1)"
            )
            clauses.append("NOT (p.platform='tiktok' AND p.views=0 AND (p.likes + p.comments + p.shares + p.saves)=0)")
            if platforms:
                placeholders = ",".join("?" for _ in platforms)
                clauses.append(f"p.platform IN ({placeholders})")
                args.extend(platforms)
            if topic:
                clauses.append("LOWER(j.topic) LIKE ?")
                args.append(f"%{str(topic).casefold()}%")
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " GROUP BY p.platform ORDER BY p.platform"
            for row in conn.execute(sql, tuple(args)):
                summary["platforms"][row["platform"]] = {
                    "views": round(float(row["avg_views"] or 0), 3),
                    "engagement": round(float(row["avg_engagement"] or 0), 3),
                    "saves": round(float(row["avg_saves"] or 0), 3),
                    "follows": round(float(row["avg_follows"] or 0), 3),
                    "completion_rate": round(float(row["avg_completion_rate"] or 0), 4),
                    "three_second_view_rate": round(float(row["avg_three_second_view_rate"] or 0), 4),
                    "avg_watch_seconds": round(float(row["avg_watch_seconds"] or 0), 3),
                    "sample_count": int(row["sample_count"] or 0),
                }
        if topic:
            summary["clusters"] = [row.get("payload", {}) for row in self.related_topic_clusters(topic)]
        return summary

    def learned_ranking_context(self, profile_name="default"):
        platform_perf = self.feedback_summary().get("platforms", {})
        cluster_rows = self.topic_clusters()
        weighted_clusters = []
        for row in cluster_rows:
            payload = row.get("payload", {})
            cluster_platforms = payload.get("platforms", [])
            perf_boost = 0.0
            for platform in cluster_platforms:
                perf_boost += float(platform_perf.get(platform, {}).get("engagement", 0)) / max(
                    1.0, float(platform_perf.get(platform, {}).get("views", 0))
                )
            weighted_clusters.append(
                {
                    "label": row.get("label", ""),
                    "cluster_key": row.get("cluster_key", ""),
                    "weight": round(float(row.get("score", 0)) + min(perf_boost, 1.0), 3),
                    "topic_signals": payload.get("topic_signals", []),
                }
            )
        weighted_clusters.sort(key=lambda item: item["weight"], reverse=True)
        preferred_sources = {}
        for platform, summary in platform_perf.items():
            score = min(1.5, float(summary.get("engagement", 0)) / max(1.0, float(summary.get("views", 0))) * 3)
            if score > 0:
                preferred_sources[platform] = round(score, 3)
        return {
            "profile": profile_name,
            "preferred_clusters": weighted_clusters[:8],
            "preferred_sources": preferred_sources,
        }

    def save_tool_inventory(self, snapshot_name, payload):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO tool_inventory(snapshot_name,payload_json,created_at) VALUES(?,?,?)",
                (snapshot_name, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def latest_tool_inventory(self, snapshot_name):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_inventory WHERE snapshot_name=? ORDER BY id DESC LIMIT 1",
                (snapshot_name,),
            ).fetchone()
        if not row:
            return {}
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def save_content_package(self, package, job_id=""):
        payload = package.to_dict() if hasattr(package, "to_dict") else dict(package)
        content_package_id = str(payload.get("content_package_id") or "")
        if not content_package_id:
            raise ValueError("content_package_id is required")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO content_packages(
                    content_package_id,job_id,platform,account_id,status,content_type,topic,title,payload_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_package_id) DO UPDATE SET
                    job_id=excluded.job_id,
                    platform=excluded.platform,
                    account_id=excluded.account_id,
                    status=excluded.status,
                    content_type=excluded.content_type,
                    topic=excluded.topic,
                    title=excluded.title,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at""",
                (
                    content_package_id,
                    str(payload.get("job_id") or job_id or ""),
                    str(payload.get("platform") or ""),
                    str(payload.get("account_id") or ""),
                    str(payload.get("status") or "created"),
                    str(payload.get("content_type") or ""),
                    str(payload.get("topic") or ""),
                    str(payload.get("title") or ""),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_content_package(content_package_id)

    def get_content_package(self, content_package_id):
        rows = self.content_packages(content_package_id=content_package_id, limit=1)
        if not rows:
            raise KeyError(f"content package not found: {content_package_id}")
        return rows[0]

    def content_packages(self, content_package_id="", job_id="", platform="", limit=200):
        sql = "SELECT * FROM content_packages"
        clauses, args = [], []
        if content_package_id:
            clauses.append("content_package_id=?")
            args.append(content_package_id)
        if job_id:
            clauses.append("job_id=?")
            args.append(job_id)
        if platform:
            clauses.append("platform=?")
            args.append(platform)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        rows = self._rows(sql, tuple(args))
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
        return rows

    def save_publish_receipt(self, content_package_id, platform, receipt, job_id=""):
        payload = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt)
        package_id = str(content_package_id or "")
        platform_name = str(platform or payload.get("platform") or "")
        status = str(payload.get("status") or "")
        platform_content_id = str(payload.get("platform_content_id") or "")
        with self.connect() as conn:
            existing = conn.execute(
                """SELECT id FROM publish_receipts
                   WHERE content_package_id=? AND platform=? AND status=? AND platform_content_id=?
                   ORDER BY id DESC LIMIT 1""",
                (package_id, platform_name, status, platform_content_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE publish_receipts
                       SET job_id=?, verification_level=?, url=?, payload_json=?, created_at=?
                       WHERE id=?""",
                    (
                        str(job_id or payload.get("job_id") or ""),
                        str(payload.get("verification_level") or ""),
                        str(payload.get("url") or ""),
                        json.dumps(payload, ensure_ascii=False),
                        utc_now(),
                        existing["id"],
                    ),
                )
                return
            conn.execute(
                """INSERT INTO publish_receipts(
                    content_package_id,job_id,platform,status,verification_level,platform_content_id,url,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    package_id,
                    str(job_id or payload.get("job_id") or ""),
                    platform_name,
                    status,
                    str(payload.get("verification_level") or ""),
                    platform_content_id,
                    str(payload.get("url") or ""),
                    json.dumps(payload, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def publish_receipts(self, content_package_id="", job_id="", platform="", limit=100):
        sql = "SELECT * FROM publish_receipts"
        clauses, args = [], []
        if content_package_id:
            clauses.append("content_package_id=?")
            args.append(content_package_id)
        if job_id:
            clauses.append("job_id=?")
            args.append(job_id)
        if platform:
            clauses.append("platform=?")
            args.append(platform)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        rows = self._rows(sql, tuple(args))
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
        return rows

    def create_review_tasks(self, content_package_id, platform, schedule, job_id=""):
        created = []
        with self.connect() as conn:
            for item in schedule:
                hours = int(item.get("hours", item.get("review_point_hours", item.get("after_publish_hours", 0))))
                purpose = str(item.get("purpose") or f"status review at {hours}h")
                due_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")
                conn.execute(
                    """INSERT INTO review_tasks(content_package_id,job_id,platform,review_point_hours,purpose,state,due_at,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (content_package_id, job_id, platform, hours, purpose, "pending", due_at, utc_now()),
                )
                created.append({
                    "content_package_id": content_package_id,
                    "job_id": job_id,
                    "platform": platform,
                    "review_point_hours": hours,
                    "purpose": purpose,
                    "state": "pending",
                    "due_at": due_at,
                })
        return created

    def review_tasks(self, state="", limit=100):
        sql = "SELECT * FROM review_tasks"
        args = []
        if state:
            sql += " WHERE state=?"
            args.append(state)
        sql += " ORDER BY id LIMIT ?"
        args.append(int(limit))
        return self._rows(sql, tuple(args))

    def enqueue_delivery(self, job_id, platform, action, payload=None):
        now = utc_now()
        payload = payload or {}
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT state FROM delivery_queue WHERE job_id=? AND platform=? AND action=?",
                (job_id, platform, action),
            ).fetchone()
            retry_requested = bool(payload.get("retry"))
            state = "queued"
            if existing and existing["state"] in {"completed", "handoff_ready"} and not retry_requested:
                state = existing["state"]
            conn.execute(
                """INSERT INTO delivery_queue(job_id,platform,action,state,payload_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform,action) DO UPDATE SET
                state=excluded.state,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at""",
                (job_id, platform, action, state, json.dumps(payload, ensure_ascii=False), now, now),
            )
            self._event(conn, job_id, "delivery_enqueued", {"platform": platform, "action": action, "retry": retry_requested})

    def claim_delivery(self, owner, ttl_seconds=300):
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("delivery claim requires owner")
        now = utc_now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM delivery_queue
                WHERE state='queued' AND (lease_owner='' OR lease_expires_at='' OR lease_expires_at<=?)
                ORDER BY id LIMIT 1""",
                (now,),
            ).fetchone()
            if not row:
                return {}
            conn.execute(
                """UPDATE delivery_queue
                SET state='processing', lease_owner=?, lease_expires_at=?, attempts=attempts+1, updated_at=?
                WHERE id=?""",
                (owner, expires, now, row["id"]),
            )
            result = dict(row)
            result["state"] = "processing"
            result["lease_owner"] = owner
            result["lease_expires_at"] = expires
            result["attempts"] = int(result.get("attempts", 0)) + 1
            result["payload"] = json.loads(result.pop("payload_json", "{}"))
            return result

    def complete_delivery(self, queue_id, owner, state, error=""):
        if state not in {"completed", "failed", "queued", "handoff_ready"}:
            raise ValueError("invalid delivery queue state")
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE delivery_queue
                SET state=?, lease_owner='', lease_expires_at='', error=?, updated_at=?
                WHERE id=? AND lease_owner=?""",
                (state, str(error), utc_now(), queue_id, owner),
            )
            if cursor.rowcount != 1:
                raise ValueError("delivery claim is not owned by caller")

    def list_delivery_queue(self, state=None):
        sql = "SELECT * FROM delivery_queue"
        args = []
        if state:
            sql += " WHERE state=?"
            args.append(state)
        sql += " ORDER BY id"
        rows = self._rows(sql, tuple(args))
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
        return rows

    def used_topics(self, platform=None, lookback_days=None):
        clauses, args = [], []
        if platform:
            clauses.append("platform IN (?, '')")
            args.append(str(platform))
        if lookback_days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, int(lookback_days)))).isoformat(timespec="seconds")
            clauses.append("datetime(used_at) >= datetime(?)")
            args.append(cutoff)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.connect() as conn:
            return {row[0] for row in conn.execute("SELECT fingerprint FROM topic_history" + where, tuple(args))}

    def mark_topic_used(self, fingerprint, title, source, job_id, platform=""):
        if not fingerprint:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO topic_history(fingerprint,platform,title,source,job_id,used_at) VALUES(?,?,?,?,?,?)",
                (fingerprint, str(platform or ""), title, source or "", job_id, utc_now()),
            )

    def record_manual_publication(self, platform, topic, *, topic_fingerprint="", external_id="", source="manual_publish"):
        """Create a first-class receipt so manual work participates in deduplication."""
        normalized_platform = str(platform or "").strip()
        normalized_topic = str(topic or "").strip()
        fingerprint = str(topic_fingerprint or normalized_topic.casefold()).strip()
        if not normalized_platform or not normalized_topic or not fingerprint:
            raise ValueError("manual publication requires platform, topic, and topic fingerprint")
        job = self.create_job(
            normalized_topic,
            [normalized_platform],
            {"source": source, "manual_publication": True, "platform": normalized_platform},
            profile="manual",
            topic_fingerprint=fingerprint,
        )
        self.transition(job["id"], {"created"}, "published", "manual_publication_recorded", {"source": source})
        self.save_delivery(job["id"], normalized_platform, "published", external_id, "manual publication recorded")
        self.mark_topic_used(fingerprint, normalized_topic, source, job["id"], platform=normalized_platform)
        return {"job_id": job["id"], "platform": normalized_platform, "status": "published", "topic_fingerprint": fingerprint}

    def protected_paths(self):
        with self.connect() as conn:
            paths = [row[0] for row in conn.execute("SELECT path FROM artifacts")]
            paths += [row[0] for row in conn.execute("SELECT external_id FROM deliveries WHERE external_id LIKE '/%' ")]
        return set(paths)

    def save_geo_score(self, job_id, geo_result):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO geo_scores(job_id,score,payload_json,created_at) VALUES(?,?,?,?)",
                (job_id, geo_result.get("score", 0), json.dumps(geo_result, ensure_ascii=False), utc_now()),
            )

    def geo_scores(self, job_id=None):
        with self.connect() as conn:
            if job_id:
                rows = conn.execute("SELECT * FROM geo_scores WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
            else:
                rows = conn.execute("SELECT * FROM geo_scores ORDER BY id DESC LIMIT 100")
            return [dict(row) for row in rows]

    def save_schedule(self, payload):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO schedules(topic,platforms,brief,profile,cron,enabled,label,next_run,last_run,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (payload["topic"], payload.get("platforms", "[]"), payload.get("brief", "{}"),
                 payload.get("profile", "default"), payload.get("cron", "@daily"),
                 payload.get("enabled", 1), payload.get("label", ""), payload.get("next_run", ""),
                 payload.get("last_run", ""), payload.get("created_at", utc_now())),
            )

    def list_schedules(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM schedules ORDER BY id")]

    def update_schedule(self, schedule_id, enabled=None, next_run=None, last_run=None):
        with self.connect() as conn:
            if enabled is not None:
                conn.execute("UPDATE schedules SET enabled=? WHERE id=?", (int(enabled), schedule_id))
            if next_run is not None:
                conn.execute("UPDATE schedules SET next_run=? WHERE id=?", (next_run, schedule_id))
            if last_run is not None:
                conn.execute("UPDATE schedules SET last_run=? WHERE id=?", (last_run, schedule_id))

    def _rows(self, sql, args):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    @staticmethod
    def _event(conn, job_id, event, detail):
        conn.execute(
            "INSERT INTO events(job_id,event,detail_json,created_at) VALUES(?,?,?,?)",
            (job_id, event, json.dumps(detail, ensure_ascii=False), utc_now()),
        )

    @staticmethod
    def _ensure_column(conn, table, name, definition):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _job(row):
        result = dict(row)
        result["brief"] = json.loads(result.pop("brief_json"))
        result["platforms"] = json.loads(result.pop("platforms_json"))
        result["risk"] = json.loads(result.pop("risk_json"))
        result["draft_meta"] = json.loads(result.pop("draft_meta_json", "{}"))
        result["acceptance"] = json.loads(result.pop("acceptance_json", "{}"))
        return result
