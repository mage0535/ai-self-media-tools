# Task9 Deployment Acceptance

Task9 is an evidence-only release gate. Run the canary runner serially against a
materialized artifact root, then evaluate the resulting report. The runner calls
`python -m content_platform.cli project-audit` for every platform and probes real
files, hashes, SQLite delivery state, PIL cover dimensions, and FFmpeg/ffprobe
media when installed. It does not publish, alter timers, or change production
databases, cookies, or media.

```powershell
python scripts/task9_canary.py --artifact-root .task9-artifacts --output .task9-reports/canary.json
python scripts/task9_acceptance.py --report .task9-reports/acceptance-input.json --output .task9-reports/acceptance.json --require-production-ready
python scripts/task9_deployment_acceptance.py --report .task9-reports/acceptance-input.json --current-root $PWD --rollback-root C:\releases\previous --protected-root $PWD\data --output .task9-reports/deployment.json
```

`production_ready` is forbidden unless all 12 artifact/policy cases pass, full
pytest/privacy/license evidence paths exist, source/release/Hermes commit parity
matches, rollback rehearsal passes, two shadow reports are clean, and both the
active and an available weak Hermes model pass the same deterministic gates. If
the second model is unavailable, the report must remain `dual_model_pending`.

Delivery failures remain auditable: crash/timeout is `unknown`, delayed visibility
is polled by immutable identity, inconclusive/auth/conflict is
`unknown_requires_review`, duplicate schedules reuse one intent, and Kuaishou is
not `scheduled` without management-page account/title/full-description-or-digest/
exact-time plus DOM or screenshot evidence. Manual channels remain
`handoff_pending` or `handoff_ready`; they are never reported as published.
