# AI Self-Media Tools

[中文](README.md) | Current version: `1.0.0`

AI Self-Media Tools is a multi-platform content operations toolkit for self-media operators and AI agents. It connects account analytics, growth strategy, topic planning, article/video generation, asset licensing, quality gates, draft or handoff delivery, publishing checks, and performance review into an auditable workflow.

This public repository contains source code, rules, example configuration, and helper scripts only. It does not include the maintainer's cookies, browser state, API keys, proxy nodes, account data, generated works, screenshots, logs, or databases. Every operator must bind their own accounts and runtime data.

## What It Solves

- Multi-platform work often reuses the same topic, template, BGM, and video file.
- Content lacks hooks, useful detail, real visual matching, and clear CTA.
- Videos may have no BGM, BGM may bury the voice, subtitles may block the subject, or visuals may not match the script.
- Uploaders may report success while the platform backend contains no draft or work.
- Private cookies, analytics, and generated works can accidentally leak into the project folder.

The goal is not "one-click spam". The goal is operations-first content production with executable gates and visible evidence.

## Workflow

1. Account and niche analysis: platform rules, historical metrics, account state, and positioning.
2. Trend and topic planning: platform data, same-lane accounts, external trend sources, and dedup history.
3. Content planning: quantity, format, title, hook, script, asset needs, cover, and schedule.
4. Content generation: articles, notes, knowledge cards, scripts, titles, captions, tags, SEO, and GEO.
5. Media production: real or compliant generated assets, knowledge cards, voice-over, subtitles, BGM, covers, and final video files.
6. Quality gates: preflight, recipes, tool invocation evidence, licenses, BGM fingerprint, subtitles, duplication, and platform format.
7. Draft or handoff: platform draft, scheduled post, postcheck, or manual publishing package.
8. Performance review: views, reads, likes, comments, saves, shares, follows, completion rate, 3-second rate, and average watch time.

## Enforced Contract Layer

Current builds turn rules into code-level gates:

- `preflight_manifest`: proves that rules, strategy, asset needs, and publishing constraints were loaded.
- `content_recipe`: required for articles, notes, and knowledge-card packages; records structure, visual binding, variation, first-screen promise, payoff schedule, and 7-day fatigue checks.
- `visual_recipe`: required for videos; records template family, effect modules, scene-to-asset matching, visual differentiation, and anti-reuse identity.
- `tool_invocation_manifest`: required evidence of planned and invoked tools.
- BGM gate: requires real online instrument music with source, license, and fingerprint; rejects silence, synthetic fallback, and duplicates.
- Media delivery gate: video and cover handoff must be sent as separate `MEDIA:<absolute_path>` messages, never appended to a long report tail.

## Platform Scope

Domestic platforms:

| Platform | Default mode | Content types |
| --- | --- | --- |
| WeChat Official Account | Draft/API/Hermes adapter | Long articles, GitHub picks, trend articles, knowledge cards |
| Kuaishou | Automated upload + postcheck | Knowledge-card videos, real-material shorts, microcases |
| Bilibili | Manual handoff | 16:9 tutorials, knowledge videos, case videos |
| Zhihu | Draft/article package | Deep answers, opinion analysis, experience reviews |
| Juejin | Draft/article package | Technical articles, open-source project reviews, engineering notes |
| Douyin | Manual handoff | TikTok localized reposts, pet content, short videos |
| WeChat Video Channels | Manual handoff | WeChat-ecosystem shorts, knowledge cards, case videos |
| Xiaohongshu / RedNote | Manual handoff | Notes, knowledge blocks, short-video mix |

International platforms:

| Platform | Default mode | Content types |
| --- | --- | --- |
| X/Twitter | Automated or draft, depending on config | Short posts, links, growth experiments |
| YouTube | Manual handoff | Shorts, landscape tutorials, knowledge videos |
| TikTok | Manual handoff | Hot material analysis, localized short videos |
| Dev.to | Draft/API | English technical articles |
| Bluesky / Mastodon / Nostr | API or draft | Short posts and link sharing |

Baijiahao and Toutiao are not part of the current main workflow.

## Installation

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

Basic validation:

```bash
python -m content_platform.cli project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## Beginner Onboarding

Run:

```bash
python scripts/onboard_operator.py
```

Status check only:

```bash
python scripts/onboard_operator.py --check
```

Single-platform guide:

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform youtube
python scripts/onboard_operator.py --platform tiktok
```

## Useful Commands

```bash
# Privacy and release audit
python -m content_platform.cli project-audit

# Channel rule validation
python scripts/validate_channel_rulebook.py

# Free image provider smoke test without printing secrets
python scripts/smoke_image_provider.py --providers pollinations,cloudflare,auto

# Visual recipe validation
python scripts/validate_visual_recipe.py --recipe /path/to/visual_recipe.json

# BGM fingerprint gate
python scripts/check_bgm_uniqueness.py /path/to/render_dir --platform kuaishou

# Platform topic independence gate
python scripts/check_platform_topic_independence.py 20260807 --platforms wechat,kuaishou,bilibili

# Send media as separate Hermes messages; target comes from HERMES_DELIVERY_TARGET
python scripts/deliver_media.py "video handoff" /path/to/final.mp4 /path/to/cover.jpg
```

## Privacy Boundary

Do not commit or share:

- `config.json`
- `.env`, `secrets/`
- `data/`
- `cookies/`
- `logs/`
- `artifacts/`
- browser profiles
- account screenshots, generated works, databases, publish records
- cookies, API keys, tokens, proxy nodes

When sharing with friends, share the GitHub repository or a clean public release bundle only. See [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md).

## Hermes / Agent Usage

Before an automated run, Hermes or another agent should:

1. Load the fixed account growth strategy.
2. Run `performance-cycle` and refresh real platform data.
3. Check `capability_status` through MCP or project tooling.
4. Build an independent `platform_source_matrix` for every platform.
5. Ensure each package contains `preflight_manifest`, `content_recipe` or `visual_recipe`, and `tool_invocation_manifest`.
6. Run postcheck for automated platforms; use `handoff_pending` for manual platforms.

If a gate fails, repair and rerun. If repeated repair fails, mark the platform `blocked`. Do not bypass gates.

## Development Validation

```bash
python -m py_compile content_platform/content_recipe.py content_platform/video_recipe.py scripts/mix_bgm_with_gate.py
pytest -q
python -m content_platform.cli project-audit
python scripts/validate_channel_rulebook.py
```

## License and Compliance

You are responsible for complying with each platform's rules and every asset license. This project does not grant rights to third-party media, music, accounts, or platform APIs.
