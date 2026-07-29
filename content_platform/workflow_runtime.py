import time
from contextlib import contextmanager
from pathlib import Path

from .risk import redact_secrets
from .store import utc_now


WORKFLOW_STEPS = [
    "initialize_task",
    "load_content_strategy",
    "run_operation_strategy",
    "generate_content",
    "validate_content_structure",
    "run_fact_check",
    "run_safety_gate",
    "run_quality_gate",
    "collect_or_prepare_materials",
    "generate_or_collect_images",
    "validate_image_requirements",
    "render_platform_content",
    "run_platform_pre_publish_gate",
    "publish_or_create_draft",
    "verify_publish_result",
    "record_publish_receipt",
    "generate_platform_report",
    "send_completion_report",
]

STEP_SUCCEEDED = "SUCCEEDED"
STEP_RUNNING = "RUNNING"
STEP_BLOCKED = "BLOCKED"
STEP_FAILED_RETRYABLE = "FAILED_RETRYABLE"
STEP_FAILED_FINAL = "FAILED_FINAL"
STEP_SKIPPED_ALLOWED = "SKIPPED_ALLOWED"


class WorkflowBlocked(RuntimeError):
    def __init__(self, step, reason_code, message, gate_result=None):
        super().__init__(message)
        self.step = step
        self.reason_code = reason_code
        self.gate_result = gate_result or {}


class WorkflowStepRunner:
    def __init__(self, store, workflow_id, job_id, platform="", notifier=None):
        self.store = store
        self.workflow_id = workflow_id
        self.job_id = job_id
        self.platform = platform or ""
        self.notifier = notifier

    def succeeded(self, step_name, output=None, required=True, depends_on=None, message=""):
        self.store.save_workflow_step(
            self.workflow_id,
            self.job_id,
            self.platform,
            step_name,
            STEP_SUCCEEDED,
            required=required,
            depends_on=depends_on or [],
            message=message,
            output_payload=output or {},
            started_at=utc_now(),
            finished_at=utc_now(),
        )

    def skipped(self, step_name, reason_code, message, required=False, depends_on=None):
        self.store.save_workflow_step(
            self.workflow_id,
            self.job_id,
            self.platform,
            step_name,
            STEP_SKIPPED_ALLOWED,
            required=required,
            depends_on=depends_on or [],
            reason_code=reason_code,
            message=message,
            started_at=utc_now(),
            finished_at=utc_now(),
        )

    def block(self, step_name, reason_code, message, gate_result=None, depends_on=None):
        self.store.save_workflow_step(
            self.workflow_id,
            self.job_id,
            self.platform,
            step_name,
            STEP_BLOCKED,
            required=True,
            depends_on=depends_on or [],
            reason_code=reason_code,
            message=message,
            gate_result=gate_result or {},
            finished_at=utc_now(),
        )
        raise WorkflowBlocked(step_name, reason_code, message, gate_result)

    def run(self, step_name, func, required=True, depends_on=None, require_output=False, input_payload=None):
        depends_on = depends_on or []
        self._assert_dependencies(depends_on, step_name)
        started = utc_now()
        started_mono = time.monotonic()
        self.store.save_workflow_step(
            self.workflow_id,
            self.job_id,
            self.platform,
            step_name,
            STEP_RUNNING,
            required=required,
            depends_on=depends_on,
            input_payload=input_payload or {},
            started_at=started,
        )
        try:
            result = func()
            if require_output and result in (None, "", [], {}):
                self.block(step_name, "missing_required_output", f"{step_name} produced no required output", depends_on=depends_on)
            finished = utc_now()
            self.store.save_workflow_step(
                self.workflow_id,
                self.job_id,
                self.platform,
                step_name,
                STEP_SUCCEEDED,
                required=required,
                depends_on=depends_on,
                output_payload=_compact_output(result),
                started_at=started,
                finished_at=finished,
                duration_ms=int((time.monotonic() - started_mono) * 1000),
            )
            return result
        except WorkflowBlocked:
            raise
        except Exception as exc:
            status = STEP_FAILED_FINAL if required else STEP_FAILED_RETRYABLE
            self.store.save_workflow_step(
                self.workflow_id,
                self.job_id,
                self.platform,
                step_name,
                status,
                required=required,
                depends_on=depends_on,
                reason_code="exception",
                message=redact_secrets(exc),
                started_at=started,
                finished_at=utc_now(),
                duration_ms=int((time.monotonic() - started_mono) * 1000),
            )
            if required:
                raise
            return None

    def _assert_dependencies(self, depends_on, step_name):
        if not depends_on:
            return
        steps = {row["step_name"]: row["status"] for row in self.store.workflow_steps(self.job_id, self.platform)}
        missing = [name for name in depends_on if steps.get(name) not in {STEP_SUCCEEDED, STEP_SKIPPED_ALLOWED}]
        if missing:
            self.block(
                step_name,
                "dependency_not_satisfied",
                f"{step_name} cannot start before dependencies complete: {', '.join(missing)}",
                {"missing": missing, "current": steps},
                depends_on=depends_on,
            )


