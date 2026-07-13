# Installation Guide

[中文](INSTALL.md) | [English](INSTALL.en.md)

Version: `0.2`

## 1. Short Path

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform project-audit
```

## 2. Before Installation

Confirm:

- Python 3.11+
- whether Hermes CLI is available
- whether an OpenAI-compatible API is available
- whether media scripts already exist
- whether this is a dry-run environment or a real delivery environment

## 3. Environment Variables

- `CONTENT_PLATFORM_HOME`
- `CONTENT_PLATFORM_STYLE_GUIDE`
- `CONTENT_PLATFORM_TREND_CACHE_DIR`
- `SOCIAL_AUTO_UPLOAD_HOME`

## 4. User Decisions

### 4.1 Install Root

Default install root is `.ai-self-media-tools` under the user home directory.

### 4.2 Generation Provider

Choose between:

- Hermes CLI
- OpenAI-compatible provider
- fallback-only mode

### 4.3 Media Scripts

Reserved script paths:

- `external/scripts/image_gen.py`
- `external/scripts/video_pipeline.py`
- `external/scripts/ocr_pipeline.py`
- `external/scripts/transcribe_pipeline.py`
- `external/scripts/multimodal_analyze.py`

### 4.4 Delivery Mode

Recommended default:

- file drafts first
- real publishers later

### 4.5 Notification Mode

Choose whether to use:

- local log only
- Hermes notify
- Telegram / webhook

### 4.6 Management Console Password

Start the console with:

```bash
python -m content_platform admin-serve --password "<admin-password>"
```

The command prints a one-time access URL.

The session is browser-session scoped and becomes invalid after browser close.
