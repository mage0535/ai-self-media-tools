import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AdminStore:
    def __init__(self, db_path):
        self.path = Path(db_path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
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
                CREATE TABLE IF NOT EXISTS platform_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    auth_type TEXT NOT NULL DEFAULT 'manual',
                    status TEXT NOT NULL DEFAULT 'pending',
                    credentials_ref TEXT NOT NULL DEFAULT '',
                    track TEXT NOT NULL DEFAULT '',
                    current_status TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform, account_key)
                );
                CREATE INDEX IF NOT EXISTS idx_platform_accounts_platform ON platform_accounts(platform, updated_at DESC);
                """
            )

    def upsert_binding(self, platform, payload):
        payload = dict(payload or {})
        now = utc_now()
        account_key = str(payload.get("account_key") or payload.get("display_name") or "").strip()
        if not account_key:
            raise ValueError("binding requires account_key or display_name")
        row = {
            "platform": str(platform).strip(),
            "account_key": account_key,
            "display_name": str(payload.get("display_name") or account_key).strip(),
            "auth_type": str(payload.get("auth_type") or "manual").strip(),
            "status": str(payload.get("status") or "pending").strip(),
            "credentials_ref": str(payload.get("credentials_ref") or "").strip(),
            "track": str(payload.get("track") or "").strip(),
            "current_status": str(payload.get("current_status") or "").strip(),
            "notes": str(payload.get("notes") or "").strip(),
            "config_json": json.dumps(payload.get("config") or {}, ensure_ascii=False),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO platform_accounts(platform,account_key,display_name,auth_type,status,credentials_ref,track,current_status,notes,config_json,enabled,last_checked_at,last_error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?, '', '', ?, ?)
                ON CONFLICT(platform,account_key) DO UPDATE SET
                display_name=excluded.display_name,
                auth_type=excluded.auth_type,
                status=excluded.status,
                credentials_ref=excluded.credentials_ref,
                track=excluded.track,
                current_status=excluded.current_status,
                notes=excluded.notes,
                config_json=excluded.config_json,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at""",
                (
                    row["platform"],
                    row["account_key"],
                    row["display_name"],
                    row["auth_type"],
                    row["status"],
                    row["credentials_ref"],
                    row["track"],
                    row["current_status"],
                    row["notes"],
                    row["config_json"],
                    row["enabled"],
                    now,
                    now,
                ),
            )
        return self.get_binding_by_key(platform, account_key)

    def get_binding(self, binding_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM platform_accounts WHERE id=?", (int(binding_id),)).fetchone()
        if not row:
            raise KeyError(f"binding not found: {binding_id}")
        return self._binding(row)

    def get_binding_by_key(self, platform, account_key):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM platform_accounts WHERE platform=? AND account_key=?",
                (str(platform), str(account_key)),
            ).fetchone()
        if not row:
            raise KeyError(f"binding not found: {platform}:{account_key}")
        return self._binding(row)

    def list_bindings(self, platform=None):
        sql = "SELECT * FROM platform_accounts"
        args = []
        if platform:
            sql += " WHERE platform=?"
            args.append(str(platform))
        sql += " ORDER BY platform, updated_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [self._binding(row) for row in rows]

    def toggle_binding(self, binding_id, enabled):
        with self.connect() as conn:
            conn.execute(
                "UPDATE platform_accounts SET enabled=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, utc_now(), int(binding_id)),
            )
        return self.get_binding(binding_id)

    def delete_binding(self, binding_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM platform_accounts WHERE id=?", (int(binding_id),))

    def mark_binding_check(self, binding_id, status, error=""):
        with self.connect() as conn:
            conn.execute(
                "UPDATE platform_accounts SET status=?, last_error=?, last_checked_at=?, updated_at=? WHERE id=?",
                (str(status), str(error), utc_now(), utc_now(), int(binding_id)),
            )
        return self.get_binding(binding_id)

    @staticmethod
    def _binding(row):
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["config"] = json.loads(result.pop("config_json", "{}"))
        return result
