"""Read-only history overlay. Never construct Store or expose queue tables here."""

import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class HistoryUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


# Integer row IDs in independent databases are not global identities.
_KEYS = {
    "jobs": ("id",),
    "topic_history": ("fingerprint", "platform"),
    "performance": ("job_id", "platform"),
    "deliveries": ("job_id", "platform"),
}


def _resolved_file(value):
    try:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise OSError()
        return path
    except (OSError, RuntimeError, ValueError):
        raise HistoryUnavailable("HISTORY_DB_UNAVAILABLE") from None


def _mirror_path():
    value = os.environ.get("CONTENT_PLATFORM_HISTORY_DB", "").strip()
    required = os.environ.get("CONTENT_PLATFORM_HISTORY_REQUIRED", "").lower() in {"1", "true", "yes"}
    status_file = os.environ.get("CONTENT_PLATFORM_HISTORY_STATUS_FILE", "").strip()
    if required and not status_file:
        status_file = "/srv/business-sync/status.json"
    if not value:
        if required or status_file:
            raise HistoryUnavailable("HISTORY_DB_UNAVAILABLE")
        return None
    path = _resolved_file(value)
    try:
        max_age = float(os.environ.get("CONTENT_PLATFORM_HISTORY_MAX_AGE_SECONDS", "86400"))
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError()
        observed = path.stat().st_mtime
        if status_file:
            state = json.loads(Path(status_file).expanduser().read_text(encoding="utf-8"))
            if state.get("status") != "ok" or state.get("mirror_only_no_queue_replay") is not True:
                raise ValueError()
            generation = state.get("generation")
            if not isinstance(generation, str) or path.parent.parent.name != generation:
                raise HistoryUnavailable("HISTORY_GENERATION_MISMATCH")
            observed = float(state["source_observed_at"])
            verified = float(state["verified_at"])
            if not math.isfinite(verified) or verified < observed or verified > time.time() + 300:
                raise ValueError()
        age = time.time() - observed
        if not math.isfinite(observed) or age > max_age or age < -300:
            raise HistoryUnavailable("HISTORY_STALE")
        # Published generations are standalone snapshots, not live WAL databases.
        wal = Path(str(path) + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise HistoryUnavailable("HISTORY_SNAPSHOT_UNSAFE")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HistoryUnavailable("HISTORY_STATUS_UNAVAILABLE") from None
    return path


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def read_history(active_path, tables):
    """Yield a RO connection and CTE prefix (read_jobs, read_performance, ...).

    Resolve a published mirror generation once per operation. Active records win
    before any caller filters or limit; mirror AUTOINCREMENT IDs remain local.
    """
    if not tables or any(table not in _KEYS for table in tables):
        raise HistoryUnavailable("HISTORY_SCHEMA_UNAVAILABLE")
    active = _resolved_file(active_path)
    mirror = _mirror_path()
    if mirror == active:
        raise HistoryUnavailable("HISTORY_SNAPSHOT_UNSAFE")
    conn = None
    try:
        # Do not let a read-only active WAL open create missing shared-memory files.
        wal = Path(str(active) + "-wal")
        if wal.exists() and wal.stat().st_size and not Path(str(active) + "-shm").exists():
            raise HistoryUnavailable("HISTORY_SNAPSHOT_UNSAFE")
        conn = sqlite3.connect(active.as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        if mirror is not None:
            conn.execute("ATTACH DATABASE ? AS history", (mirror.as_uri() + "?mode=ro&immutable=1",))
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        ctes = []
        for table in tables:
            columns = [row[1] for row in conn.execute(f"PRAGMA main.table_info({_quote(table)})")]
            if not columns or not set(_KEYS[table]).issubset(columns):
                raise HistoryUnavailable("HISTORY_SCHEMA_UNAVAILABLE")
            projection = ", ".join(_quote(c) for c in columns)
            sql = f"read_{table} AS (SELECT {projection} FROM main.{table}"
            if mirror is not None:
                old_columns = {row[1] for row in conn.execute(f"PRAGMA history.table_info({_quote(table)})")}
                if not set(columns).issubset(old_columns):
                    raise HistoryUnavailable("HISTORY_SCHEMA_UNAVAILABLE")
                same = " AND ".join(f"a.{_quote(k)} = m.{_quote(k)}" for k in _KEYS[table])
                old_projection = ", ".join("m." + _quote(c) for c in columns)
                sql += (f" UNION ALL SELECT {old_projection} FROM history.{table} m"
                        f" WHERE NOT EXISTS (SELECT 1 FROM main.{table} a WHERE {same})")
            ctes.append(sql + ")")
        yield conn, "WITH " + ", ".join(ctes) + " "
    except sqlite3.Error:
        raise HistoryUnavailable("HISTORY_SCHEMA_UNAVAILABLE") from None
    except OSError:
        raise HistoryUnavailable("HISTORY_DB_UNAVAILABLE") from None
    finally:
        if conn is not None:
            conn.close()
