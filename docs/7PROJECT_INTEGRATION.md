# 7-Project Integration - 2026-07-06

## Integrated Projects

| # | Project | Status | Category | Integration Method |
|---|---------|--------|----------|-------------------|
| 1 | `html-anything` | active | content formatting | CLI wrapper |
| 2 | `last30days-skill` | active | trend discovery | CLI wrapper |
| 3 | `open-connector` | pending | auth gateway | Docker, pending upstream fix |
| 4 | `alphacouncil-agent` | active | multi-agent analysis | MCP server registration |
| 5 | `claude-obsidian` | active | knowledge pattern | pattern extraction |
| 6 | `translate-book` | active | translation | pip install and CLI wrapper |
| 7 | `nexu` | recorded | desktop client | future evaluation |

## Hermes Skill Layer

This project can optionally consume Hermes-hosted skills and helper scripts when they are present in the local Hermes home.
These integrations are additive only. They do not replace the repository's own `generator.py` or `intelligence.py`.

Reference locations are expected under:

- `${HERMES_HOME:-~/.hermes}/skills/...`
- `${HERMES_HOME:-~/.hermes}/scripts/...`

## Fusion References

Typical optional companion artifacts:

- `${HERMES_HOME:-~/.hermes}/scripts/7project-fusion.py`
- `${HERMES_HOME:-~/.hermes}/docs/7project-fusion-architecture.md`
- `${HERMES_HOME:-~/.hermes}/docs/7project-hmfe-fusion.md`
- `${HERMES_HOME:-~/.hermes}/docs/7project-channel-fusion.md`

## Fusion Pipeline

```text
last30days trend data       -> promo pipeline discovery
html-anything formatting    -> channel export
alphacouncil review         -> quality audit
claude-obsidian knowledge   -> retrieval cache
translate-book translation  -> multilingual publishing
open-connector auth layer   -> credential unification (pending)
```

## Notes

- Keep repository docs agent-neutral and path-neutral.
- Do not record machine-specific absolute paths in tracked files.
- Runtime-only Hermes details belong in ignored local notes or deployment records, not in the publishable repo.
