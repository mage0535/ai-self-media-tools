"""绑定原 claim 前失败实体与当前零制作效果；不恢复旧 token。"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

JOB = "f8bb617683914cbe"
PRIOR = Path("/srv/hermes-worker/staging/media-f8-internal-make-r3-20261011-r1")
PINS = {
    "native-internal-make-failure.private.json": "be2e143a06beb6a32c601a13cf3b8bc879558f2b58286111e5b390e3aa9afda2",
    "F8-INTERNAL-MAKE-RESULT.private.json": "0c49164d9a0e464907115c6eda93ad84d34f05c0ece555e1eb66cc7667e77f77",
    "native-internal-make-attempt.private.json": "c8b4d1fba0f97f367b56c5fbe677797841bae9828330218ad83a7203d26ef0eb",
    "original-first-unconsumed-internal-make.intent.private.json": "85169a3c9eabdbfcb492b681e139565f380a4f96033e1be09b8f978aa55200a1",
}
PIPELINE_PIN = "9133d336e5a0bccdb2a58471e61058e1b63780b2f39f70b41e96a829441011f7"
STORE_PIN = "1e63541d231c3250cc11e95249fbfdc86051bbb0b91ced219d65c163c1e72aa0"
SCHEMA = "f8-original-claim-failure-management-continuation-v1"
EFFECT_TABLES = ("artifacts", "approvals", "deliveries", "delivery_queue", "workflow_steps", "workflow_reports", "platform_outputs", "review_tasks", "delivery_intents", "publish_receipts", "gate_results", "source_items")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_private(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (os.name == "posix" and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077)):
        raise PermissionError("root_private_continuation_entity_required")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        return stream.read()


def admission(conn):
    rows = conn.execute("SELECT id,detail_json FROM events WHERE job_id=? AND event='migration_internal_make_admitted' ORDER BY id", (JOB,)).fetchall()
    if len(rows) != 1:
        raise PermissionError("original_single_consumed_admission_required")
    event_id, detail = rows[0]
    data = json.loads(detail)
    if data.get("action") != "internal_make" or data.get("publication_authorized") is not False or data.get("approval_authorized") is not False:
        raise PermissionError("original_internal_make_action_boundary_invalid")
    closed = conn.execute("SELECT count(*) FROM events WHERE job_id=? AND event='migration_internal_make_scope_closed'", (JOB,)).fetchone()[0]
    continued = conn.execute("SELECT count(*) FROM events WHERE job_id=? AND event='migration_internal_make_continuation_admitted'", (JOB,)).fetchone()[0]
    claimed = conn.execute("SELECT count(*) FROM events WHERE job_id=? AND event='job_claimed'", (JOB,)).fetchone()[0]
    if closed != 1 or continued != 0 or claimed != 0:
        raise PermissionError("original_closed_before_claim_once_required")
    return {"id": event_id, "detail_sha256": digest(detail.encode()), "token_sha256": data["token_sha256"]}


def verify_receipt(conn, receipt_path, receipt_sha256, signed_payload):
    raw = raw_private(Path(receipt_path))
    if digest(raw) != receipt_sha256 or signed_payload.get("continuation_sha256") != receipt_sha256:
        raise PermissionError("management_continuation_receipt_hmac_binding_invalid")
    receipt = json.loads(raw)
    if (receipt.get("schema") != SCHEMA or receipt.get("job_id") != JOB
            or receipt.get("prior_capsule_sha256") != PINS
            or receipt.get("prior_admission") != admission(conn)
            or receipt.get("approval_or_publication_authorized") is not False
            or receipt.get("workflow_initialization_reached") is not False
            or receipt.get("generation_stage_reached") is not False
            or receipt.get("source_pipeline_sha256") != PIPELINE_PIN
            or receipt.get("source_prior_store_sha256") != STORE_PIN
            or receipt.get("actual_current_effect_counts") != {table: 0 for table in EFFECT_TABLES}
            or not 0 <= time.time() - receipt.get("audited_at_unix", 0) <= 1800):
        raise PermissionError("management_continuation_receipt_scope_invalid")
    for name, pin in PINS.items():
        if digest(raw_private(PRIOR / name)) != pin:
            raise PermissionError("original_failed_capsule_changed")
    return receipt


def produce(args):
    if os.geteuid() != 0:
        raise PermissionError("root_management_continuation_required")
    original = {name: json.loads(raw_private(PRIOR / name)) for name in PINS}
    for name, pin in PINS.items():
        if digest(raw_private(PRIOR / name)) != pin:
            raise PermissionError("original_failed_capsule_changed")
    failure = original["native-internal-make-failure.private.json"]
    result = original["F8-INTERNAL-MAKE-RESULT.private.json"]
    attempt = original["native-internal-make-attempt.private.json"]
    frames = failure.get("safe_frames", [])
    if (failure.get("error_type") != "IntegrityError"
            or frames[-2:] != [{"file": "pipeline.py", "line": 153, "function": "run"}, {"file": "store.py", "line": 558, "function": "claim"}]
            or result.get("same_original_job") != JOB or result.get("native_returncode") != 2
            or result.get("state") != "created" or result.get("attempts") != 0
            or result.get("original_hold_continuously_kept") is not True):
        raise PermissionError("actual_native_claim_failure_lineage_required")
    pipeline_raw, store_raw = args.pipeline.read_bytes(), args.prior_store.read_bytes()
    if digest(pipeline_raw) != PIPELINE_PIN or digest(store_raw) != STORE_PIN:
        raise PermissionError("original_failed_consumer_source_changed")
    tree = ast.parse(pipeline_raw)
    run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
    claim = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "claim"]
    runners = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "WorkflowStepRunner"]
    if len(claim) != 1 or claim[0].lineno != 153 or len(runners) != 1 or runners[0].lineno <= claim[0].lineno:
        raise PermissionError("actual_claim_before_workflow_source_proof_invalid")
    conn = sqlite3.connect(args.db.as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        prior = admission(conn)
        if prior["token_sha256"] != attempt.get("token_sha256"):
            raise PermissionError("original_attempt_admission_binding_invalid")
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (JOB,)).fetchone())
        if digest(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) != "3594cc2a59e9f3f84cee8fd13fffd44f53182828344bea3107eaf84423954416":
            raise PermissionError("current_original_created_row_changed")
        hold = dict(conn.execute("SELECT * FROM media_migration_hold WHERE job_id=?", (JOB,)).fetchone())
        if digest(json.dumps(hold, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) != "3ebf1816aeb694a90d1094d34115ed0c455fd3a58d6db603dd00aa1a3995c2b5":
            raise PermissionError("original_continuous_hold_changed")
        effects = {}
        for table in EFFECT_TABLES:
            effects[table] = conn.execute("SELECT count(*) FROM " + table + " WHERE job_id=?", (JOB,)).fetchone()[0]
        if any(effects.values()):
            raise PermissionError("original_before_claim_effect_changed")
        receipt = {"schema": SCHEMA, "job_id": JOB, "prior_capsule_sha256": PINS, "prior_admission": prior,
                   "source_pipeline_sha256": PIPELINE_PIN, "source_prior_store_sha256": STORE_PIN,
                   "workflow_initialization_reached": False, "generation_stage_reached": False,
                   "actual_current_effect_counts": effects, "approval_or_publication_authorized": False,
                   "audited_at_unix": time.time()}
    finally:
        conn.close()
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    print(json.dumps({"continuation_receipt_path": str(args.output), "continuation_sha256": digest(raw), "canonical_mutations": 0, "generation_stage_reached": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("db", "pipeline", "prior-store", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    produce(parser.parse_args())
