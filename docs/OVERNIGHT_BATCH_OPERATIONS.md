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
checkpoint. The systemd service admits scheduled runs only between 00:00 and
00:15; a late `Persistent=true` catch-up writes `no_run` and never consumes the
morning-report window.

## Execution and Recovery

```bash
content-platform overnight-plan --tasks secrets/overnight-slots.json \
  --output data/overnight/DATE/plan.json --deadline-minute 290 --finalization-minutes 10
content-platform overnight-run --plan data/overnight/DATE/plan.json \
  --state data/overnight/DATE/state.json --events data/overnight/DATE/events.jsonl
```

`state.json` is atomically written after every platform. Restarting the command
continues unfinished rows and never recreates rows already marked `staged`,
`handoff_ready`, `published`, `blocked`, or `failed`. `events.jsonl` is an
append-only event stream for real-time reporting.

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

## Acceptance

- Plan status is `scheduled`; no row exceeds the 04:50 work deadline.
- Each row owns exactly one platform and one job id.
- Event stream has `platform_started` plus final event for every row.
- Automatic channels pass the existing preflight, quality gate, and postcheck.
- Handoff channels contain the full package and end in `handoff_ready`.
- No credential appears in `plan.json`, `state.json`, `events.jsonl`, reports,
  or notification logs.
