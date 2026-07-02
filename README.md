# AI Self-Media Tools

A clean, publishable, agent-neutral toolkit for AI-assisted self-media operations.

It combines:
- content intelligence and copywriting generation
- trend collection and topic scoring
- draft-first domestic distribution orchestration
- AiToEarn task-market automation
- optional browser-based publisher integrations

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
python -m content_platform delivery-readiness
```

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
