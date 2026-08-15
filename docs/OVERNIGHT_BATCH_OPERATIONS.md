# Recoverable Overnight Operations

## Purpose

Run all channels that are due according to the account growth strategy between
00:00 and 05:00 without holding a long-lived Hermes conversation or the global
Hermes work-directory lock. The content worker is the executor. Hermes is only
the observer, reporter, and exception handler.

## Boundary

- Automatic lane, after the existing Pipeline gates and approvals: WeChat,
  Kuaishou, Zhihu, Juejin, and X.
- Manual-handoff lane: Bilibili, Douyin AI, Douyin pet, Shipinhao,
  Xiaohongshu, YouTube, and TikTok. Their final overnight state is
  `handoff_ready`, never `published` or `drafted`.
- The batch never implicitly approves or publishes a job. It may stage a draft
  for an automatic channel when that task explicitly requests `action: stage`.

## Nightly Input

## Provider Preflight

Before any analytics refresh or content job creation, the systemd worker runs
`scripts/smoke_provider.sh config.json`. The generator configuration must name
both `hermes_provider` and `hermes_model`; the smoke runs in a minimal
systemd-like environment and requires a JSON object with `title` and `body`.
An HTTP authentication, rate-limit, service, or invalid-JSON response blocks
the batch before it creates jobs.

The production project passes `--provider` and `--model` explicitly. Do not
rely solely on Hermes' global default provider or alter tracked files with a
credential. Any Hermes credential-pool repair remains server-local.

The server-local `secrets/overnight-slots.json` contains only channels that are
due tonight. It is not committed. Every row must have a platform, topic, brief,
stage, action, and conservative `estimate_minutes`.

```json
[
  {
    "platform": "wechat",
    "topic": "Selected after a verified source matrix",
    "brief": {"platform_source_matrix": {"attempted_sources": []}},
    "stage": "article",
    "action": "stage",
    "estimate_minutes": 35
  }
]
```

The planning command fails closed when the sum of scheduled estimates would
cross 04:50. It does not start a task which cannot finish before the 05:00
morning-report window. It does not terminate an already admitted task merely
because 04:50 arrives; each task has its own conservative time budget and
checkpoint. The systemd service admits scheduled runs between 00:00 and 01:00
by default. Set server-local `OVERNIGHT_ADMISSION_WINDOW_MINUTES` only when a
narrower window is required. A later `Persistent=true` catch-up writes
`no_run` and never consumes the morning-report window.

## Execution and Recovery

```bash
content-platform overnight-plan --tasks secrets/overnight-slots.json \
  --output data/overnight/DATE/plan.json --deadline-minute 290 --finalization-minutes 10
content-platform overnight-run --plan data/overnight/DATE/plan.json \
  --state data/overnight/DATE/state.json --events data/overnight/DATE/events.jsonl
```

`state.json` is atomically written after every platform. Restarting the command
continues unfinished rows and never recreates rows already marked `staged`,
`handoff_ready`, `published`, `review_required`, `blocked`, or `failed`. A row
found as `running` after process interruption becomes
`blocked: interrupted_batch_requires_recovery`; it is never replayed
implicitly. `events.jsonl` is an
append-only event stream for real-time reporting.

Transient infrastructure failures are retried once inside the same batch only
for timeouts, temporary connections, rate limits, locks, and resource-busy
errors. Authentication failures, quality-gate failures, missing trend evidence,
and any publish or manual-review boundary remain blocked or failed without
automatic replay.

## Reporting Contract

Hermes follows `events.jsonl` and the Pipeline notification log, reports each
start, material decision, blocked reason, repair attempt, and final platform
state. If Hermes itself stops, the worker continues and the next Hermes session
reads the same files. Notification delivery failure is recorded but cannot
abort content work.

## Service Installation

Install the two template units from `systemd/`, run `systemctl daemon-reload`,
enable `hermes-content-platform-overnight.timer`, then verify that the 05:00
morning-report service uses its own worker and does not share a Hermes workdir
lock. Do not enable the timer until a read-only dry run has produced a
capacity-safe plan.

Enable `hermes-content-platform-runtime-cleanup.timer` as well. It archives
only rebuildable media intermediates older than 14 days; final media,
handoff files, acceptance reports, and manifests are never cleanup targets.

## Hermes Progress Reporting

The systemd units load an optional server-local
`secrets/notifications.env`. It is never committed. Set only a preconfigured
Hermes delivery target, for example:

```bash
AI_SELF_MEDIA_HERMES_TARGET=telegram
AI_SELF_MEDIA_TELEGRAM_TARGET=telegram
```

The batch wrapper emits start, strategy-refresh, preparation, plan, completion,
skip, and failure events. `scripts/create_hermes_overnight_monitor.py` registers
a read-only three-minute observer which reads `events.jsonl` and `state.json`.
It must use `AI_SELF_MEDIA_TELEGRAM_TARGET`; the observer reports progress but
never retries, approves, publishes, or modifies a task.

If notifications cannot be delivered, the worker continues and its local
event/checkpoint files remain authoritative for recovery.

## Persisted Acceptance And Reconciliation

The pipeline records acceptance for every batch job in SQLite and the batch
writes `acceptance_summary.json` after execution. The summary reconciles the
durable job/delivery state with `state.json`; it never infers `published` from
a successful wrapper or uploader response.

- A failed content or artifact acceptance is `blocked` and changes the batch
  status to `partial`.
- `handoff_pending` is represented only as `handoff_ready`.
- Kuaishou `under_review` is a successful submission verification only when
  the management page also proves the matching title and description. It is
  never reported as published.
- Source evidence is created by collection and ranking stages. The batch must
  not create placeholder matrices or treat generic sources as platform proof.

## Acceptance

- Plan status is `scheduled`; no row exceeds the 04:50 work deadline.
- Each row owns exactly one platform and one job id.
- Event stream has `platform_started` plus final event for every row.
- Automatic channels pass the existing preflight, quality gate, and postcheck.
- Handoff channels contain the full package and end in `handoff_ready`.
- No credential appears in `plan.json`, `state.json`, `events.jsonl`, reports,
  or notification logs.
