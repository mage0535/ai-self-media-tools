# AI Self-Media Tools

[中文](README.md) | [English](README.en.md)

Current public version: `0.2`

AI Self-Media Tools is an agent-neutral workflow system for content intelligence, generation, draft-first delivery, platform account management, and operational automation.

It is built around:

- topic discovery
- trend analysis
- same-track references
- topic clustering
- historical performance learning
- content generation
- quality gates
- draft-first delivery
- management-console operations

## Problems It Solves

- too many trend candidates, weak prioritization
- too much reference material, weak structured analysis
- generic AI outputs
- multi-platform account and delivery complexity
- no automatic learning from historical performance

## Core Capabilities Already Implemented

- trend collection and topic ranking
- source normalization, account analysis, and topic clustering
- viral scoring and strategy routing
- humanization and quality gates
- queue-backed draft delivery
- provider abstraction for image / video / OCR / transcription / analysis
- multi-account platform bindings
- one-time-link password-protected management console
- publishable privacy audit

## Management Console

Start it with:

```bash
python -m content_platform admin-serve --password "your-password"
```

The command prints a one-time access URL.

Properties:

- one-time launch link
- password required
- browser-session login
- session invalid after browser close

The console provides:

- global platform overview
- per-platform detail pages
- multi-account binding flow
- account status checks
- latest works, draft/published states, queue and failure panels
- charts on both overview and platform detail pages

## Domestic Browser Publishing Backend

Platforms that require a browser session, such as Douyin, Bilibili, Xiaohongshu, and Kuaishou, should use `social-auto-upload` as the external runtime:

1. Install the external tool under `external/social-auto-upload`, or set `SOCIAL_AUTO_UPLOAD_HOME` to an existing runtime.
2. Log in through that tool. Account files stay in its local `cookies/` directory, such as `douyin_<account>.json` and `bilibili_<account>.json`.
3. Configure each platform in the runtime `config.json` with `type: "social-auto-upload"`.
4. Run `python -m content_platform delivery-readiness` to verify the tool path, Python runtime, CLI startup, and account-file counts.

Example:

```json
{
  "publishers": {
    "platforms": {
      "douyin": {
        "type": "fallback",
        "publishers": [
          {
            "type": "social-auto-upload",
            "platform_name": "douyin",
            "account_name": "<account-alias>"
          },
          {
            "type": "file"
          }
        ]
      },
      "bilibili": {
        "type": "fallback",
        "publishers": [
          {
            "type": "social-auto-upload",
            "platform_name": "bilibili",
            "account_name": "<account-alias>",
            "video_extra_args": ["--tid", "171"]
          },
          {
            "type": "aitoearn-draft",
            "env_file": "secrets/aitoearn.env"
          }
        ]
      }
    }
  }
}
```

To recover or add a Bilibili account:

```bash
cd "$SOCIAL_AUTO_UPLOAD_HOME"
./venv/bin/python sau_cli.py bilibili login --account <account-alias>
./venv/bin/python sau_cli.py bilibili check --account <account-alias>
```

Do not commit cookies, tokens, server paths, or account data. New browser-based channels should follow the same model: external tool implementation plus `platform_name`, `account_name`, and optional `extra_args` configuration. During rollout, use `type: "fallback"` to keep an older backend available while the new browser backend is being validated.

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
python -m content_platform admin-serve --password "your-password"
```

## Version Note

The public baseline version is unified as `0.2`.

Older `v3.x` labels inside the continuous-development log are internal development-wave labels, not the current public version.
