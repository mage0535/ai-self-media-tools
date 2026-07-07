---
name: content-open-notebook
description: Integrate Open Notebook style deep research into the content pipeline.
trigger_keywords: [open-notebook, deep research, notebook research]
category: content
---

# Open Notebook Integration

## Purpose

This skill connects an Open Notebook compatible service to the content pipeline for:

- source digestion from URLs or text
- multi-source topic research
- optional enrichment inside `build_generation_context()`

## Preconditions

The Open Notebook service must already be running in a local deployment chosen by the operator.
Do not hardcode machine-specific install paths in tracked files.

Example health check:

```bash
python -m scripts.open_notebook_integrator health
```

## CLI Usage

```bash
python -m scripts.open_notebook_integrator digest --url https://example.com/article --title "Article Title" --topic "tech"
python -m scripts.open_notebook_integrator digest --text "Source content" --topic "text-analysis"
python -m scripts.open_notebook_integrator research --topic "AI Agents" --urls "https://a.com" "https://b.com"
```

## Python Usage

```python
from scripts.open_notebook_integrator import digest_source, research_topic

result = digest_source(
    url="https://example.com/article",
    title="Article Title",
    topic="tech",
)

result = research_topic(
    topic="AI Agents",
    urls=["https://a.com", "https://b.com"],
    texts=["supplemental notes"],
)
```

## Pipeline Hook

`content_platform.intelligence.build_generation_context()` can include Open Notebook research when `deep_research=True`.

## API Notes

Default API endpoint:

- `http://<open-notebook-host>`

Typical endpoints:

- `/health`
- `/api/notebooks`
- `/api/sources`
- `/api/search`
- `/api/search/ask`
- `/api/notes`

## Quality Notes

- service health is checked before deep calls
- non-fatal downstream errors should degrade gracefully
- `ToolRegistry.probe()` should expose `open_notebook`
