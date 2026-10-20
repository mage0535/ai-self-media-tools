"""固定F8已知来源BLOCKED的一次原阶段修复，复用原native签名key。"""
import base64
import contextlib
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time
from datetime import datetime, timedelta, timezone

JOB = "f8bb617683914cbe"
WF = "wf_" + JOB
SOURCE = "collect_native_source_inputs"
ALIAS = SOURCE + "__root_source_repair"
JOB_ROW_SHA = "d8112b45e07601aac7ab3c6f589356437c3421e115c915b16b8e000c32453b56"
HOLD_SHA = "3ebf1816aeb694a90d1094d34115ed0c455fd3a58d6db603dd00aa1a3995c2b5"
STEP_PINS = {
    5212: "9a09f8999118bce5c0df06dbfc89282e5e813754fb7a0273e02b035a75ac44d1",
    5213: "f1a7542d68ae5fe664b2c6b153e23cbdd4c16ec36ab4354c39c6822cd947b386",
    5214: "c1afc4c1eebd977ce9f8ba00a793eeab205246ae20a6af0eed391bde199cf2be",
}
MAIN_SHA = "2c1874a581be2f5a42853e4f4b7ed6bf3e2aa8966bb5593f59e65c9e4ab00a59"
COLLECTOR_SHA = "75062890a5ab99a9dc11b220385bb34e94a0fddcde7110980116acc0b2050e08"
EFFECTS = ("artifacts", "approvals", "deliveries", "delivery_queue", "platform_outputs", "source_items", "gate_results", "review_tasks", "delivery_intents", "publish_receipts")
PRIOR_PINS = {
    "outer_intent": "5e64148f175cd6d0fb4753f9f28a322532d348a8fcdc4b066b90f6e0f07f00d3",
    "intent": "aefea30d508b4dd1549c8021ed85c9a9abaf0041f16f125a378a4671ec35fbe7",
    "completed": "a0031fabfc8781e29e5417c33414c22faf4d7f0bd22e1d8b410a001c0658da29",
    "native_result": "e764aa8fc0898e60a57123333e3fe3582e4cf35eff16124c49419b8da22f00dd",
    "outer": "b149d7c4b46c70a7ac5c0904ba073fd6f14aa89185a6e2937fd56b86313da742",
}
RECEIPT_PINS = {"authentication": "b056c2f11dd8f4b36eef70d8419a8007ae2de7a2a08edde397efad79e0524af6",
                "old_main_restore": "70f6dd4c5f055e05a0ad7a9bff5322e30a76097ff3ac2784aa21ea631fe947d3",
                "new_main_restore": "42c19b0f842262a5e17d96d656b2fed2a06bb306d2474d91ff5d236cb4f107be"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value): return hashlib.sha256(encoded(value)).hexdigest()
def raw_hash(value): return hashlib.sha256(value).hexdigest()


def current_source_sha(path):
    return raw_hash(private_bytes(path))


def private_bytes(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or (os.name == "posix" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077)):
        raise PermissionError("root_private_source_repair_entity_required")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream: return stream.read()


def signed_record(policy, domain, value):
    payload = dict(value)
    signature = hmac.new(policy._key(), domain.encode() + b"\n" + encoded(payload), hashlib.sha256).hexdigest()
    return {"payload": payload, "signature": signature}


def read_signed(policy, domain, record):
    if not isinstance(record, dict) or set(record) != {"payload", "signature"}:
        raise PermissionError("actual_source_repair_signature_record_required")
    expected = signed_record(policy, domain, record["payload"])["signature"]
    if not hmac.compare_digest(expected, record["signature"]):
        raise PermissionError("actual_source_repair_hmac_invalid")
    return record["payload"]


