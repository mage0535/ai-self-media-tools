# Continuous Development

Last updated: 2026-07-02

## Mandatory Rules

- This document is the single ongoing handoff document for all future work.
- Every contributor must append real work, validation, blockers, and next steps here.
- Never commit or sync private server information, passwords, SSH keys, tokens, cookies, personal account data, or machine-specific private paths.
- Local and GitHub code must remain clean, publishable, and installable.
- Runtime secrets must be stored in ignored local files only.
- Any future server deployment must keep secrets outside the synced repository.

## Project Purpose

Build a unified AI self-media toolkit that can:
- discover trends
- learn same-track popular writing and visual style
- generate stronger text, image, and video prompts
- stage drafts to multiple platforms
- automate eligible AiToEarn promotion tasks
- coordinate with Hermes and other agents without being hard-wired to one agent runtime

## Delivery Goal

This repository is the clean, publishable, continuously-developed home for:

1. Content intelligence and generation
2. Draft-first multi-platform distribution
3. AiToEarn promotion-task automation
4. Cross-agent installation and operation

It is intended to replace fragmented machine-local scripts with one syncable project directory.

## Architecture Summary

### 1. Content Intelligence
- trend collection
- same-track reference fetching
- style extraction
- topic angle selection
- draft metadata generation

### 2. Distribution Matrix
- official draft publishers
- AiToEarn draft/flow publishers
- browser-upload integration path
- local fallback drafts

### 3. Task Market Automation
- market scan
- allowlist policy
- promotion-first automation
- manual deferral for high-risk interaction tasks

### 4. Agent Compatibility
- Hermes-compatible
- Codex-compatible
- Claude Code compatible
- generic shell/CI compatible

## Design Principles

- Draft-first by default: do not treat draft staging as public publishing.
- Same-track learning before generation: prefer reference-style extraction over generic prompting.
- Trend-aware planning: every draft should know whether it is emerging, hot, or viral-candidate content.
- Agent-neutral packaging: no code path should require one specific agent runtime.
- Clean distribution: the local/GitHub project must remain publishable without private infrastructure data.

## Current Project Structure

- `content_platform/`
  - workflow engine
  - generator
  - trend ranking
  - task-market automation
  - publisher adapters
  - readiness inspection
- `skills/content/content-copywriting-style/`
  - default copywriting and visual-style rules
- `tests/`
  - regression and behavior tests
- `systemd/`
  - deployment templates
- `scripts/install.py`
  - generic bootstrap installer
- `docs/`
  - this file plus installation and future handoff material

## What Is Already Implemented

- `content_platform` workflow engine
- `AiToEarnDraftPublisher`
- `AiToEarnFlowPublisher`
- `SocialAutoUploadPublisher`
- `TaskMarketRunner`
- `delivery-readiness` command
- content intelligence module with:
  - trend-stage labeling
  - same-track reference analysis
  - fallback to local trend cache when explicit references are absent
  - image/video prompt generation
  - `draft_meta` persistence
- `content-copywriting-style` skill upgraded with default generation rules
- generic install bootstrap:
  - OS detection
  - Python detection
  - common agent CLI detection
  - clean config rendering
  - installation report output

## Work Completed In This Packaging Phase

- copied the currently validated workflow engine into a standalone project directory
- removed hard-coded server-specific launch paths from repository-facing defaults
- added generic path helpers for:
  - install root
  - style-guide path
  - trend-cache path
  - optional social-auto-upload path
  - browser-profile checks
- added a publishable `pyproject.toml`
- added `.gitignore` rules that keep secrets, cookies, logs, and local runtime data out of sync
- added install entrypoints:
  - `scripts/install.py`
  - `install.ps1`
  - `install.sh`

## Verified State

- Local full test suite passed before packaging.
- Packaged project test suite passed after packaging changes.
- Hermes server runtime remained functional during earlier validation.
- The packaged repo is privacy-clean by design and uses generic default paths.
- Installer executed successfully and produced an installation report with detected agent CLIs.

## Validation Evidence

- Packaged project tests: `57/57` passed locally.
- Packaged installer output confirmed:
  - Python version
  - OS
  - detected agents
  - install root
  - rendered config path
- No residual server IPs, passwords, tokens, SSH key paths, or private backup paths remained in the packaged repository scan.

## Packaging Notes

This repository is the clean distribution layer.
It intentionally does not bundle:
- real production secrets
- real account cookies
- real server-only config
- user-private OneDrive-only assumptions
- real server IPs
- private SSH material
- private agent runtime logs

## Recommended Next Steps

1. Create and push the clean GitHub repository for this packaged project.
2. Sync this same directory to the OneDrive project path used by collaborators.
3. Store a clean server-side mirror of this same project directory for Hermes-side reference and future diffs.
4. Add GitHub Actions for tests and packaging checks.
5. Add article-sync integration path for long-form domestic text platforms.
6. Add browser session bootstrap helpers for optional upload tools.
7. Continue appending real implementation and validation evidence here after every development wave.
