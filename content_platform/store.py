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
                CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
                CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);
                CREATE INDEX IF NOT EXISTS idx_delivery_queue_state ON delivery_queue(state, id);
                CREATE INDEX IF NOT EXISTS idx_topic_clusters_key ON topic_clusters(cluster_key, id);
                CREATE INDEX IF NOT EXISTS idx_draft_versions_job ON draft_versions(job_id, id);
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

    def deliveries_all(self):
        return self._rows("SELECT * FROM deliveries ORDER BY updated_at DESC, id DESC", ())

    def draft_versions(self, job_id):
        rows = self._rows("SELECT * FROM draft_versions WHERE job_id=? ORDER BY id", (job_id,))
        for row in rows:
            row["draft_meta"] = json.loads(row.pop("draft_meta_json", "{}"))
        return rows

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

    def feedback_summary(self):
        summary = {"platforms": {}, "totals": {"views": 0, "likes": 0, "comments": 0, "shares": 0, "engagement": 0}}
        for row in self.performance():
            platform = row["platform"]
            platform_entry = summary["platforms"].setdefault(platform, {"views": 0, "likes": 0, "comments": 0, "shares": 0, "engagement": 0})
            for key in ("views", "likes", "comments", "shares"):
                value = int(row.get(key, 0))
                platform_entry[key] += value
                summary["totals"][key] += value
            engagement = platform_entry["likes"] + platform_entry["comments"] + platform_entry["shares"]
            platform_entry["engagement"] = engagement
        summary["totals"]["engagement"] = summary["totals"]["likes"] + summary["totals"]["comments"] + summary["totals"]["shares"]
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
                AVG(p.likes + p.comments + p.shares) avg_engagement,
                COUNT(*) sample_count
                FROM performance p
                JOIN jobs j ON j.id = p.job_id"""
            clauses = []
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

    def enqueue_delivery(self, job_id, platform, action, payload=None):
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO delivery_queue(job_id,platform,action,state,payload_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(job_id,platform,action) DO UPDATE SET
                state=CASE WHEN delivery_queue.state='completed' THEN delivery_queue.state ELSE 'queued' END,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at""",
                (job_id, platform, action, "queued", json.dumps(payload or {}, ensure_ascii=False), now, now),
            )
            self._event(conn, job_id, "delivery_enqueued", {"platform": platform, "action": action})

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
        if state not in {"completed", "failed", "queued"}:
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
        return result
