# Operations Evidence Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cross-platform topic choice, final video quality, and policy consistency verifiable before publisher handoff.

**Architecture:** Add a small manifest module and CLI to hold run-scoped evidence. Reuse the current topic checker as a compatibility gate, add a read-only final-video verifier, and audit policy facts against the operational skill documents. No publisher or account integration changes.

**Tech Stack:** Python standard library, pytest, ffprobe/ffmpeg when locally installed.

---

### Task 1: Run Manifest And Direction Register

**Files:**
- Create: `content_platform/ops_run.py`
- Create: `scripts/ops_run.py`
- Modify: `scripts/check_platform_topic_independence.py`
- Test: `tests/test_ops_run.py`

- [ ] Write tests that reject same normalized direction across platforms and allow a documented follow-up with a new angle and reason.
- [ ] Run `python -m pytest tests/test_ops_run.py -q` and confirm the missing module causes the expected failure.
- [ ] Implement JSON manifest creation, topic registration, and validation; make the legacy checker consume a same-date register when present.
- [ ] Run `python -m pytest tests/test_ops_run.py tests/test_operational_scripts.py -q` and confirm it passes.

### Task 2: Final Video Artifact Gate

**Files:**
- Create: `content_platform/video_artifact.py`
- Create: `scripts/verify_video_artifact.py`
- Modify: `scripts/video_toolchain_runner.py`
- Test: `tests/test_video_artifact.py`

- [ ] Write tests for an overlong short video, wrong vertical dimensions, placeholder title, static-frame evidence, and a valid manifest.
- [ ] Run `python -m pytest tests/test_video_artifact.py -q` and confirm the missing module causes the expected failure.
- [ ] Implement a read-only validator and invoke it after a successful local render, recording a structured verification result in the render manifest.
- [ ] Run `python -m pytest tests/test_video_artifact.py tests/test_video_toolchain_runner.py -q` and confirm it passes.

### Task 3: Policy And Skill Drift Audit

**Files:**
- Create: `scripts/audit_strategy_skill_conflicts.py`
- Modify: `scripts/validate_channel_rulebook.py`
- Test: `tests/test_strategy_skill_audit.py`
- Modify: `docs/CONTINUOUS_DEVELOPMENT.md`

- [ ] Write tests for a matching policy/skill pair and each known conflict class.
- [ ] Run `python -m pytest tests/test_strategy_skill_audit.py -q` and confirm the missing module causes the expected failure.
- [ ] Implement the read-only audit and expose it through the existing rulebook validation path.
- [ ] Run the focused tests, full suite, rulebook validator, and project audit; append evidence and operating instructions to the continuous-development document.
