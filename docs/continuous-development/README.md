# Production Runtime V8 Continuous Development

This directory is the coordination source of truth for the production-runtime-v8 work.

## Required reading order

1. `README.md` (this file) - coordination and ownership protocol.
2. `STATUS.md` - current phase, active owner, blockers, and next command.
3. `DECISIONS.md` - architecture decisions that must not be silently reversed.
4. `SERVER_EVIDENCE.md` - observed production facts and verification evidence.

Then read `../superpowers/plans/2026-08-31-production-runtime-v8.md` for the implementation sequence and acceptance gates. Re-read all four coordination files after an interruption; an earlier chat summary is not the current source of truth.

## Collaboration protocol

- Branch: `codex/production-runtime-v8`
- Worktree: `D:/Onedrive/CodeX/worktrees/ai-self-media-production-runtime-v8`
- Base: `149362f23a93f64d35ae16d2f17bb38080ec9dd3`
- Do not edit the private mutable runtime (`$PRIVATE_RUNTIME`) directly.
- Do not enable overnight timers until `STATUS.md` records all production gates as passed.
- Before editing a shared file, record the owner and file list in `STATUS.md`.
- Each change uses failing test -> minimal implementation -> targeted tests -> full tests -> commit.
- A task is complete only after updating `STATUS.md` and adding durable evidence to `SERVER_EVIDENCE.md`.
- Never report `review_required`, `approved`, uploader success, or artifact existence as a completed platform delivery.

## Shared-file lock convention

Record one row per active work item in `STATUS.md`. Only one owner may hold a file at a time. If work overlaps, split by adapter/test file rather than editing the same core module concurrently.

## Current handoff

- P1-P4 are committed local milestones; production deployment remains prohibited.
- P5 capability evidence and inventory governance are committed local milestones.
- P6 bounded Hermes worker sessions and generation SLOs are a committed local milestone.
- P7 image checkpoint and verified provider fallback is a committed local milestone.
- P8 video shot retry, checkpoint, and final-effect evidence is a committed local milestone.
- P9 publication identity and metric retry are a committed submilestone.
- P9 postcheck capability is implemented and verified as a local submilestone.
- P9 delivery trace persistence and negative-path hardening are a locally verified milestone.
- P10 real media Canaries, Linux deployment, live publisher verification, and rollback rehearsal are the next workstream. Tests with replacement publishers are not live platform proof.
- P10 starts with a read-only server baseline, then a signed immutable release candidate with timers kept disabled. Activation and rollback evidence must be recorded before any live Canary.
- The legacy current release is not a valid rollback artifact because runtime files and tracked drift are present. Use `prepare_bootstrap_release` from a clean Git source to create a signed rollback without activating it.
- Bootstrap preparation now rejects unsafe names and unresolved path boundaries before side effects, and cleans up only outputs proven to belong to its own transaction. Do not bypass these guards with ad hoc copies.
- Server activation must use the same systemd scope as the installed production units. The current server uses system scope; scope convergence remains a P10 gate.
- Deployment and acceptance now accept `--systemd-scope user|system`; this is command routing, not proof of a completed activation. Expanded effective paths and gateway-root convergence still require Linux verification.
- On every resume, compare server HEAD, dirty-file names, and available timestamps/hashes before deployment. Preserve uncommitted server work; unchanged HEAD alone does not establish unchanged content.
- Effective-unit validation compares expanded runtime paths and exact environment assignments. External scraper environment paths must not be mistaken for the service's ExecStart; missing production roots still block activation.
- Effective-path implementation `de506e2` passed local full regression and Linux deployment-focused regression. Continue with signed candidate preparation and gateway/config convergence, not timer restoration.
- Real private-config preflight currently rejects three external Hermes tool bridges. Do not remove tools or loosen the release boundary to obtain a passing signature. Resolve explicit external-tool ownership/contracts first; fail-fast preflight now avoids expensive builds for known incompatible config.
- External bridge trust uses an explicit private-config contract bound to config key, absolute path under Hermes home, regular-file status, and SHA-256. Passing this contract proves dependency identity only, not invocation or content impact.
- Stable `$CURRENT_RELEASE` script aliases are rewritten to the explicitly supplied candidate code root before filesystem resolution. Canary callers pass their code root directly rather than relying on ambient environment.
- At handoff, update all four documents with exact commands/results, remaining gaps, and file ownership. Do not describe an old server observation as a fresh health check.
