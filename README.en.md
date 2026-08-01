# AI Self-Media Tools

[中文](README.md) | Current version: `1.0.0`

AI Self-Media Tools is a workflow toolkit for AI-assisted self-media operations. It connects operations analysis, topic planning, content generation, image/video production, quality gates, draft/publish validation, and performance review into one auditable process.

The project is safe to share as source code, but each operator must use their own accounts, cookies, proxies, API keys, and runtime data. This repository contains public code, rules, example configuration, and workflow tools only. It does not include the maintainer's private account state or generated works.

## Core Capabilities

- Operations strategy: account stage, niche positioning, same-lane references, cross-platform trends, and historical performance review.
- Content generation: articles, image-text posts, knowledge cards, short-video scripts, titles, body copy, topics, SEO, and GEO.
- Visual and video workflow: knowledge cards, real material matching, captions, voice-over, BGM, and vertical-video quality gates.
- Platform adaptation: WeChat Official Account, Kuaishou, Douyin, Video Channels, Bilibili, Xiaohongshu, Toutiao, Juejin, Zhihu, and extension channels.
- Delivery safety: draft/manual-handoff first; unattended publishing must pass health checks, content quality gates, asset-license checks, and postchecks.
- Feedback loop: views, engagement, saves, follows, completion rate, three-second view rate, average watch time, and platform-specific metrics.

## Who It Is For

- Operators who want AI-assisted multi-platform content workflows.
- Builders who want repeatable content production and publishing rules.
- Agent users who want Hermes, Codex, Claude Code, OpenCode, or similar agents to call a structured content toolchain.
- Beginners who want to start with local drafts and manual publishing before enabling automation.

## Installation

Python 3.11 or newer is required.

```bash
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
pip install -r requirements.txt
pip install -e .
```

Initialize and verify:

```bash
python -m content_platform init
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## Beginner Onboarding Wizard

For non-technical users, start with the guided onboarding script. It does not print or upload cookie plaintext. It guides the operator through Python checks, local configuration, runtime folders, platform binding choices, and tool matching.

```bash
python scripts/onboard_operator.py
```

Check current status only:

```bash
python scripts/onboard_operator.py --check
```

Create a local config file:

```bash
python scripts/onboard_operator.py --write-config
```

Show platform-specific binding guidance:

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform douyin
python scripts/onboard_operator.py --platform shipinhao
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform toutiao
python scripts/onboard_operator.py --platform juejin
python scripts/onboard_operator.py --platform zhihu
```

## Platform Modes

| Platform | Default mode | Notes |
| --- | --- | --- |
| WeChat Official Account | Draft/API or Hermes adapter | Long-form articles, knowledge cards, GitHub picks, trend articles |
| Kuaishou | Automated workflow + postcheck | Knowledge-card video and real-material short video |
| Douyin | Manual review package | Generate complete package; operator publishes manually |
| Video Channels | Manual review package | Generate video, title, body, cover, and topics for operator review |
| Bilibili | Draft/file package/extension uploader | Tutorial and knowledge videos |
| Xiaohongshu | Manual review package | Image-text, knowledge blocks, and short-video combinations |
| Toutiao | Draft/article package | Developed image-text articles |
| Juejin | Draft/article package | Technical articles and open-source project analysis |
| Zhihu | Draft/article package | Deep answers, tradeoff analysis, and experience reviews |

## Configuration Rules

Copy the example config:

```bash
cp config.example.json config.json
```

Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
```

Fill in only your own values. Never commit or share:

- `config.json`
- `.env`, `.env.*`
- `data/`
- `secrets/`
- `cookies/`
- `logs/`
- `artifacts/`
- `outbox/`
- `.codex-server-runtime/`
- any database, screenshot, generated video, publish record, platform cookie, browser profile, API key, or proxy node

## Sharing With Friends

Do not zip your working directory. Generate a clean public bundle:

```bash
python scripts/release_bundle.py --target /tmp/ai-self-media-tools-public
```

Windows PowerShell:

```powershell
python scripts\release_bundle.py --target C:\Temp\ai-self-media-tools-public
```

Share only the generated `ai-self-media-tools-public` directory. See [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md).

## Common Commands

```bash
python -m content_platform health
python -m content_platform delivery-readiness
python -m content_platform health-refresh
python -m content_platform feedback-summary
python -m content_platform admin-serve --password "your-password"
```

## Pre-Publish Validation

Before real publishing, run:

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## License

MIT
