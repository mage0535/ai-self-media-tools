# AI Self-Media Tools

[中文](README.md) | Current version: `1.0.0`

AI Self-Media Tools is a multi-platform content operations toolkit for self-media operators and AI agents. It connects account analysis, topic planning, trend collection, content generation, image/video production, quality gates, draft/manual-handoff publishing, and post-publish review into one auditable workflow.

This repository contains public source code, rules, example configuration, and helper scripts only. It does not contain the maintainer's cookies, browser state, API keys, proxy nodes, generated works, logs, or account data. Every operator must configure their own accounts and runtime state.

## What This Is

The project addresses a practical problem: multi-platform content work easily drifts off-lane, becomes repetitive, and reports success without visible evidence.

It is not a "one click spam every platform" script. It is a rule-gated operations system:

1. Analyze the account and platform before deciding topics.
2. Generate reviewable content packages before draft or publish preparation.
3. Require quality, asset-license, privacy, duplication, and platform checks before delivery.
4. Feed performance metrics back into the next content cycle.

## Why It Was Built

When operating multiple channels, these failures appear quickly:

- Every platform gets the same template.
- Content has no hook, no useful detail, and no real visual match.
- Video has captions but no voice, or BGM buries the voice.
- The uploader reports success while the platform backend has no draft.
- Cookies, logs, account data, and generated works leak into the project folder.

This project turns those lessons into executable rules and checks so work starts from operations analysis instead of mechanical copy generation.

## Design Goals

- Draft/manual-handoff first. Real public publishing requires health checks and visible postchecks.
- One strategy per platform, not one recycled template for all channels.
- Articles must include developed copy, hooks, images/knowledge cards, SEO/GEO, and platform adaptation.
- Videos must include clear human-like voice, suitable BGM, lower-third captions, real material matching, and preflight gates.
- Public repositories must stay free of private paths, cookies, account data, and generated works.
- Hermes, Codex, Claude Code, OpenCode, and similar agents can call stable scripts and rulebooks.

## How It Works

1. Account and niche analysis: platform rules, historical data, account state, and positioning.
2. Trend and topic planning: platform trends, competitor references, keyword heat, and dedup history.
3. Content plan: quantity, format, topic angle, script structure, asset requirements, and suggested schedule.
4. Content generation: articles, notes, knowledge cards, scripts, titles, body copy, tags, covers, SEO, and GEO.
5. Media production: real material matching, knowledge-card rendering, voice-over, captions, BGM, covers, and video files.
6. Quality gates: word count, images, licenses, captions, voice, BGM, clarity, platform rules, and duplication.
7. Draft or handoff: platform draft, local package, semi-automatic review package, or manual publishing material.
8. Performance review: views, clicks, saves, comments, follows, completion rate, 3-second view rate, and average watch time.

## Public Release Scope

`v1.0.0` is the first public-ready release for operators other than the original maintainer.

Included:

- Operations strategy, content generation, media quality, channel rulebooks, and pre-publish checks.
- Beginner installer and platform binding wizard.
- Domestic and international platform examples.
- Privacy-safe public bundle tooling.

Not included:

- Maintainer cookies, browser profiles, API keys, proxy nodes.
- Live account analytics, generated works, logs, screenshots, databases, or publish records.
- Private Hermes runtime directories or operator-specific state.

## Requirements

Base requirements:

- Python `3.11+`
- Git
- Windows PowerShell, macOS Terminal, or Linux shell
- Network access

Recommended for video workflows:

- `ffmpeg` for video rendering, subtitles, audio mixing, and validation.
- Playwright browsers for browser-based draft workflows and login-state probes.
- Optional: `yt-dlp`, OCR, TTS, image generation, and stock material retrieval tools.

If you only create article drafts, you can start without the full video toolchain. If you use Kuaishou, Douyin, Video Channels, Bilibili, YouTube, or TikTok, configure `ffmpeg` and browser tooling first.

## Before You Start

Beginners should prepare:

- A GitHub account to download the project.
- Their own platform accounts.
- A private local runtime directory, such as `%USERPROFILE%\.ai-self-media-tools` on Windows.
- A safe place for secrets, such as `.env` or `secrets/provider.env`, never committed to Git.
- A network route that can access the target platform. Domestic and international platforms may need different routes.
- If using Hermes or a server, store cookies, proxies, and browser profiles in private runtime directories, not in this repository.

Do not prepare or send to others:

- Cookie plaintext
- API key plaintext
- Proxy node plaintext
- Browser profiles
- Platform backend screenshots
- Original generated works or account analytics exports

## Quick Start

### Windows PowerShell

```powershell
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
.\install.ps1
python scripts\onboard_operator.py
```

### macOS / Linux

```bash
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
./install.sh
python scripts/onboard_operator.py
```

Run a basic validation after installation:

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## Install Modes

The installer is the recommended beginner entrypoint. It:

1. Checks Python, Git, project location, and optional video tools.
2. Installs Python dependencies and registers the project locally.
3. Creates a private runtime directory, usually `~/.ai-self-media-tools`.
4. Writes an example runtime config without real secrets.
5. Writes `installation-report.json` for humans or agents to inspect.
6. Points the operator to the platform binding wizard.

Common modes:

```bash
python scripts/install.py --mode full
python scripts/install.py --mode check
python scripts/install.py --mode config-only
```

Windows equivalents:

```powershell
python scripts\install.py --mode full
python scripts\install.py --mode check
python scripts\install.py --mode config-only
```