def check_original_rows(conn, evidence):
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (JOB,)).fetchone()
    hold = conn.execute("SELECT * FROM media_migration_hold WHERE job_id=?", (JOB,)).fetchone()
    if not row or not hold or digest(dict(hold)) != evidence["hold_sha256"]:
        raise PermissionError("source_repair_original_hold_changed")
    steps = [dict(v) for v in conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND id IN (5212,5213,5214) ORDER BY id", (JOB,))]
    if len(steps) != 3 or {v["id"]: digest(v) for v in steps} != STEP_PINS:
        raise PermissionError("source_repair_three_original_rows_changed")
    if conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_history_reobserve_registered'", (JOB,)).fetchone():
        old = conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND id=5216", (JOB,)).fetchone()
        if not old or digest(dict(old)) != "f1fb8aba6ba3ab69fb2c73283afd84639706a50e52158756377a5de0551272df":
            raise PermissionError("original_failed_history_source_alias_changed")
    return dict(row), steps


def load_evidence(store, path, pin, *, initial=True):
    raw = private_bytes(path)
    if raw_hash(raw) != pin: raise PermissionError("source_repair_evidence_sha_changed")
    evidence = json.loads(raw)
    if (evidence.get("schema") != "fixed-f8-known-source-blocked-repair-v1" or evidence.get("job_id") != JOB
            or evidence.get("workflow_id") != WF or evidence.get("attempts") != 1
            or evidence.get("effect_unknown") is not False or evidence.get("approval_or_publication_authorized") is not False
            or evidence.get("renderer_budget_seconds") != 900 or evidence.get("main_sha256") != MAIN_SHA
            or evidence.get("collector_sha256") != COLLECTOR_SHA or evidence.get("job_row_sha256") != JOB_ROW_SHA
            or evidence.get("hold_sha256") != HOLD_SHA or evidence.get("remaining_budget_seconds") != 1798):
        raise PermissionError("fixed_known_source_repair_scope_required")
    prior = evidence["prior_native"]
    if {name: record.get("sha256") for name, record in prior.items()} != PRIOR_PINS:
        raise PermissionError("exact_original_native_execution_receipts_required")
    files = {name: json.loads(private_bytes(record["path"])) for name, record in prior.items()}
    if any(raw_hash(private_bytes(record["path"])) != record["sha256"] for record in prior.values()):
        raise PermissionError("actual_prior_native_entity_changed")
    intent, completed, outer = files["intent"], files["completed"], files["outer"]
    elapsed = float(outer["finished_at_unix"]) - float(files["outer_intent"]["started_at_unix"])
    remaining = 1800 - math.ceil(elapsed)
    if (not math.isfinite(elapsed) or elapsed <= 0 or completed.get("same_original_job") != JOB
            or completed.get("state") != "blocked" or completed.get("attempts") != 1
            or outer.get("unknown_effect") is not False or remaining != 1798
            or evidence.get("remaining_budget_seconds") != remaining):
        raise PermissionError("actual_source_repair_remaining_budget_invalid")
    native = files["native_result"]
    if native.get("id") != JOB or native.get("state") != "blocked" or native.get("attempts") != 1:
        raise PermissionError("actual_known_source_blocked_result_required")
    # 每项来自实际Root闭合只读证，不接受布尔通过替代实体SHA。
    for name, record in evidence["source_repair_receipts"].items():
        data = private_bytes(record["path"])
        if raw_hash(data) != record["sha256"]:
            raise PermissionError("actual_source_repair_receipt_changed:" + name)
    required = {"authentication", "old_main_restore", "new_main_restore"}
    if (set(evidence["source_repair_receipts"]) != required
            or {name: record.get("sha256") for name,record in evidence["source_repair_receipts"].items()} != RECEIPT_PINS):
        raise PermissionError("actual_source_auth_and_dual_restore_receipts_required")
    restored = {name: json.loads(private_bytes(record["path"])) for name, record in evidence["source_repair_receipts"].items()}
    authentication = restored["authentication"]
    if (authentication.get("job_id") != JOB or authentication.get("current_account_result_one") is not True
            or authentication.get("current_account_identity_matches_source") is not True
            or authentication.get("source_qualification_complete") is not True
            or authentication.get("status") != "backend_signal" or authentication.get("account_metrics") != {"works": 4}
            or authentication.get("metric_metadata", {}).get("metric_scope") != "account_snapshot"
            or authentication.get("metric_metadata", {}).get("strategy_eligible") is not False
            or authentication.get("source_identity_sha256") != restored["new_main_restore"].get("source_identity_sha256")):
        raise PermissionError("actual_same_account_current_backend_source_required")
    if evidence.get("authentication_observed_at_unix") != authentication.get("collected_at_unix"):
        raise PermissionError("actual_authentication_source_date_binding_required")
    for name in ("old_main_restore", "new_main_restore"):
        receipt = restored[name]
        if (receipt.get("schema") != "same-account-main-fresh-session-consumer-cas-r5-v1"
                or receipt.get("same_original_f8") != JOB or receipt.get("main_after_sha256") != MAIN_SHA
                or receipt.get("before_restore_verified") is not True
                or receipt.get("original_magic_unchanged") is not True
                or receipt.get("f8_and_original_failure_rows_unchanged") is not True):
            raise PermissionError("actual_dual_main_restore_scope_invalid")
    if restored["old_main_restore"].get("source_identity_sha256") != restored["new_main_restore"].get("source_identity_sha256"):
        raise PermissionError("actual_dual_main_uid_mismatch")
    if current_source_sha(evidence["main_path"]) != MAIN_SHA or current_source_sha(evidence["collector_path"]) != COLLECTOR_SHA:
        raise PermissionError("current_actual_main_collector_binding_changed")
    with store.connect() as conn:
        row, steps = check_original_rows(conn, evidence)
        if initial:
            if (digest(row) != evidence["job_row_sha256"] or row["state"] != "blocked" or row["attempts"] != 1
                    or row["lease_owner"] or row["lease_expires_at"]
                    or steps[2]["step_name"] != SOURCE or steps[2]["status"] != "BLOCKED"
                    or steps[2]["reason_code"] != "source_account_data_unavailable"):
                raise PermissionError("known_original_source_blocked_checkpoint_changed")
            all_steps = conn.execute("SELECT count(*) FROM workflow_steps WHERE job_id=?", (JOB,)).fetchone()[0]
            if all_steps != 3 or any(conn.execute("SELECT 1 FROM " + table + " WHERE job_id=? LIMIT 1", (JOB,)).fetchone() for table in EFFECTS):
                raise PermissionError("source_repair_downstream_existing_or_unknown_effect")
    return evidence


def issue_source_repair(store, policy, evidence_path, evidence_sha256):
    from .review import ReviewTokens
    if os.geteuid() != 0 or type(policy) is not ReviewTokens or policy.key_path.resolve() != (store.path.parent / "review.key").resolve() or not policy.key_path.is_file():
        raise PermissionError("root_existing_native_source_repair_key_required")
    evidence = load_evidence(store, evidence_path, evidence_sha256)
    with store.connect() as conn:
        if conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_repair_registered' LIMIT 1", (JOB,)).fetchone():
            raise PermissionError("original_source_repair_already_consumed")
    now = time.time()
    payload = {"action": "source_repair", "job_id": JOB, "workflow_id": WF, "attempts": 1, "nonce": os.urandom(16).hex(),
               "evidence_sha256": evidence_sha256, "remaining_budget_seconds": evidence["remaining_budget_seconds"], "exp": int(now) + evidence["remaining_budget_seconds"]}
    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    token = body + "." + b64(hmac.new(policy._key(), body.encode(), hashlib.sha256).digest())
    record = {"token_sha256": raw_hash(token.encode()), "evidence_sha256": evidence_sha256, "job_id": JOB, "remaining_budget_seconds": payload["remaining_budget_seconds"]}
    destination = Path(evidence_path).parent / "SOURCE-REPAIR-TOKEN-REGISTRATION.private.json"
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream: stream.write(encoded(record) + b"\n"); stream.flush(); os.fsync(stream.fileno())
    return token


def active_grant(store):
    grant = getattr(store, "_root_source_repair", None)
    if (not isinstance(grant, dict) or grant.get("store_identity") != id(store) or grant.get("pid") != os.getpid()
            or grant.get("thread_id") != threading.get_ident() or os.geteuid() != 0
            or not 0 < grant.get("expires_at", 0) - time.time() <= grant.get("remaining_budget_seconds", 0)):
        raise PermissionError("actual_same_store_source_repair_scope_required")
    payload = grant["policy"].verify(grant["token"], grant.get("action", "source_repair"))
    if payload.get("evidence_sha256") != grant["evidence_sha256"] or payload.get("nonce") != grant["nonce"]:
        raise PermissionError("actual_source_repair_token_scope_changed")
    return grant


def state_update(store, conn, sql, args, expected):
    from .migration_internal_dml import TRIGGERS
    grant = active_grant(store)
    databases = [v[1] for v in conn.execute("PRAGMA database_list")]
    if not conn.in_transaction or any(v not in {"main", "temp"} for v in databases):
        raise PermissionError("source_repair_local_transaction_main_only")
    if tuple(tuple(v) for v in conn.execute("SELECT name,tbl_name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY name")) != TRIGGERS:
        raise PermissionError("actual_original_three_main_triggers_changed")
    if not conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER) or conn.execute("SELECT 1 FROM temp.sqlite_schema LIMIT 1").fetchone():
        raise PermissionError("source_repair_original_trigger_on_empty_temp_required")
    before = conn.execute("SELECT * FROM jobs WHERE id=?", (JOB,)).fetchone()
    columns = tuple(before.keys()); old = tuple(before); new = tuple(expected[k] for k in columns); used = 0
    def exact(*values):
        nonlocal used
        try:
            if active_grant(store) is grant and used == 0 and values == old + new:
                used += 1; return 1
        except PermissionError: pass
        return 0
    names = ["source_repair_" + name for name, _, _ in TRIGGERS]
    conn.create_function("source_repair_exact_row", len(columns) * 2, exact)
    try:
        for temp, (name, table, ddl) in zip(names, TRIGGERS):
            if table == "jobs":
                values = ",".join(side + '."' + k + '"' for side in ("OLD", "NEW") for k in columns)
                temporary = f"CREATE TEMP TRIGGER {temp} BEFORE UPDATE ON main.jobs WHEN EXISTS(SELECT 1 FROM main.media_migration_hold h WHERE h.job_id=OLD.id) AND source_repair_exact_row({values})!=1 BEGIN SELECT RAISE(ABORT,'historical_job_frozen_no_replay'); END"
            else:
                temporary = ddl.replace("CREATE TRIGGER " + name, "CREATE TEMP TRIGGER " + temp, 1).replace(" ON " + table, " ON main." + table, 1)
            conn.execute(temporary)
        conn.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        cursor = conn.execute(sql, args)
        if cursor.rowcount != 1 or used != 1: raise PermissionError("source_repair_exact_single_state_transition_required")
    finally:
        try: conn.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)
        except BaseException: conn.close(); raise
        for name in names: conn.execute("DROP TRIGGER IF EXISTS temp." + name)
        conn.create_function("source_repair_exact_row", len(columns) * 2, None)


