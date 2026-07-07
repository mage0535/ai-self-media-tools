# Content Generation Enhancement Layer

## Purpose

This repository has a built-in content pipeline.
When a Hermes environment is available, it can optionally call extra skill-based tooling for research, writing, review, and media planning.

## Base Mode

Use the repository's own workflow:

```bash
python -m content_platform trends --limit 5
python -m content_platform analyze-topic --topic "AI Agent"
```

## Enhanced Mode

If the Hermes companion script exists under the local Hermes home, it can be invoked directly:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --topic "AI Agent" --type article
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --topic "大模型落地" --type video-script
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --list-types
```

## Optional Capabilities

| Capability | Typical Source | Gap It Fills |
|------------|----------------|--------------|
| real-time trend collection | AutoCLI | live hot-topic collection |
| cover and image planning | Hermes image skills | richer visual planning |
| video script drafting | Hermes video skills | platform-native video outlines |
| proofreading and review | Hermes review skills | stronger editorial checks |
| infographic generation | Hermes design skills | structured visual assets |

## Preconditions

- Hermes runtime is installed and reachable.
- Optional Hermes skills exist under `${HERMES_HOME:-~/.hermes}/skills/`.
- AutoCLI browser-dependent features require the local daemon when used.
