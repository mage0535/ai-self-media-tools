---
name: content-github-star-explorer
description: GitHub Star Explorer - daily trending project discovery and cross-channel promotion
category: content
trigger_keywords: [github-star, star-explorer, trending, open-source-discovery]
---

## GitHub Star Explorer

Discovers trending GitHub projects daily and generates promotional content for cross-channel distribution.

### Usage

```python
from github_star_explorer import daily_pick, fetch_trending

# Get daily top project
result = daily_pick(lang="zh")
# result["project"] - project details (name, stars, description)
# result["content"] - generated promo content

# Get raw trending list
projects = fetch_trending()
```

### CLI

```bash
python github_star_explorer.py --lang zh
python github_star_explorer.py --lang en
```

### Pipeline Integration

- unified_pipeline.py: `github_stars` channel with `use_github_explorer: True`
- promo_pipeline.py: GitHub trending data injected as context before content generation
- Content template: `github-star-explorer` key in CONTENT_TEMPLATES_V2 (en/zh)

### Quality Gate

Projects must have 10+ stars and meaningful description. Validated by `content_quality_gate.py`.

### API Rate Limits

GitHub API has a rate limit of 60 requests/hour unauthenticated. Set `GITHUB_TOKEN` environment variable for 5000 requests/hour.
