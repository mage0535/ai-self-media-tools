# AI Self-Media Tools 1.0.0

This is the first public-ready release intended for operators other than the original maintainer.

## Highlights

- Public-safe sharing workflow through `scripts/release_bundle.py`.
- Beginner installer through `install.ps1`, `install.sh`, and `scripts/install.py`.
- Beginner onboarding wizard through `scripts/onboard_operator.py`.
- Expanded Chinese and English GitHub README files modeled after a public-release structure: what it is, why it exists, how it works, requirements, install modes, platform matrix, validation, troubleshooting, and privacy boundaries.
- Platform-by-platform setup guidance for domestic channels: WeChat, Kuaishou, Douyin, Video Channels, Bilibili, Xiaohongshu, Toutiao, Juejin, and Zhihu.
- Platform-by-platform setup guidance for international channels: YouTube, TikTok, Reddit, Dev.to, Telegraph, Mastodon, Bluesky, Nostr, Write.as, Buttondown, LinkedIn, and X/Twitter.
- Growth review loop with saves, follows, completion rate, three-second view rate, average watch time, and platform-specific metrics.
- Stronger quality gates for article packets, visual workflows, video artifacts, and preflight manifests.
- Draft/manual-handoff defaults for sensitive platforms where unattended publishing should not be assumed.
- Public bundle audit that excludes cookies, private config, runtime databases, logs, generated works, screenshots, and browser state.

## Recommended Setup

```bash
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
pip install -r requirements.txt
pip install -e .
python scripts/onboard_operator.py
```

Beginner install scripts:

```bash
./install.sh
python scripts/install.py --mode check
python scripts/install.py --mode config-only
```

Windows:

```powershell
.\install.ps1
python scripts\install.py --mode check
python scripts\install.py --mode config-only
```

For a privacy-safe distributable copy:

```bash
python scripts/release_bundle.py --target /tmp/ai-self-media-tools-public
```

## Privacy Boundary

This release does not include the maintainer's cookies, account data, generated works, logs, private databases, browser profiles, API keys, or proxy nodes. Each operator must configure their own runtime state.

Do not commit or share:

- `config.json`
- `.env` or `.env.*`
- `data/`
- `secrets/`
- `cookies/`
- `logs/`
- `artifacts/`
- `outbox/`
- `.codex-server-runtime/`
- platform screenshots, generated videos, publish manifests, and account analytics exports

## Verification

Before using any real publishing workflow:

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```
