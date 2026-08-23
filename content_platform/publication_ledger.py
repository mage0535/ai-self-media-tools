"""Verified publication identity and metric-window ledger."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "72h": timedelta(hours=72)}
REQUIRED_METRICS = {"default": ("views", "likes", "comments", "shares")}


class PublicationLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS publication_identities (
              id INTEGER PRIMARY KEY, platform TEXT NOT NULL, account_alias TEXT NOT NULL,
              content_id TEXT NOT NULL, canonical_url TEXT NOT NULL, published_at TEXT NOT NULL,
              verification_level TEXT NOT NULL, UNIQUE(platform, account_alias, content_id)
            );
            CREATE TABLE IF NOT EXISTS metric_windows (
              id INTEGER PRIMARY KEY, publication_id INTEGER NOT NULL, window TEXT NOT NULL,
              collect_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              data_json TEXT NOT NULL DEFAULT '{}', required_metrics_json TEXT NOT NULL DEFAULT '[]',
              attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL DEFAULT '',
              UNIQUE(publication_id, window)
            );
            CREATE TABLE IF NOT EXISTS metric_observations (
              id INTEGER PRIMARY KEY, window_id INTEGER NOT NULL, source TEXT NOT NULL,
              confidence TEXT NOT NULL, metrics_json TEXT NOT NULL, collected_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metric_collection_attempts (
              id INTEGER PRIMARY KEY, window_id INTEGER NOT NULL, attempt_no INTEGER NOT NULL,
              status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL,
              finished_at TEXT NOT NULL, next_attempt_at TEXT NOT NULL DEFAULT ''
            );
            """)
            self._ensure_column(conn, "metric_windows", "required_metrics_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "metric_windows", "attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "metric_windows", "next_attempt_at", "TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_column(conn, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def register(self, identity: dict) -> dict:
        required = ("platform", "internal_account_alias", "platform_content_id", "canonical_url", "published_at", "verification_level")
        if any(not str(identity.get(key) or "").strip() for key in required):
            return {"ok": False, "reason": "publication_identity_incomplete"}
        if identity["verification_level"] not in {"url_verified", "postcheck_verified"}:
            return {"ok": False, "reason": "publication_identity_unverified"}
        if not str(identity["canonical_url"]).startswith(("http://", "https://")):
            return {"ok": False, "reason": "canonical_url_invalid"}
        published = _parse_time(identity["published_at"])
        if not published:
            return {"ok": False, "reason": "published_at_invalid"}
        with self._connect() as conn:
            cur = conn.execute("INSERT OR IGNORE INTO publication_identities(platform,account_alias,content_id,canonical_url,published_at,verification_level) VALUES(?,?,?,?,?,?)", (identity["platform"], identity["internal_account_alias"], identity["platform_content_id"], identity["canonical_url"], published.isoformat(), identity["verification_level"]))
            row = conn.execute("SELECT id FROM publication_identities WHERE platform=? AND account_alias=? AND content_id=?", (identity["platform"], identity["internal_account_alias"], identity["platform_content_id"])).fetchone()
            for window, delta in WINDOWS.items():
                conn.execute("INSERT OR IGNORE INTO metric_windows(publication_id,window,collect_at,required_metrics_json) VALUES(?,?,?,?)", (row["id"], window, (published + delta).isoformat(), json.dumps(REQUIRED_METRICS["default"])))
        return {"ok": True, "publication_id": row["id"], "created": bool(cur.rowcount)}

    def due_windows(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM metric_windows WHERE status='pending' AND collect_at<=? AND (next_attempt_at='' OR next_attempt_at<=?)", (now.isoformat(), now.isoformat())).fetchall()
            return [dict(row) for row in rows]

    def identity_for_window(self, window_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT p.* FROM publication_identities p JOIN metric_windows m ON m.publication_id=p.id WHERE m.id=?", (window_id,)).fetchone()
            return dict(row) if row else None

    def record_metrics(self, platform: str, account_alias: str, content_id: str, window: str, metrics: dict, *, source: str = "collector", confidence: str = "unknown") -> bool:
        if window not in WINDOWS:
            return False
        if not isinstance(metrics, dict) or not metrics:
            metrics = {"status": None}
        safe = {key: ("insufficient" if value is None or (isinstance(value, (int, float)) and value < 0) else value) for key, value in metrics.items()}
        with self._connect() as conn:
            row = conn.execute("SELECT m.id,m.required_metrics_json FROM metric_windows m JOIN publication_identities p ON p.id=m.publication_id WHERE p.platform=? AND p.account_alias=? AND p.content_id=? AND m.window=?", (platform, account_alias, content_id, window)).fetchone()
            if not row:
                return False
            required = json.loads(row["required_metrics_json"] or "[]")
            missing = [key for key in required if safe.get(key) in (None, "insufficient")]
            status = "insufficient" if missing or any(value == "insufficient" for value in safe.values()) else "collected"
            conn.execute("UPDATE metric_windows SET status=?,data_json=?,next_attempt_at='' WHERE id=?", (status, json.dumps({**safe, "missing_metrics": missing}, ensure_ascii=False), row["id"]))
            conn.execute("INSERT INTO metric_observations(window_id,source,confidence,metrics_json,collected_at) VALUES(?,?,?,?,?)", (row["id"], source, confidence, json.dumps({**safe, "missing_metrics": missing}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        return True

    def record_collection_attempt(self, window_id: int, status: str, *, error: str = "", next_attempt_at: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute("SELECT attempts FROM metric_windows WHERE id=?", (window_id,)).fetchone()
            attempt_no = int(row["attempts"] if row else 0) + 1
            conn.execute("UPDATE metric_windows SET attempts=?,next_attempt_at=? WHERE id=?", (attempt_no, next_attempt_at, window_id))
            conn.execute("INSERT INTO metric_collection_attempts(window_id,attempt_no,status,error,started_at,finished_at,next_attempt_at) VALUES(?,?,?,?,?,?,?)", (window_id, attempt_no, status, error, now, now, next_attempt_at))
        return attempt_no

    def ready_for_analysis(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT p.* FROM publication_identities p WHERE NOT EXISTS (SELECT 1 FROM metric_windows m WHERE m.publication_id=p.id AND m.status!='collected')").fetchall()
            return [dict(row) for row in rows]


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def identity_from_delivery(platform: str, result, *, account_alias: str | None = None, published_at: str | None = None) -> dict | None:
    """Build an identity only from a verified published result with a canonical URL."""
    if getattr(result, "status", "") != "published":
        return None
    external_id = str(getattr(result, "external_id", "") or "")
    url = str(getattr(result, "canonical_url", "") or "")
    verification = str(getattr(result, "verification_level", "") or "")
    if verification not in {"url_verified", "postcheck_verified"}:
        return None
    if not url:
        return None
    return {
        "platform": platform,
        "internal_account_alias": account_alias or str(getattr(result, "account_alias", "") or platform),
        "platform_content_id": external_id,
        "canonical_url": url,
        "published_at": published_at or str(getattr(result, "published_at", "") or datetime.now(timezone.utc).isoformat()),
        "verification_level": verification,
    }