@contextmanager
def strict_workflow_lock(store, owner, workflow_id, ttl_seconds=1800, enabled=True):
    if not enabled:
        yield
        return
    if not store.acquire_workflow_lock(owner, workflow_id, ttl_seconds):
        raise RuntimeError("another ai-self-media-tools workflow is already running")
    try:
        yield
    finally:
        store.release_workflow_lock(owner)


def write_platform_report(store, data_dir, workflow_id, job, platform, status, delivery=None, error=""):
    reports_dir = Path(data_dir) / "reports" / job["id"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    delivery = delivery or {}
    steps = store.workflow_steps(job["id"], platform)
    report_path = reports_dir / f"{platform or 'workflow'}.md"
    started = steps[0]["started_at"] if steps else ""
    finished = utc_now()
    blocked = [row for row in steps if row["status"] in {STEP_BLOCKED, STEP_FAILED_FINAL}]
    summary = {
        "workflow_id": workflow_id,
        "job_id": job["id"],
        "platform": platform,
        "status": status,
        "delivery_status": delivery.get("status", ""),
        "external_id_present": bool(delivery.get("external_id")),
        "blocked_count": len(blocked),
        "step_count": len(steps),
    }
    lines = [
        "# Platform Task Execution Report",
        "",
        f"- Workflow ID: {workflow_id}",
        f"- Job ID: {job['id']}",
        f"- Platform: {platform}",
        f"- Started At: {started}",
        f"- Finished At: {finished}",
        "- Execution Mode: strict_serial",
        f"- Final Status: {status}",
        "",
        "## Content",
        f"- Title: {job.get('title') or job.get('topic', '')}",
        f"- Delivery Status: {delivery.get('status', '')}",
        f"- External ID Present: {bool(delivery.get('external_id'))}",
        f"- Error: {redact_secrets(error or delivery.get('error', ''))}",
        "",
        "## Steps",
        "| Step | Status | Duration ms | Reason |",
        "|---|---:|---:|---|",
    ]
    for row in steps:
        lines.append(f"| {row['step_name']} | {row['status']} | {row.get('duration_ms', 0)} | {row.get('reason_code', '')} |")
    lines.extend([
        "",
        "## Risks",
        f"- Unresolved blocked steps: {len(blocked)}",
        "- Duplicate publish risk: controlled by delivery idempotency key and publish receipt checks",
    ])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    store.save_workflow_report(workflow_id, job["id"], platform, status, str(report_path), summary)
    return {"path": str(report_path), "summary": summary}


def _compact_output(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        compact = {}
        for key, item in value.items():
            if key.lower() in {"body", "html", "content"}:
                text = str(item)
                compact[key] = {"chars": len(text), "excerpt": redact_secrets(text[:700])}
            else:
                compact[key] = item if isinstance(item, (str, int, float, bool, list, dict)) else str(item)
        return compact
    if isinstance(value, list):
        return {"count": len(value)}
    return {"value": str(value)[:500]}