@contextlib.contextmanager
def authorized_source_repair(store, policy, token, evidence_path, evidence_sha256, owner):
    evidence = load_evidence(store, evidence_path, evidence_sha256)
    from .review import ReviewTokens
    if (os.geteuid() != 0 or type(policy) is not ReviewTokens or not owner
            or policy.key_path.resolve() != (store.path.parent / "review.key").resolve()
            or not policy.key_path.is_file() or getattr(store, "_root_source_repair", None) is not None):
        raise PermissionError("root_single_native_source_repair_context_required")
    payload = policy.verify(token, "source_repair")
    remaining = evidence["remaining_budget_seconds"]
    if (payload.get("job_id") != JOB or payload.get("workflow_id") != WF or payload.get("attempts") != 1
            or payload.get("evidence_sha256") != evidence_sha256 or payload.get("remaining_budget_seconds") != remaining
            or not 0 < payload.get("exp", 0) - time.time() <= remaining
            or not isinstance(payload.get("nonce"), str) or len(payload["nonce"]) != 32):
        raise PermissionError("fixed_source_repair_signature_scope_or_budget_invalid")
    grant = {"policy": policy, "token": token, "nonce": payload["nonce"], "evidence": evidence, "evidence_sha256": evidence_sha256,
             "store_identity": id(store), "pid": os.getpid(), "thread_id": threading.get_ident(), "expires_at": payload["exp"],
             "remaining_budget_seconds": remaining, "owner": owner}
    store._root_source_repair = grant
    admitted = False
    try:
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row, steps = check_original_rows(conn, evidence)
            if digest(row) != evidence["job_row_sha256"] or conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_repair_registered' LIMIT 1", (JOB,)).fetchone():
                raise PermissionError("source_repair_last_checkpoint_cas_or_once_consumed")
            if (conn.execute("SELECT count(*) FROM workflow_steps WHERE job_id=?", (JOB,)).fetchone()[0] != 3
                    or any(conn.execute("SELECT 1 FROM " + table + " WHERE job_id=? LIMIT 1", (JOB,)).fetchone() for table in EFFECTS)):
                raise PermissionError("source_repair_last_effect_free_checkpoint_changed")
            lease = min(900, math.floor(payload["exp"] - time.time()))
            if lease <= 0: raise PermissionError("source_repair_budget_exhausted")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            expires = (datetime.now(timezone.utc) + timedelta(seconds=lease)).isoformat(timespec="seconds")
            updated = dict(row, state="generating", lease_owner=owner, lease_expires_at=expires, updated_at=now)
            record = signed_record(policy, "source_repair_registered_v1", {"job_id": JOB, "workflow_id": WF, "attempts": 1,
                     "evidence_sha256": evidence_sha256, "original_step_pins": {str(k): v for k,v in STEP_PINS.items()}, "alias": ALIAS,
                     "token_sha256": raw_hash(token.encode()), "nonce_sha256": raw_hash(payload["nonce"].encode()), "remaining_budget_seconds": remaining,
                     "publication_authorized": False, "approval_authorized": False})
            store._event(conn, JOB, "root_source_repair_registered", record)
            state_update(store, conn, "UPDATE jobs SET state=?,lease_owner=?,lease_expires_at=?,updated_at=? WHERE id=? AND state='blocked' AND attempts=1 AND lease_owner='' AND lease_expires_at=''", ("generating", owner, expires, now, JOB), updated)
            grant["lease_expires_at"] = expires
        admitted = True
        yield evidence
    finally:
        if getattr(store, "_root_source_repair", None) is grant: del store._root_source_repair
        if admitted:
            store.record_event(JOB, "root_source_repair_scope_closed", {"original_hold_kept": True, "original_failure_preserved": True, "approval_or_publication_authorized": False})


