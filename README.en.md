# AI Self-Media Tools

[中文](README.md) | [English](README.en.md)

Current public version: `0.1`

AI Self-Media Tools is a publishable, continuously developed, agent-neutral workflow system for self-media content research, generation, draft distribution, and automation.

This is not just a “copywriting script”. It is a full workflow around topic discovery, same-track analysis, content generation, media artifacts, draft-first delivery, task-market automation, and historical learning.

## What Problem It Solves

- Find topics worth producing from trends and same-track content
- Match topics to the right content form and platform
- Improve generated outputs with style signals and quality gates
- Distribute outputs as stable drafts instead of risky direct publishing
- Learn from historical performance over repeated runs

## Core Capabilities Already Implemented

- trend collection and ranking
- source normalization, account analysis, and topic clustering
- viral scoring and strategy routing
- humanization and quality gates
- provider abstraction for image / video / OCR / transcription / analysis
- queue-backed draft delivery
- AiToEarn automation foundation
- publishable privacy audit
- cross-agent install and operation

## Documentation

- [Project Guide (Chinese)](docs/PROJECT_GUIDE.zh.md)
- [Project Guide (English)](docs/PROJECT_GUIDE.en.md)
- [Installation Guide (Chinese)](docs/INSTALL.md)
- [Installation Guide (English)](docs/INSTALL.en.md)
- [Acknowledgements](docs/ACKNOWLEDGEMENTS.md)
- [Continuous Development Log](docs/CONTINUOUS_DEVELOPMENT.md)

## Quick Start

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform analyze-topic --topic "AI workflows" --brief "{\"platforms\":[\"wechat\",\"douyin\"]}"
```

## Version Note

The public baseline version is unified as `0.1`.

Older `v3.x` labels still appear inside historical development notes. Those are internal development-wave labels, not the current public version.
