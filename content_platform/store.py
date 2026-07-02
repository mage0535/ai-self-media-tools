import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
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
                    fingerprint TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    used_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    platform TEXT NOT NULL,
                    views INTEGER NOT NULL DEFAULT 0,
                    likes INTEGER NOT NULL DEFAULT 0,
                    comments INTEGER NOT NULL DEFAULT 0,
                    shares INTEGER NOT NULL DEFAULT 0,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(job_id, platform)
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
                """
            )
            for name, definition in {
                "profile": "TEXT NOT NULL DEFAULT 'default'",
                "prompt_version": "TEXT NOT NULL DEFAULT ''",
                "draft_meta_json": "TEXT NOT NULL DEFAULT '{}'",
                "lease_owner": "TEXT NOT NULL DEFAULT ''",
                "lease_expires_at": "TEXT NOT NULL DEFAULT ''",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "last_error": "TEXT NOT NULL DEFAULT ''",
                "topic_fingerprint": "TEXT NOT NULL DEFAULT ''",
            }.items():
                self._ensure_column(conn, "jobs", name, definition)
            for name, definition in {
                "idempotency_key": "TEXT NOT NULL DEFAULT ''",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                self._ensure_column(conn, "deliveries", name, definition)

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

    def save_draft(self, job_id, title, body, risk_level, risk, prompt_version="", draft_meta=None):
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET title=?,body=?,risk_level=?,risk_json=?,prompt_version=?,draft_meta_json=?,updated_at=? WHERE id=?",
                (title, body, risk_level, json.dumps(risk, ensure_ascii=False), prompt_version, json.dumps(draft_meta or {}, ensure_ascii=False), utc_now(), job_id),
            )
            self._event(conn, job_id, "draft_saved", {"risk_level": risk_level})

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
        return recovered

    def record_event(self, job_id, event, detail=None):
        with self.connect() as conn:
            self._event(conn, job_id, event, detail or {})

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

    def record_performance(self, job_id, platform, views=0, likes=0, comments=0, shares=0):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO performance(job_id,platform,views,likes,comments,shares,recorded_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform) DO UPDATE SET views=excluded.views,likes=excluded.likes,
                comments=excluded.comments,shares=excluded.shares,recorded_at=excluded.recorded_at""",
                (job_id, platform, int(views), int(likes), int(comments), int(shares), utc_now()),
            )

    def performance(self, job_id=None):
        if job_id:
            return self._rows("SELECT * FROM performance WHERE job_id=? ORDER BY platform", (job_id,))
        return self._rows("SELECT * FROM performance ORDER BY recorded_at DESC", ())

    def used_topics(self):
        with self.connect() as conn:
            return {row[0] for row in conn.execute("SELECT fingerprint FROM topic_history")}

    def mark_topic_used(self, fingerprint, title, source, job_id):
        if not fingerprint:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO topic_history(fingerprint,title,source,job_id,used_at) VALUES(?,?,?,?,?)",
                (fingerprint, title, source or "", job_id, utc_now()),
            )

    def protected_paths(self):
        with self.connect() as conn:
            paths = [row[0] for row in conn.execute("SELECT path FROM artifacts")]
            paths += [row[0] for row in conn.execute("SELECT external_id FROM deliveries WHERE external_id LIKE '/%' ")]
        return set(paths)

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
        return result
