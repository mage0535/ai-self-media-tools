# Content Intelligence MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working content-intelligence MVP that analyzes same-track references, scores candidate virality, chooses content form, records intelligence data, and exposes server content-tool readiness through the existing `content_platform`.

**Architecture:** Extend the existing single-process Python workflow rather than replacing it. Add focused modules for normalized source ingestion, intelligence persistence, niche analysis, viral scoring, strategy routing, and tool registry, then enrich `DraftGenerator`, `Pipeline`, `Store`, `readiness`, and `cli` with metadata-first behavior.

**Tech Stack:** Python standard library, SQLite, existing `content_platform` pipeline, unittest.

---

### Task 1: Intelligence Tests First

**Files:**
- Modify: `tests/test_intelligence.py`
- Create: `tests/test_intel_store.py`
- Create: `tests/test_strategy.py`

- [ ] **Step 1: Write failing tests for normalized source ingestion and context enrichment**
- [ ] **Step 2: Run focused tests and verify they fail for missing modules / missing fields**
- [ ] **Step 3: Add tests for virality scoring, content strategy routing, and enriched `draft_meta`**
- [ ] **Step 4: Run focused tests and verify they fail for the expected missing behavior**

### Task 2: Intelligence Modules

**Files:**
- Create: `content_platform/sources.py`
- Create: `content_platform/niche_analysis.py`
- Create: `content_platform/viral_score.py`
- Create: `content_platform/strategy_router.py`
- Modify: `content_platform/intelligence.py`

- [ ] **Step 1: Implement normalized source ingestion helpers**
- [ ] **Step 2: Implement niche/style signature analysis**
- [ ] **Step 3: Implement interpretable viral scoring**
- [ ] **Step 4: Implement content-form and platform strategy routing**
- [ ] **Step 5: Update generation-context assembly to include the new metadata**

### Task 3: Intelligence Persistence

**Files:**
- Modify: `content_platform/store.py`
- Modify: `tests/test_store.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests for intelligence tables and persistence helpers**
- [ ] **Step 2: Run focused tests and verify failure**
- [ ] **Step 3: Add SQLite tables and helper methods for source items, account snapshots, idea candidates, and tool inventory**
- [ ] **Step 4: Persist enriched draft metadata and pipeline-side intelligence events**
- [ ] **Step 5: Run store and pipeline tests to green**

### Task 4: Tool Registry And Readiness

**Files:**
- Create: `content_platform/tool_registry.py`
- Modify: `content_platform/media.py`
- Modify: `content_platform/readiness.py`
- Modify: `tests/test_adapters.py`
- Modify: `tests/test_cli_v2.py`

- [ ] **Step 1: Write failing tests for tool detection and readiness output**
- [ ] **Step 2: Run focused tests and verify failure**
- [ ] **Step 3: Implement capability probing for image, video, OCR, transcription, crawling, and browser tools**
- [ ] **Step 4: Refactor media bridge to expose provider metadata through a registry-backed interface**
- [ ] **Step 5: Run the focused tests to green**

### Task 5: Generator, CLI, And Documentation

**Files:**
- Modify: `content_platform/generator.py`
- Modify: `content_platform/cli.py`
- Modify: `tests/test_content.py`
- Modify: `tests/test_cli.py`
- Modify: `docs/CONTINUOUS_DEVELOPMENT.md`

- [ ] **Step 1: Write failing tests for richer generation metadata and new CLI analysis commands**
- [ ] **Step 2: Run focused tests and verify failure**
- [ ] **Step 3: Implement generator metadata enrichment and CLI analysis/report commands**
- [ ] **Step 4: Append this development wave to the continuous-development document**
- [ ] **Step 5: Run the full test suite and keep everything green**
