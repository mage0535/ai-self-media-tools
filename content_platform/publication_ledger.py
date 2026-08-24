"""SQLite publication identity and post-publish metric windows."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERIFIED_LEVELS = {"url_verified", "postcheck_verified"}
REQUIRED_METRICS = ("views", "likes", "comments", "shares", "favorites", "followers")

class PublicationLedger:
    def __init__(self, path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _connect(self):
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row; c.execute("PRAGMA busy_timeout=30000"); return c
    def _init(self):
        with self._connect() as c:
            c.executescript("""CREATE TABLE IF NOT EXISTS publication_identities(id INTEGER PRIMARY KEY,platform TEXT NOT NULL,account_id TEXT NOT NULL,platform_content_id TEXT NOT NULL,canonical_url TEXT NOT NULL,published_at TEXT NOT NULL,verification_level TEXT NOT NULL,identity_source TEXT NOT NULL,metadata_json TEXT NOT NULL,UNIQUE(platform,account_id,platform_content_id));CREATE TABLE IF NOT EXISTS metric_windows(id INTEGER PRIMARY KEY,identity_id INTEGER NOT NULL,hours INTEGER NOT NULL,due_at TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',UNIQUE(identity_id,hours));CREATE TABLE IF NOT EXISTS metric_observations(id INTEGER PRIMARY KEY,window_id INTEGER NOT NULL,state TEXT NOT NULL,metrics_json TEXT NOT NULL,source TEXT NOT NULL,observed_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS metric_collection_attempts(id INTEGER PRIMARY KEY,window_id INTEGER NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL,attempted_at TEXT NOT NULL);""")
    def register_identity(self,payload):
        fields=("platform","account_id","platform_content_id","canonical_url","published_at","verification_level","identity_source")
        if any(not str(payload.get(k) or "").strip() for k in fields): return {"passed":False,"reason":"publication_identity_fields_missing"}
        if str(payload["verification_level"]) not in VERIFIED_LEVELS: return {"passed":False,"reason":"publication_not_independently_verified"}
        with self._connect() as c:
            c.execute("INSERT OR IGNORE INTO publication_identities(platform,account_id,platform_content_id,canonical_url,published_at,verification_level,identity_source,metadata_json) VALUES(?,?,?,?,?,?,?,?)",tuple(str(payload[k]) for k in fields[:-1])+ (json.dumps(payload,ensure_ascii=False),))
            row=c.execute("SELECT * FROM publication_identities WHERE platform=? AND account_id=? AND platform_content_id=?",(payload["platform"],payload["account_id"],payload["platform_content_id"])).fetchone()
            published=datetime.fromisoformat(str(payload["published_at"]).replace("Z","+00:00"))
            for hours in (1,24,72): c.execute("INSERT OR IGNORE INTO metric_windows(identity_id,hours,due_at,state) VALUES(?,?,?,?)",(row["id"],hours,(published+timedelta(hours=hours)).isoformat(),"pending"))
        return {"passed":True,"identity_id":row["id"]}
    def due_windows(self):
        with self._connect() as c: return [dict(r) for r in c.execute("SELECT * FROM metric_windows WHERE state='pending' ORDER BY due_at").fetchall()]
    def record_metrics(self,window_id,metrics,source="collector"):
        state="collected" if isinstance(metrics,dict) and any(metrics.get(k) is not None for k in REQUIRED_METRICS) else "insufficient"
        with self._connect() as c:
            c.execute("UPDATE metric_windows SET state=? WHERE id=?",(state,window_id)); c.execute("INSERT INTO metric_observations(window_id,state,metrics_json,source,observed_at) VALUES(?,?,?,?,?)",(window_id,state,json.dumps(metrics or {},ensure_ascii=False),source,datetime.now(timezone.utc).isoformat(timespec="seconds")))
        return {"state":state,"window_id":window_id}
