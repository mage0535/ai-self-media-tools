# Production Runtime V8 Continuous Development

This directory is the coordination source of truth for the production-runtime-v8 work.

## Required reading order

1. `STATUS.md` - current phase, active owner, blockers, and next command.
2. `DECISIONS.md` - architecture decisions that must not be silently reversed.
3. `SERVER_EVIDENCE.md` - observed production facts and verification evidence.
4. `../superpowers/plans/2026-08-31-production-runtime-v8.md` - implementation sequence and acceptance gates.

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
- P9 remains active to persist postcheck execution into the delivery trace; start with its row in `STATUS.md`.
