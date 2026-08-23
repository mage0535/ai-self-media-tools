# Luna 5.6 Quality Runtime V3 Implementation Plan

> **For agentic workers:** Execute task-by-task with test-driven development. Keep production and Hermes timers frozen until every release gate passes.

**Goal:** Make ai-self-media-tools select and execute the right tools, skills, MCP capabilities, rules, hot topics, media gates, and publication feedback for each platform with auditable evidence.

**Architecture:** One deterministic capability catalog and execution DAG. Content profile, verified trend/hotspot evidence, compiled rules, and tool selection are assembled before model generation. Only verified execution and artifact evidence can promote a capability beyond planned/consulted.

**Tech Stack:** Python, SQLite, pytest, Hermes CLI/MCP, Playwright, FFmpeg, systemd, JSON evidence contracts.

## Milestones

- P0: baseline, production protection, generation-input repair, fail-closed trend admission.
- P1: unified catalog for active tools, skills, MCP tools, scripts, gates, and publishers.
- P2: platform-native associated-hotspot contract, support matrix, identity validation, scoring.
- P3: pre-generation compilation of hooks, structures, formulas, skill rules, and affected outputs.
- P4: allowlisted adapter DAG, resource limits, artifact lineage, fail-closed media gates.
- P5: 12 real non-publishing canaries with media probes and active/secondary model evidence.
- P6: verified publication identities, metric observations/attempts, scheduler, collectors, and rollback.
- Release: three-way sync, migrations, privacy/license audit, rollback rehearsal, shadow run, then per-platform rollout.

## Autonomous Rules

- Never modify production while developing; never enable timers before release gates pass.
- Never fabricate native trend, hotspot association, tool execution, publication identity, or metrics.
- Required capability failure blocks its stage; optional capability failure records fallback/not_invoked and continues.
- If a dependency is unavailable, choose the safest approved fallback, record the reason, and continue independent work.
- Every phase requires failing tests first, passing targeted tests, full regression, audit, evidence artifact, and a reversible commit.
