# AI Self-Media Tools 1.0.0

This is the first public-ready release intended for operators other than the original maintainer.

## Highlights

- Public-safe sharing workflow through `scripts/release_bundle.py`.
- Beginner onboarding wizard through `scripts/onboard_operator.py`.
- Clean Chinese and English GitHub README files.
- Platform-by-platform setup guidance for WeChat, Kuaishou, Douyin, Video Channels, Bilibili, Xiaohongshu, Toutiao, Juejin, and Zhihu.
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

