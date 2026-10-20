"""仅固定内部制作的一条 jobs UPDATE；主库 trigger/hold 不修改。"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

JOB = "f8bb617683914cbe"
TRIGGERS = (
    ("media_hold_delivery", "delivery_queue", "CREATE TRIGGER media_hold_delivery BEFORE UPDATE OF state ON delivery_queue\n      WHEN EXISTS(SELECT 1 FROM media_migration_effect_hold h WHERE h.table_name='delivery_queue' AND h.row_id=OLD.id)\n      BEGIN SELECT RAISE(ABORT,'historical_delivery_frozen_no_replay'); END"),
    ("media_hold_job_state", "jobs", "CREATE TRIGGER media_hold_job_state BEFORE UPDATE OF state,lease_owner,lease_expires_at ON jobs\n      WHEN EXISTS(SELECT 1 FROM media_migration_hold h WHERE h.job_id=OLD.id)\n      BEGIN SELECT RAISE(ABORT,'historical_job_frozen_no_replay'); END"),
    ("media_hold_schedule", "schedules", "CREATE TRIGGER media_hold_schedule BEFORE UPDATE OF enabled ON schedules\n      WHEN EXISTS(SELECT 1 FROM media_migration_effect_hold h WHERE h.table_name='schedules' AND h.row_id=OLD.id)\n      BEGIN SELECT RAISE(ABORT,'historical_schedule_frozen_no_replay'); END"),
)
CLAIM_SQL = "UPDATE jobs SET state=?,lease_owner=?,lease_expires_at=?,attempts=attempts+1,updated_at=? WHERE id=? AND state IN (?) AND (lease_owner='' OR lease_expires_at<=? OR lease_owner=?)"
RELEASE_SQL = "UPDATE jobs SET state=?,lease_owner='',lease_expires_at='',last_error=?,updated_at=? WHERE id=? AND lease_owner=?"
RELEASE_EVENTS = {"review_required": "review_requested", "blocked": "workflow_blocked", "failed": "generation_failed"}


def _grant(store):
    grant = getattr(store, "_migration_internal_make", None)
    if (not isinstance(grant, dict) or grant.get("job_id") != JOB
            or grant.get("store_identity") != id(store) or grant.get("pid") != os.getpid()
            or grant.get("thread_id") != threading.get_ident() or os.geteuid() != 0
            or not 0 < grant.get("expires_at", 0) - time.time() <= 1800):
        raise PermissionError("fixed_internal_dml_context_required")
    from .review import ReviewTokens
    if type(grant.get("policy")) is not ReviewTokens:
        raise PermissionError("fixed_internal_dml_native_policy_required")
    verified = grant["policy"].verify(grant["token"], "internal_make")
    if verified.get("job_id") != JOB or verified.get("nonce") != grant.get("nonce"):
        raise PermissionError("fixed_internal_dml_signature_scope_changed")
    return grant


def execute_fixed_internal_dml(store, conn, mode, sql, args, *, event=None):
    """不 yield 连接；关闭 main trigger 期间仅执行这条固定 SQL。"""
    grant = _grant(store)
    if not conn.in_transaction or sqlite3.sqlite_version_info < (3, 35, 0):
        raise PermissionError("fixed_internal_dml_transaction_or_sdk_invalid")
    databases = [row[1] for row in conn.execute("PRAGMA database_list")]
    if "main" not in databases or any(name not in {"main", "temp"} for name in databases):
        raise PermissionError("fixed_internal_dml_attached_database_forbidden")
    actual = tuple(tuple(row) for row in conn.execute("SELECT name,tbl_name,sql FROM main.sqlite_schema WHERE type='trigger' ORDER BY name"))
    if actual != TRIGGERS or not conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER):
        raise PermissionError("fixed_internal_dml_original_trigger_changed")
    if conn.execute("SELECT 1 FROM temp.sqlite_schema LIMIT 1").fetchone():
        raise PermissionError("fixed_internal_dml_existing_temp_schema_forbidden")
    if " ".join(sql.split()) != (CLAIM_SQL if mode == "claim" else RELEASE_SQL if mode == "release" else None):
        raise PermissionError("fixed_internal_dml_exact_statement_required")
    hold = conn.execute("SELECT original_state FROM main.media_migration_hold WHERE job_id=?", (JOB,)).fetchone()
    old = conn.execute("SELECT * FROM main.jobs WHERE id=?", (JOB,)).fetchone()
    if not old or not hold or hold[0] != "created":
        raise PermissionError("fixed_internal_dml_original_hold_required")
    columns, before = tuple(old.keys()), tuple(old)
    expected = dict(old)
    if mode == "claim":
        if (grant.get("claimed") or len(args) != 8 or args[0] != "generating" or not args[1]
                or args[4:] != (JOB, "created", args[3], args[1])
                or hashlib.sha256(json.dumps(dict(old), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != "3594cc2a59e9f3f84cee8fd13fffd44f53182828344bea3107eaf84423954416"):
            raise PermissionError("fixed_internal_dml_claim_boundary_invalid")
        stamp, expiry = datetime.fromisoformat(args[3]), datetime.fromisoformat(args[2])
        if (stamp.tzinfo != timezone.utc or expiry.tzinfo != timezone.utc
                or stamp.isoformat(timespec="seconds") != args[3]
                or expiry.isoformat(timespec="seconds") != args[2]
                or not 0 < expiry.timestamp() - time.time() <= 900
                or not 900 <= (expiry - stamp).total_seconds() <= 901
                or not -2 <= stamp.timestamp() - time.time() <= 0):
            raise PermissionError("fixed_internal_dml_native_900_lease_required")
        expected.update(state=args[0], lease_owner=args[1], lease_expires_at=args[2], attempts=1, updated_at=args[3])
        writable = {"state", "lease_owner", "lease_expires_at", "attempts", "updated_at"}
    else:
        if (not grant.get("claimed") or grant.get("released") or len(args) != 5
                or args[0] not in RELEASE_EVENTS or event != RELEASE_EVENTS[args[0]]
                or args[3:] != (JOB, grant.get("claim_owner")) or old["state"] != "generating"
                or old["attempts"] != 1 or old["lease_owner"] != grant.get("claim_owner")
                or old["lease_expires_at"] != grant.get("claim_expires")):
            raise PermissionError("fixed_internal_dml_release_boundary_invalid")
        expected.update(state=args[0], lease_owner="", lease_expires_at="", last_error=args[1], updated_at=args[2])
        writable = {"state", "lease_owner", "lease_expires_at", "last_error", "updated_at"}
    after = tuple(expected[column] for column in columns)
    used = 0

    def exact_row(*values):
        nonlocal used
        try:
            if _grant(store) is grant and used == 0 and values == before + after:
                used += 1
                return 1
        except (ValueError, PermissionError):
            pass
        return 0

    writes = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_UPDATE,
              sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA,
              sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
              sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_TRIGGER,
              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_TABLE,
              sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TEMP_TABLE, sqlite3.SQLITE_ALTER_TABLE}

    def authorize(action, table, column, database, source):
        if action not in writes:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_UPDATE and database == "main" and table == "jobs" and column in writable and source is None:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    names = ["fixed_internal_" + row[0] for row in TRIGGERS]
    conn.create_function("fixed_internal_exact_row", len(columns) * 2, exact_row)
    try:
        for name, (_, table, ddl) in zip(names, TRIGGERS):
            if table == "jobs":
                values = ",".join(side + '."' + column + '"' for side in ("OLD", "NEW") for column in columns)
                temporary = (f"CREATE TEMP TRIGGER {name} BEFORE UPDATE ON main.jobs "
                             "WHEN EXISTS(SELECT 1 FROM main.media_migration_hold h WHERE h.job_id=OLD.id) "
                             f"AND fixed_internal_exact_row({values}) != 1 "
                             "BEGIN SELECT RAISE(ABORT,'historical_job_frozen_no_replay'); END")
            else:
                temporary = ddl.replace("CREATE TRIGGER " + ddl.split()[2], "CREATE TEMP TRIGGER " + name, 1).replace(" ON " + table, " ON main." + table, 1)
            conn.execute(temporary)
        conn.set_authorizer(authorize)
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        cursor = conn.execute(sql, args)
        if cursor.rowcount != 1 or used != 1:
            raise PermissionError("fixed_internal_dml_single_row_required")
        return cursor
    finally:
        try:
            conn.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)
            if not conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER):
                raise PermissionError("fixed_internal_dml_trigger_restore_failed")
        except BaseException:
            conn.close()
            raise
        conn.set_authorizer(None)
        for name in names:
            conn.execute("DROP TRIGGER IF EXISTS temp." + name)
        conn.create_function("fixed_internal_exact_row", len(columns) * 2, None)
