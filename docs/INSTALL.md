# Install

## Supported Environments

- Windows PowerShell
- Linux shell
- macOS shell
- Hermes agent runtime
- Codex / Claude Code / OpenClaw style agent environments

## Quick Install

```bash
python scripts/install.py
```

The installer will:
- detect OS
- detect Python
- detect git and optional gh
- detect common agent CLIs
- create a local install root
- render a clean `config.json` from the template
- prepare external script directories for image / video / OCR / transcription / analysis adapters
- emit an installation report

## Environment Variables

- `CONTENT_PLATFORM_HOME`
- `CONTENT_PLATFORM_STYLE_GUIDE`
- `CONTENT_PLATFORM_TREND_CACHE_DIR`
- `SOCIAL_AUTO_UPLOAD_HOME`

## Post-Install Checks

```bash
python -m content_platform content-readiness
python -m content_platform project-audit
```

## Export Clean Mirror Bundle

```bash
python scripts/release_bundle.py --target /path/to/exported-bundle
```
