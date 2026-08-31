# Production Runtime V8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one production runtime where Hermes uses every relevant capability through a deterministic, resumable, evidence-backed platform workflow.

**Architecture:** Immutable releases provide code only; private config and mutable data remain outside releases. Every production job is admitted through an evidence-backed run contract, routed through one capability registry and execution DAG, and reaches review or delivery only after the platform artifact contract passes.

**Tech Stack:** Python 3.12, SQLite, systemd, Hermes MCP, Playwright, FFmpeg, pytest, JSON evidence manifests.

---

## Execution sequence

- [ ] P0 baseline, JUnit, privacy, license, and runtime snapshots.
- [ ] P1 runtime path resolver and MCP/config/database convergence.
- [ ] P2 automated task admission and legacy isolation.
- [ ] P3 platform completion contracts and stale lease recovery.
- [ ] P4 pre-generation operations and source gates.
- [ ] P5 unified capability/MCP/Skill execution evidence.
- [ ] P6 bounded Hermes worker sessions and generation SLOs.
- [ ] P7 image checkpoint and verified stock-to-generation fallback.
- [ ] P8 video shot retry, checkpoint, final media, and effect evidence.
- [ ] P9 delivery postchecks and Publication Ledger.
- [ ] P10 four-format smoke, 12-platform Canary, rollback, and controlled timer restoration.

Each checkbox is complete only with a failing test added first, targeted tests passing, full regression passing, a focused commit, and evidence recorded in `docs/continuous-development/SERVER_EVIDENCE.md`.