def release_source_repair(store, job_id, owner, new_state, event, error="", detail=None):
    grant = active_grant(store)
    events = {"review_required": "review_requested", "blocked": "workflow_blocked", "failed": "generation_failed"}
    if job_id != JOB or owner != grant["owner"] or events.get(new_state) != event:
        raise PermissionError("source_repair_release_scope_invalid")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row, _ = check_original_rows(conn, grant["evidence"])
        if row["state"] != "generating" or row["attempts"] != 1 or row["lease_owner"] != owner or row["lease_expires_at"] != grant["lease_expires_at"]:
            raise PermissionError("source_repair_release_owner_or_row_changed")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        updated = dict(row, state=new_state, lease_owner="", lease_expires_at="", last_error=str(error), updated_at=now)
        state_update(store, conn, "UPDATE jobs SET state=?,lease_owner='',lease_expires_at='',last_error=?,updated_at=? WHERE id=? AND lease_owner=? AND state='generating' AND attempts=1", (new_state, str(error), now, JOB, owner), updated)
        store._event(conn, JOB, event, detail or {"error": str(error)})
    return store.get_job(JOB)


def record_source_repair_success(store):
    grant = active_grant(store)
    with store.connect() as conn:
        _, original = check_original_rows(conn, grant["evidence"])
        actual_alias = grant.get("alias", ALIAS)
        rows = conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND workflow_id=? AND step_name=?", (JOB, WF, actual_alias)).fetchall()
        if len(rows) != 1 or rows[0]["status"] != "SUCCEEDED": raise PermissionError("actual_source_repair_alias_output_required")
        row = dict(rows[0]); output = json.loads(row["output_json"])
        record = signed_record(grant["policy"], "source_repair_success_v1", {"job_id": JOB, "workflow_id": WF, "attempts": 1,
                 "evidence_sha256": grant["evidence_sha256"], "original_step_id": 5214, "original_step_sha256": STEP_PINS[5214],
                 "alias_step_id": row["id"], "alias_step_name": actual_alias, "alias_step_sha256": digest(row), "output_sha256": digest(output)})
        store._event(conn, JOB, "root_source_repair_succeeded", record)