| Mode | What it does | Best for |
| --- | --- | --- |
| `full` | Checks environment, installs dependencies, creates runtime config | First-time setup |
| `check` | Checks only; does not install or write config | Diagnosing a computer |
| `config-only` | Creates runtime folders and example config only | Already configured machines |

If dependency installation fails, run:

```bash
python scripts/install.py --mode check
```

Then fix the missing Python, Git, ffmpeg, or network issue before retrying.

## Beginner Onboarding Wizard

After installation:

```bash
python scripts/onboard_operator.py
```

The wizard guides platform preparation, account binding choices, publishing modes, and validation steps. It never reads, prints, or uploads cookie plaintext.

Status check only:

```bash
python scripts/onboard_operator.py --check
```

Create local `config.json`:

```bash
python scripts/onboard_operator.py --write-config
```

Show one platform guide:

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform douyin
python scripts/onboard_operator.py --platform shipinhao
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform youtube
python scripts/onboard_operator.py --platform tiktok
python scripts/onboard_operator.py --platform reddit
```

## Platform Matrix

Domestic platforms:

| Platform | Default mode | Content types | Notes |
| --- | --- | --- | --- |
| WeChat Official Account | Draft/API or Hermes adapter | Long articles, GitHub picks, trend articles, knowledge cards | Requires AppID/AppSecret or verified adapter |
| Kuaishou | Automated upload + postcheck | Knowledge-card videos, real-material shorts, microcases | Requires preflight, quality gate, and postcheck |
| Douyin | Manual review package | TikTok localized reposts, pet knowledge, short videos | Default: generate complete package; operator publishes manually |
| Video Channels | Manual review package | WeChat-ecosystem shorts, knowledge cards, case videos | Generates title, body, cover, tags, and video package |
| Bilibili | File package/draft/extension uploader | Tutorials, knowledge videos, longer case content | Requires category, cover, tags, captions, and clarity checks |
| Xiaohongshu | Manual review package | Image-text notes, knowledge blocks, short-video mix | Focus on authenticity, save value, and manual publishing |
| Toutiao | Draft/article package | Long-form image-text, trend analysis, experience posts | Next integration target |
| Juejin | Automated article workflow + draft/publish preparation | Technical articles, OSS project analysis, engineering notes | Publisher integrated; requires operator credentials and article quality gates |
| Zhihu | Automated article workflow + draft/publish preparation | Deep answers, opinion analysis, experience reviews | Publisher integrated; requires operator login state and article quality gates |

International platforms:

| Platform | Default mode | Content types | Notes |
| --- | --- | --- | --- |
| YouTube / Shorts | Manual or verified uploader | Shorts, tutorials, knowledge videos | Requires channel login, title, description, tags, cover, and captions |
| TikTok | Material source / manual package | Trend material analysis, shorts, localized edits | Requires international access route and source evidence |
| Reddit | Trend collection + draft package | Community posts, discussion drafts, topic validation | Default: no auto-post; check subreddit rules |
| Dev.to | Draft/API | English technical articles | Good for OSS projects, tutorials, and engineering recaps |
| Telegraph | API/file publish | Lightweight articles | Useful for quick linkable pages |
| Mastodon | API publisher | Short posts and link distribution | Requires instance URL and access token |
| Bluesky | API publisher | Short posts and link distribution | Requires account credentials or app password |
| Nostr | Signed publisher | Decentralized short posts | Private key must stay in private runtime |
| Write.as | API publisher | Lightweight blog posts | Requires API key |
| Buttondown | API publisher | Newsletter | Requires API key |
| LinkedIn / X | Manual or extension publisher | Professional posts, short updates, link distribution | Manual publishing is recommended by default |

## Recommended First Week

Do not bind every platform on day one.

1. Day 1: install, run checks, and create local config.
2. Day 2: generate one manual review package for Xiaohongshu or Douyin.
3. Day 3: configure WeChat draft flow and verify article images/knowledge cards.
4. Day 4: configure one video platform such as Kuaishou or Bilibili.
5. Day 5: start performance review metrics.
6. Day 6+: gradually add international channels or more automation.

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

Share only the generated `ai-self-media-tools-public` directory or the GitHub Release archive. See [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md).

## Validation

Before real publishing:

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

Common checks:

```bash
python -m content_platform health
python -m content_platform delivery-readiness
python -m content_platform health-refresh
python -m content_platform feedback-summary
```

Admin console:

```bash
python -m content_platform admin-serve --password "your-password"
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Python is not found | Install Python 3.11+ and reopen the terminal |
| Dependency install failed | Run `python scripts/install.py --mode check` first |
| Video has no voice or captions | Check `ffmpeg`, then rerun the video quality gate |
| Platform draft is invisible | Verify in the backend draft list or management page, not just API output |
| Cookie expired | Re-login with your own account and store state in private runtime |
| Privacy concern | Run `project-audit`, then use `release_bundle.py` |

## Repository Structure

- `content_platform/`: core strategy, generation, gates, publishers, and review logic.
- `scripts/`: install, validation, media production, quality checks, and publishing helpers.
- `config/`: rulebooks, quality gates, growth strategy, and security config.
- `docs/`: operations rules, release notes, public sharing, and continuous development notes.
- `skills/`: reusable content, visual, and operations skills.
- `tests/`: unit and regression tests.

## Release

- Current release: [v1.0.0](https://github.com/mage0535/ai-self-media-tools/releases/tag/v1.0.0)
- Release notes: [RELEASE_NOTES_1.0.0.md](RELEASE_NOTES_1.0.0.md)
- Public distribution guide: [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md)

## License

MIT.
