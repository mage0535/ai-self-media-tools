# Domestic Content Quality Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static-card domestic batch with quality-gated, channel-specific article and video artifacts.

**Architecture:** Add a Local Ops Lab rebuild runner that uses the existing template selector and voice engine, then verifies rendered media before a publisher receives a manifest. Add a small reusable media-quality module so a pipeline can reject incomplete video metadata as well.

**Tech Stack:** Python, Pillow, FFmpeg/ffprobe, existing Local Ops Lab template selector and voice engine, Patchright publishers.

---

### Task 1: Add machine-readable quality checks

**Files:**
- Create: `content_platform/media_quality.py`
- Create: `tests/test_media_quality.py`

- [ ] Validate article length, hook presence, template-selection evidence, and section-image mapping.
- [ ] Validate video audio/subtitle/burned-caption evidence and a non-empty source-asset catalog.
- [ ] Run `python -m pytest -q tests/test_media_quality.py`.

### Task 2: Build an operational rebuild runner

**Files:**
- Create: `.codex-server-runtime/private/local-ops-lab/domestic_quality_rebuild_20260717.py`
- Modify: `.codex-server-runtime/private/local-ops-lab/channel_content_quality_rules_20260715.json`

- [ ] Generate long-form, hook-led article packets with selected template evidence and section-matched images.
- [ ] Generate full-bleed narrated video packets with a real-footage asset manifest, SRT captions, lower-third caption burn-in, and ffprobe evidence.
- [ ] Persist a per-item quality report that blocks manifests on failure.

### Task 3: Replace queued work safely

**Files:**
- Create: ignored runtime evidence under `.codex-server-runtime/private/local-ops-lab/artifacts/`

- [ ] Postcheck each old item by its platform-visible title or description.
- [ ] Delete only exact matching queued/draft records, then save the before/after evidence.
- [ ] Upload only health-allowed replacement items and collect management-page postchecks.

### Task 4: Verify and record

**Files:**
- Modify: `docs/CONTINUOUS_DEVELOPMENT.md`

- [ ] Run focused tests, media probes, extracted-frame review, and project audit.
- [ ] Record the new gate semantics and actual upload state without credentials.
