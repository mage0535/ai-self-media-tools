# Quality Runtime V6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development task-by-task. Luna implements bounded tasks; Terra reviews specification compliance and code quality; Sol integrates and controls production.

**Goal:** Build and deploy a model-agnostic, deterministic, high-quality Hermes content runtime with executable capabilities and real end-to-end evidence.

**Architecture:** A single platform-serial state machine compiles compact platform context, executes one capability DAG, validates actual artifacts, delivers through policy adapters, and creates verified metric windows. Development uses Codex roles; production follows Hermes' active model and contains no Codex model identifiers.

**Tech Stack:** Python 3.12, SQLite, pytest, JSON Schema, FFmpeg/ffprobe, Playwright, systemd, Hermes CLI/MCP.

---

### Task 1: Baseline And Release Discipline

**Files:** `scripts/runtime_release_audit.py`, `tests/test_runtime_release_audit.py`, deployment scripts.

- [ ] Add a failing test for mismatched source, release, and configured script roots.
- [ ] Implement immutable release metadata with commit, source hashes, config hash, test report, and rollback target.
- [ ] Reject dirty or uncommitted release inputs.
- [ ] Verify with focused tests, full pytest, project audit, and a rollback dry run.
- [ ] Commit as `fix: establish auditable release source of truth`.

### Task 2: Compact Platform Context And Hermes Recovery

**Files:** create `content_platform/generation_context_compiler.py`; modify `generator.py`, `capability_context.py`, `platform_workflow_context.py`, `workflow_runtime.py`; tests under `tests/test_generation_context_compiler.py` and `tests/test_hermes_generation_recovery.py`.

- [ ] Write failing tests that reject unrelated platform rules, repeated Skill text, inventory dumps, and oversized provider context.
- [ ] Compile a platform/stage-specific provider packet with rule IDs and hashes.
- [ ] Add progress heartbeat, soft deadline, hard deadline, one compact-context retry, and persisted failure classification.
- [ ] Prove Juejin input contains no Douyin rules and a stalled Hermes call terminates with a resumable checkpoint.
- [ ] Commit as `fix: bound platform context and recover Hermes generation`.

### Task 3: Unified Capability Registry

**Files:** replace `config/creative_capability_registry.json`; modify `tool_selection.py`, `capability_catalog.py`, `capability_router.py`, `adapter_executor.py`, `execution_dag.py`; add registry schema and tests.

- [ ] Write schema and coverage tests for all 22 tool groups.
- [ ] Register real probes/adapters/contracts/gates/fallbacks; retain unsupported entries as explicit inventory only.
- [ ] Make legacy tool selection a compatibility view generated from the registry.
- [ ] Fail required selection when no executable adapter exists.
- [ ] Verify manifest state transitions and output hashes.
- [ ] Commit as `feat: make capability registry the execution source of truth`.

### Task 4: Skills And MCP Adapters

**Files:** create `content_platform/adapters/methodology.py`, `search.py`, `mcp.py`; modify `skill_rule_compiler.py`, `capability_catalog.py`; tests for routing and evidence.

- [ ] Test archive/duplicate/irrelevant Skill exclusion and platform-specific rule selection.
- [ ] Implement content-relevant MCP adapters for configured search, memory, and content-platform tools.
- [ ] Record MCP tool name, input/output hash, duration, status, and affected output.
- [ ] Exclude trading and unrelated MCP namespaces from content DAGs.
- [ ] Commit as `feat: execute selected skills and MCP capabilities`.

### Task 5: Platform Intelligence And Hotspot Association

**Files:** modify `official_reference_signals.py`, `trend_intelligence.py`, `trends.py`, `associated_hotspot.py`, `overnight_batch.py`; platform collector tests.

