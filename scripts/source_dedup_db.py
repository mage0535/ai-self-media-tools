#!/usr/bin/env python3
"""搬运去重数据库 — SQLite 记录已搬运的 URL 和时间戳。"""
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path


class SourceDedupDB:
    def __init__(self, db_path=None):
        self.db_path = db_path or str(Path.home() / ".ai-self-media-tools" / "data" / "source_dedup.db")
        self._init()

    def _init(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS source_dedup (
                source_url TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT,
                downloaded_at TEXT NOT NULL,
                used_for TEXT,
                published INTEGER DEFAULT 0
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS content_dedup (
                content_hash TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            conn.commit()

    def is_duplicate(self, url):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT 1 FROM source_dedup WHERE source_url=?", (url,)).fetchone()
            return row is not None

    def record(self, url, platform="", title=""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO source_dedup(source_url, platform, title, downloaded_at) VALUES (?,?,?,?)",
                (url, platform, title, datetime.now().isoformat()),
            )
            conn.commit()

    def recent_by_platform(self, platform, days=3):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT source_url, title, downloaded_at FROM source_dedup WHERE platform=? AND downloaded_at>? ORDER BY downloaded_at DESC",
                (platform, cutoff),
            ).fetchall()
        return rows

    def count(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM source_dedup").fetchone()[0]


db = SourceDedupDB()
print(f"✅ 去重数据库就绪 | 当前记录: {db.count()}")
