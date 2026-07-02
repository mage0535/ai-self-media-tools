# AI Self-Media Tools

A clean, publishable, agent-neutral toolkit for AI-assisted self-media operations.

It combines:
- content intelligence and copywriting generation
- trend collection and topic scoring
- niche/account analysis and viral candidate routing
- anti-generic rewrite and quality scoring
- draft-first domestic distribution orchestration
- AiToEarn task-market automation
- optional browser-based publisher integrations
- content-tool readiness, tool registry, and project purity audit

## Project Goals

- Keep all code, install helpers, docs, templates, and skill rules under one syncable directory.
- Remain compatible with multiple agent runtimes, including Hermes, Codex, Claude Code, OpenClaw, and generic shell-driven agents.
- Use draft-first delivery by default. Human final review happens in platform draft boxes or required handoff flows.
- Never publish private credentials, server information, user-specific account data, cookies, or environment secrets into the repository.

## Main Components

- `content_platform/` ? Python workflow engine
- `skills/` ? reusable style and prompt rules
- `tests/` ? regression and behavior coverage
- `systemd/` ? deployment templates
- `scripts/install.py` ? cross-platform bootstrap installer
- `docs/CONTINUOUS_DEVELOPMENT.md` ? single source of truth for ongoing work

## Quick Start

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform trends --limit 5
python -m content_platform analyze-topic --topic "AI workflows" --brief "{\"platforms\":[\"douyin\"]}"
python -m content_platform account-report --topic "AI workflows" --brief "{\"reference_posts\":[]}"
python -m content_platform content-readiness
python -m content_platform feedback-summary
python -m content_platform project-audit
python -m content_platform delivery-readiness
```

## Current Content Intelligence Features

- Normalized source ingestion from briefs, source URLs, and trend-cache references
- Same-track niche analysis with account counts, style signatures, and platform distribution
- Interpretable viral scoring with trend, utility, visual promise, platform fit, and historical feedback signals
- Content-form routing for long article, social note, image carousel, and short video
- Draft metadata enriched with strategy, media plan, rewrite notes, and quality scores
- Tool registry for image/video scripts, OCR, transcription, and multimodal analysis adapters

## Clean Publishable Rule

The local repo, GitHub repo, and Hermes server mirror must stay aligned and publishable.
Use `python -m content_platform project-audit` to run a local privacy/purity scan before syncing or publishing changes.

## Privacy Rule

This repository must stay clean:
- no SSH keys
- no passwords
- no tokens
- no cookies
- no real server IPs
- no user-private absolute paths
- no production-only secret config files

Use templates and local ignored files for all runtime secrets.