- [ ] Add fixtures for all 12 platforms covering native, activity, keyword, same-lane, unavailable, and expired evidence.
- [ ] Implement bounded same-platform recapture and labeled evergreen fallback.
- [ ] Enforce global seven-day semantic dedupe and atomically reserve the selected topic before generation.
- [ ] Permit follow-up reuse only with `follow_up_to`, `difference_angle`, and `recap_reason`; expire abandoned reservations explicitly.
- [ ] Persist hotspot identity, validity, lane/semantic fit, association mode, and postcheck state.
- [ ] Verify one independent candidate or truthful block per scheduled platform.
- [ ] Commit as `feat: complete platform-native topic intelligence`.

### Task 6: Article And Media DAG

**Files:** modify `pipeline.py`, `media.py`, `image_provider.py`, `video_toolchain_runner.py`, `film_renderer.py`, TTS/BGM/subtitle modules; create platform media contracts.

- [ ] Write failing contract tests for Juejin cover plus three mapped inline images and public asset URLs.
- [ ] Add bounded within-platform asset concurrency, per-asset checkpointing, semantic/SHA gates, and public staging.
- [ ] Define `handoff_ready` as version-bound copy/media with checksums, source/license evidence, target-renderer evidence, editor-visible image mapping, and encoded motion/background evidence for video.
- [ ] Verify scene-level motion, subtitles, audio, BGM license/source, and final MP4 probes.
- [ ] Reject NC/ND production BGM and missing source URLs.
- [ ] Commit as `feat: execute and verify complete media contracts`.

### Task 7: Delivery, Ledger, And Metrics

**Files:** integrate `publication_ledger.py` with `store.py`, `pipeline.py`, publisher adapters, scheduler, and collectors; add migrations and tests.

- [ ] Test verified and unverified publication identities for automatic and manual channels.
- [ ] Persist an immutable delivery intent before external calls, including account, action, payload/media hashes, expected copy, and schedule.
- [ ] Treat timeout/crash as an unknown result; poll by immutable account/copy/media/schedule identity and retry only when the full window proves absence.
- [ ] Persist `unknown_requires_review` for failed authentication, conflicting matches, or inconclusive polling, and forbid automatic retry for that intent.
- [ ] Require Kuaishou management-page account, title, full-description or digest, exact-time, and screenshot/DOM evidence before `scheduled`.
- [ ] Add idempotent 1h/24h/72h windows, attempts, leases, retry, insufficient, and invalidated states.
- [ ] Bind observations to platform, internal account alias, content ID, source, and confidence.
- [ ] Verify drafts/handoffs/review items never create metric windows.
- [ ] Commit as `feat: connect publication identity and metric feedback`.

### Task 8: State Machine And Chinese Reporter

**Files:** modify `workflow_runtime.py`, `overnight_batch.py`, `overnight_supervisor.py`, `notify.py`; create `content_platform/chinese_reporter.py`; add state/reporter tests.

- [ ] Test strict serial execution, current-platform stop-on-failure, checkpoint resume, and two-repair limit.
- [ ] Translate structured events into detailed Chinese business updates.
- [ ] Keep reporter independent and read-only.
- [ ] Verify stale heartbeat, active long stage, completed stage, and terminal failure messages.
- [ ] Commit as `feat: add durable recovery and Chinese workflow reporting`.

### Task 9: Verification And Production Activation

**Files:** create auditable Canary fixtures/reports and deployment acceptance scripts.

- [ ] Run full pytest, privacy audit, license audit, compile, and diff checks.
- [ ] Execute 12 serial real canaries with platform-policy delivery states.
- [ ] Include crash-boundary delivery recovery, delayed visibility where the first poll misses and a later poll finds the item, `unknown_requires_review`, duplicate-schedule prevention, exact Kuaishou management-page postcheck, and complete handoff-render contracts in Canary acceptance.
- [ ] Run Hermes active-model and available weak-model cases against identical deterministic gates.
- [ ] Rehearse rollback and verify database/cookie/media preservation.
- [ ] Run two shadow batches without code edits or manual recovery.
- [ ] Enable timers only after every acceptance condition passes.
- [ ] Commit reports and deploy the audited immutable release.