def resolve_source_repair_step(store, job_id, name):
    if job_id != JOB or name != SOURCE: raise ValueError("source_repair_mapping_scope_invalid")
    from .review import ReviewTokens
    policy = ReviewTokens(store.path.parent / "review.key")
    if not policy.key_path.is_file(): raise PermissionError("existing_native_key_required_for_actual_alias")
    with store.connect() as conn:
        originals = [dict(v) for v in conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND id IN (5212,5213,5214) ORDER BY id", (JOB,))]
        if {v["id"]: digest(v) for v in originals} != STEP_PINS: raise PermissionError("original_failed_source_rows_not_preserved")
        events = {name: [json.loads(v[0]) for v in conn.execute("SELECT detail_json FROM events WHERE job_id=? AND event=?", (JOB, name))] for name in ["root_source_repair_registered", "root_source_repair_succeeded"]}
        if len(events["root_source_repair_registered"]) != 1 or len(events["root_source_repair_succeeded"]) != 1:
            raise ValueError("actual_unique_signed_source_repair_success_required")
        registration = read_signed(policy, "source_repair_registered_v1", events["root_source_repair_registered"][0])
        receipt = read_signed(policy, "source_repair_success_v1", events["root_source_repair_succeeded"][0])
        if (registration.get("job_id") != JOB or registration.get("workflow_id") != WF or registration.get("attempts") != 1
                or registration.get("alias") != ALIAS or registration.get("original_step_pins") != {str(k):v for k,v in STEP_PINS.items()}
                or receipt.get("evidence_sha256") != registration.get("evidence_sha256") or receipt.get("job_id") != JOB or receipt.get("workflow_id") != WF):
            raise PermissionError("actual_source_repair_registered_mapping_mismatch")
        actual_alias = ALIAS
        history_rows = conn.execute("SELECT detail_json FROM events WHERE job_id=? AND event='root_source_history_reobserve_registered'", (JOB,)).fetchall()
        if history_rows:
            if len(history_rows) != 1: raise PermissionError("unique_history_source_signature_required")
            history = read_signed(policy, "source_history_reobserve_registered_v1", json.loads(history_rows[0][0]))
            if (history.get("job_id") != JOB or history.get("workflow_id") != WF or history.get("attempts") != 1
                    or history.get("evidence_sha256") != receipt.get("evidence_sha256") or history.get("readonly_reobservation_authorized") is not True
                    or history.get("alias") != "collect_native_source_inputs__root_history_reobserve"
                    or history.get("old_failed_alias_sha256") != "f1fb8aba6ba3ab69fb2c73283afd84639706a50e52158756377a5de0551272df"
                    or history.get("remaining_budget_seconds") != 1748 or history.get("approval_authorized") is not False or history.get("publication_authorized") is not False):
                raise PermissionError("actual_signed_history_alias_mapping_mismatch")
            old = conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND id=5216", (JOB,)).fetchone()
            if not old or digest(dict(old)) != history["old_failed_alias_sha256"]: raise PermissionError("old_failed_alias_not_preserved")
            actual_alias = history["alias"]
        if receipt.get("alias_step_name") != actual_alias: raise PermissionError("signed_alias_name_mismatch")
        row = conn.execute("SELECT * FROM workflow_steps WHERE job_id=? AND workflow_id=? AND id=? AND step_name=?", (JOB, WF, receipt["alias_step_id"], actual_alias)).fetchone()
        if not row or row["status"] != "SUCCEEDED" or digest(dict(row)) != receipt["alias_step_sha256"]:
            raise PermissionError("actual_source_repair_alias_row_changed")
        value = json.loads(row["output_json"])
        if digest(value) != receipt["output_sha256"]: raise PermissionError("actual_source_repair_alias_output_changed")
    return value, {"id": row["id"], "step_name": actual_alias, "logical_step_name": SOURCE, "output_sha256": digest(value), "finished_at": row["finished_at"],
                   "original_failure_id": 5214, "original_failure_sha256": STEP_PINS[5214], "source_repair_evidence_sha256": receipt["evidence_sha256"]}


# 唯一已知前Source KeyError接续；原登记、scopeClosed、原红行与原lease不删除。
CONTINUE_ROW_SHA = "5061c5c0a5571d48904be0e169fc112503d430cd0c0ffaa5836b967324930c0c"
CONTINUE_OWNER = "48664-15068893"
CONTINUE_LEASE = "2026-10-11T15:37:49+00:00"
CONTINUE_EVENT_PINS = {"root_source_repair_registered": "6f0e3d6f95be4d6546028f35e1dee20e3687f087cda1f55c075ceba46e083162",
                       "root_source_repair_scope_closed": "d4439cfc34c9e31d3577d1b3d45ab74e019a387e4c269ea439da52e983eba040"}
CONTINUE_ENTITY_PINS = {"SOURCE-REPAIR-RUN-INTENT.private.json": "2d371ef9513116845b5adb75bb9b34bcd9f2518eb56c02ed2c67d5ca70f4c31a",
                        "SOURCE-REPAIR-TOKEN-REGISTRATION.private.json": "23dff6f81ff195aa3f68f24a676216f4fda790fbf151fe1f6404d7b15656d3f0",
                        "SOURCE-REPAIR-RUN-FAILURE.private.json": "6b7aa54fb1069e5f9090d6df16b610cbb9d67e657bdb2fcf21e00ab7c7a7f24a"}


def check_pre_source_continuation(store, policy, evidence_path, evidence_sha256, proof_path, proof_sha256):
    evidence = load_evidence(store, evidence_path, evidence_sha256, initial=False)
    raw = private_bytes(proof_path)
    if raw_hash(raw) != proof_sha256: raise PermissionError("actual_continuation_proof_changed")
    proof = json.loads(raw)
    if (proof.get("schema") != "same-f8-known-pre-source-keyerror-continuation-v1" or proof.get("job_id") != JOB or proof.get("workflow_id") != WF or proof.get("attempts") != 1
            or proof.get("prior_evidence_sha256") != evidence_sha256 or proof.get("current_row_sha256") != CONTINUE_ROW_SHA
            or proof.get("remaining_budget_seconds") != 1796 or proof.get("renderer_budget_seconds") != 900
            or proof.get("effect_unknown") is not False or proof.get("approval_or_publication_authorized") is not False
            or proof.get("unit_start_monotonic_us") != 1682501237411 or proof.get("unit_exit_monotonic_us") != 1682502320898):
        raise PermissionError("fixed_actual_pre_source_continuation_scope_required")
    elapsed = (proof["unit_exit_monotonic_us"] - proof["unit_start_monotonic_us"])/1000000
    if 1798 - math.ceil(elapsed) != proof["remaining_budget_seconds"]:
        raise PermissionError("actual_unit_exec_full_budget_deduction_required")
    entities = proof["prior_entities"]
    if {k:v.get("sha256") for k,v in entities.items()} != CONTINUE_ENTITY_PINS:
        raise PermissionError("exact_consumed_original_cap_and_failure_required")
    for record in entities.values():
        if raw_hash(private_bytes(record["path"])) != record["sha256"]:
            raise PermissionError("consumed_source_repair_original_entity_changed")
    failure = json.loads(private_bytes(entities["SOURCE-REPAIR-RUN-FAILURE.private.json"]["path"]))
    if (failure.get("error_type") != "KeyError" or not any(v.get("file")=="pipeline.py" and v.get("function")=="resume_source_blocked" and v.get("line")==552 for v in failure.get("safe_frames",[]))):
        raise PermissionError("only_actual_known_public_store_pre_source_failure_allowed")
    with store.connect() as conn:
        row, _ = check_original_rows(conn, evidence)
        if (digest(row) != CONTINUE_ROW_SHA or row["state"] != "generating" or row["attempts"] != 1
                or row["lease_owner"] != CONTINUE_OWNER or row["lease_expires_at"] != CONTINUE_LEASE):
            raise PermissionError("original_held_generating_root_owner_lease_cas_changed")
        if (conn.execute("SELECT count(*) FROM workflow_steps WHERE job_id=?",(JOB,)).fetchone()[0] != 3
                or any(conn.execute("SELECT 1 FROM " + table + " WHERE job_id=? LIMIT 1",(JOB,)).fetchone() for table in EFFECTS)
                or conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_repair_continuation_registered'",(JOB,)).fetchone()):
            raise PermissionError("pre_source_no_effect_or_continuation_once_gate_failed")
        originals = {}
        for name,pin in CONTINUE_EVENT_PINS.items():
            rows = conn.execute("SELECT * FROM events WHERE job_id=? AND event=?",(JOB,name)).fetchall()
            if len(rows)!=1 or digest(dict(rows[0]))!=pin: raise PermissionError("original_consumed_registration_scope_closed_changed")
            originals[name]=dict(rows[0])
        registration = read_signed(policy,"source_repair_registered_v1",json.loads(originals["root_source_repair_registered"]["detail_json"]))
        cap = json.loads(private_bytes(entities["SOURCE-REPAIR-TOKEN-REGISTRATION.private.json"]["path"]))
        if (registration.get("evidence_sha256")!=evidence_sha256 or registration.get("token_sha256")!=cap.get("token_sha256")
                or registration.get("job_id")!=JOB or registration.get("attempts")!=1
                or registration.get("approval_authorized") is not False or registration.get("publication_authorized") is not False):
            raise PermissionError("original_actual_root_authority_signature_chain_required")
    return evidence, proof


def issue_source_continuation(store, policy, evidence_path, evidence_sha256, proof_path, proof_sha256):
    from .review import ReviewTokens
    if os.geteuid()!=0 or type(policy) is not ReviewTokens or policy.key_path.resolve()!=(store.path.parent/"review.key").resolve() or not policy.key_path.is_file():
        raise PermissionError("existing_native_root_source_continuation_key_required")
    check_pre_source_continuation(store,policy,evidence_path,evidence_sha256,proof_path,proof_sha256)
    payload={"action":"source_repair_continue","job_id":JOB,"workflow_id":WF,"attempts":1,
             "evidence_sha256":evidence_sha256,"continuation_proof_sha256":proof_sha256,"remaining_budget_seconds":1796,
             "nonce":os.urandom(16).hex(),"exp":int(time.time())+1796}
    b64=lambda raw:base64.urlsafe_b64encode(raw).decode().rstrip("=")
    body=b64(json.dumps(payload,separators=(",",":")).encode());token=body+"."+b64(hmac.new(policy._key(),body.encode(),hashlib.sha256).digest())
    dest=Path(proof_path).parent/"SOURCE-REPAIR-CONTINUATION-TOKEN-REGISTRATION.private.json"
    fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:f.write(encoded({"job_id":JOB,"token_sha256":raw_hash(token.encode()),"continuation_proof_sha256":proof_sha256,"prior_failure_sha256":CONTINUE_ENTITY_PINS["SOURCE-REPAIR-RUN-FAILURE.private.json"],"remaining_budget_seconds":1796})+b"\n");f.flush();os.fsync(f.fileno())
    return token


@contextlib.contextmanager
def authorized_source_continuation(store, policy, token, evidence_path, evidence_sha256, proof_path, proof_sha256, owner):
    from .review import ReviewTokens
    if type(policy) is not ReviewTokens or policy.key_path.resolve()!=(store.path.parent/"review.key").resolve() or not policy.key_path.is_file():
        raise PermissionError("actual_native_root_continuation_policy_required")
    evidence,proof=check_pre_source_continuation(store,policy,evidence_path,evidence_sha256,proof_path,proof_sha256)
    payload=policy.verify(token,"source_repair_continue")
    if (os.geteuid()!=0 or getattr(store,"_root_source_repair",None) is not None or not owner
            or payload.get("job_id")!=JOB or payload.get("workflow_id")!=WF or payload.get("attempts")!=1
            or payload.get("evidence_sha256")!=evidence_sha256 or payload.get("continuation_proof_sha256")!=proof_sha256
            or payload.get("remaining_budget_seconds")!=1796 or not 0<payload.get("exp",0)-time.time()<=1796
            or not isinstance(payload.get("nonce"),str) or len(payload["nonce"])!=32):
        raise PermissionError("actual_root_continuation_scope_signature_budget_invalid")
    grant={"policy":policy,"token":token,"action":"source_repair_continue","nonce":payload["nonce"],"evidence":evidence,
           "evidence_sha256":evidence_sha256,"store_identity":id(store),"pid":os.getpid(),"thread_id":threading.get_ident(),
           "expires_at":payload["exp"],"remaining_budget_seconds":1796,"owner":owner}
    store._root_source_repair=grant;admitted=False
    try:
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE");row,_=check_original_rows(conn,evidence)
            if (digest(row)!=CONTINUE_ROW_SHA or conn.execute("SELECT count(*) FROM workflow_steps WHERE job_id=?",(JOB,)).fetchone()[0]!=3
                    or any(conn.execute("SELECT 1 FROM "+table+" WHERE job_id=? LIMIT 1",(JOB,)).fetchone() for table in EFFECTS)
                    or conn.execute("SELECT 1 FROM events WHERE job_id=? AND event='root_source_repair_continuation_registered'",(JOB,)).fetchone()):
                raise PermissionError("continuation_last_pre_source_no_effect_cas_or_once_changed")
            now=datetime.now(timezone.utc).isoformat(timespec="seconds")
            lease=min(900,math.floor(payload["exp"]-time.time()))
            if lease<=0:raise PermissionError("continuation_budget_exhausted")
            expires=(datetime.now(timezone.utc)+timedelta(seconds=lease)).isoformat(timespec="seconds")
            updated=dict(row,lease_owner=owner,lease_expires_at=expires,updated_at=now)
            record=signed_record(policy,"source_repair_continuation_registered_v1",{"job_id":JOB,"workflow_id":WF,"attempts":1,
                    "prior_failure_sha256":CONTINUE_ENTITY_PINS["SOURCE-REPAIR-RUN-FAILURE.private.json"],"continuation_proof_sha256":proof_sha256,
                    "evidence_sha256":evidence_sha256,"token_sha256":raw_hash(token.encode()),"remaining_budget_seconds":1796,
                    "original_owner":CONTINUE_OWNER,"original_lease":CONTINUE_LEASE,"approval_authorized":False,"publication_authorized":False})
            store._event(conn,JOB,"root_source_repair_continuation_registered",record)
            state_update(store,conn,"UPDATE jobs SET lease_owner=?,lease_expires_at=?,updated_at=? WHERE id=? AND state='generating' AND attempts=1 AND lease_owner=? AND lease_expires_at=?",(owner,expires,now,JOB,CONTINUE_OWNER,CONTINUE_LEASE),updated)
            grant["lease_expires_at"]=expires
        admitted=True;yield dict(evidence,remaining_budget_seconds=1796)
    finally:
        if getattr(store,"_root_source_repair",None) is grant:del store._root_source_repair
        if admitted:store.record_event(JOB,"root_source_repair_continuation_scope_closed",{"original_hold_kept":True,"original_failure_preserved":True,"approval_or_publication_authorized":False})
