# AI Self-Media Tools

**Go beyond "copy writing" — a full-chain agent workflow for topic analysis → content generation → de-AI optimization → multi-platform distribution.**

> 📦 **Positioning**: Content production toolchain for AI coding agents (Hermes / OpenCode / Claude Code / Codex). Not a standalone application, but a content factory orchestrated by agents.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/) [![edge-tts](https://img.shields.io/badge/edge--tts-84%2B%20languages-green)](https://github.com/rany2/edge-tts) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](https://github.com/<github-owner>/<repository>/pulls) [![Version](https://img.shields.io/badge/version-0.2-orange)](.)

**[中文文档](README.md)**

---

## Architecture Overview

```
Input Layer: Content Sources
  ┌────────┐  ┌──────────┐  ┌────────┐  ┌─────────────┐
  │RSS/Atom │  │ OpenSERP │  │GitHub  │  │Manual Brief  │
  │75+ feeds│  │6 search  │  │Trending│  │+ Deep Resear│
  └────┬───┘  └────┬─────┘  └────┬───┘  └──────┬──────┘
       └──────┬────┴─────────────┴──────────────┘
              │
         intelligence.py
  Source Normalization → Niche Analysis → Viral Score
      → Strategy Routing + Open Notebook Deep Research
              │
         generator.py — DraftGenerator v5.0
      Hermes CLI / OpenAI / Fallback (3 modes)
       + Cluster Memory + Historical Performance
              │
     ┌────────┴──────────────────────┐
     │    pipeline.run()              │
     │  G1:Risk → G2:GEO → G3:De-AI  │
     │  → G4:Media → G5:Format Check │
     │  5-Gate Quality Contract       │
     └────────┬──────────────────────┘
              │
         media.py — Media Factory
    ┌──────────┼──────────┐
  image.py   video.py   audio.py
  ComfyUI/   Remotion/  edge-tts/
  QwenImage  AutoClip   Kokoro/Piper
              │
    ┌─────────┴───────────────┐
    │    Distribution Layer    │
    │ 23+ publishers + matrix  │
    │ + Newsletter pipeline    │
    └─────────┬───────────────┘
              │
    ┌─────────┴────┐
    │ Management Console   │
    │ One-time link+passwd │
    │ Calendar · Dashboard  │
    │ MCP Server            │
    └──────────────────────┘
```

---

## Modules

| Module | Directory | Description |
|--------|-----------|-------------|
| **Pipeline Orchestrator** | `content_platform/pipeline.py` | create→generate→risk→compliance→GEO→media→review→publish |
| **Content Intelligence** | `content_platform/intelligence.py` | Trend analysis, niche analysis, viral scoring, strategy routing |
| **Content Generator** | `content_platform/generator.py` | DraftGenerator (Hermes / OpenAI / Fallback) |
| **SEO/GEO** | `content_platform/seo.py` | 7-dim GEO quality check + OpenSERP + pyseoanalyzer |
| **De-AI Optimizer** | `content_platform/humanize.py` | 47 patterns + sycophancy/hedging removal + burstiness + term locking |
| **Multi-Platform Publishing** | `content_platform/publishers.py` | 23+ publishers (WeChat/Douyin/YouTube/LinkedIn/Bilibili, etc.) |
| **Voice Engine** | `scripts/voice_engine.py` | edge-tts 84 languages + Kokoro/Piper offline fallback, de-AI post-processing |
| **Management Console** | `content_platform/admin_server.py` | Overview, detail, binding, task center, GEO trend, dashboard |
| **Content Calendar** | `content_platform/scheduler.py` | Cron-driven scheduling, calendar API |
| **RSS Ingest** | `content_platform/rss_ingest.py` | RSS/Atom feed parsing, source normalization |
| **Newsletter** | `content_platform/newsletter.py` | RSS→curation→HTML email pipeline |
| **MCP Interface** | `content_platform/mcp_server.py` | 8 MCP tools (FastMCP, stdio + SSE) |
| **Content Matrix** | `content_platform/copy_manager.py` | Content rotation scheduling, multi-format adaptation |
| **Delivery Queue** | `content_platform/pipeline.py` | Async delivery queue + generation/delivery workers |
| **Learned Ranking** | `content_platform/trends.py` | Topic clustering + historical performance → trend ranking |

---

## 23+ Publisher Matrix

### 🔴 Domestic Platforms

| Publisher | Type | Auth | Capability |
|-----------|:----:|------|------------|
| **WeChat** | REST API | app_id+secret | Image-text draft (with cover) |
| **Xiaohongshu** | Format | template | Note formatting |
| **Douyin/Kuaishou/Shipinhao** | CLI | cookies | Short video publishing |
| **Bilibili** | REST API | sessdata | Article draft |
| **Cnblogs** | HTTP | connectivity | Connection test |

### 🔵 International Platforms

| Publisher | Type | Auth | Capability |
|-----------|:----:|------|------------|
| **YouTube** | Data API v3 | OAuth refresh | Video chunked upload |
| **LinkedIn** | v2 API | Access Token | Post publishing |
| **Dev.to** | REST API | API Key | Draft creation |
| **Telegraph** | REST API | Token | Page publishing |
| **Mastodon** | ActivityPub | Access Token | Status publishing |
| **Bluesky** | AT Protocol | identifier+password | Post publishing |
| **Nostr** | WebSocket | private key | Relay broadcast |
| **WriteAs** | REST API | Token | Article publishing |
| **GitHub Discussions** | GraphQL | Token | Discussion creation |
| **Buttondown** | REST API | API Key | Email draft |
| **Ayrshare** | Aggregate API | API Key | Multi-platform dispatch |
| **Email (SMTP)** | SMTP | user+password | Newsletter delivery |
| **File** | Local | none | JSON draft export |

### 🟣 AiToEarn

| Publisher | Type | Description |
|-----------|:----:|-------------|
| **AiToEarnDraft** | JSON-RPC | Image/text/video draft creation |
| **AiToEarnFlow** | JSON-RPC | Publish flow orchestration |

---

## Capability Matrix

### GEO Quality Checks (KDD 2024 / ICLR 2026)

| Check | Weight | Detection |
|-------|:------:|-----------|
| Claims with numbers | 2 | ≥3 independent numbers |
| Claims with sources | 2 | URL/reference/"research shows" |
| Authority quotes | 1 | Quote >40 chars / blockquotes |
| Direct answer | 2 | First 200 chars contains Q&A pattern |
| Short paragraphs | 1 | Any paragraph >4 sentences → fail |
| Structured list | 1 | Table or ordered/unordered list |
| FAQ section | 1 | Q markers / A markers / ≥3 question marks |

### De-AI Pipeline (humanize.py)

| Stage | Process | Method |
|:-----:|---------|--------|
| 1 | 30 generic phrase removal | 5 categories (conclusive/transitional/importance/sycophancy/hedging) |
| 2 | 7 sycophancy pattern removal | `I apologize...`, `I understand...` etc. |
| 3 | 6 hedging language replacement | `Perhaps you might consider...` etc. |
| 4 | Em-dash limit | Auto-replace with commas when >4 em-dashes |
| 5 | Burstiness/perplexity injection | Sentence length variance + vocabulary predictability |
| 6 | Term locking | Numbers/URLs/named entities byte-for-byte preserved |
| 7 | Semantic fidelity | Embedding similarity gate ≥0.76 |

### Quality Gate (5-Gate Contract)

| Gate | Check | Pass Standard | Fail Action |
|:----:|-------|:-------------:|-------------|
| G1 | Risk + Compliance | not blocked | Block |
| G2 | GEO quality | ≥40 | Mark + log |
| G3 | Anti-generic | has rewrite | Auto-rewrite |
| G4 | Media assets | depends on form | Non-blocking |
| G5 | Format integrity | payload complete | Non-blocking |

---

## Quick Install

```bash
git clone https://github.com/<github-owner>/<repository>.git
cd ai-self-media-tools

# Run installer
python scripts/install.py
```

The installer automatically:
1. Detects agent environment (Hermes / OpenCode / Claude Code / Codex / Qwen)
2. Renders `config.json`
3. Writes installation report to `~/.ai-self-media-tools/installation-report.json`

---

## Usage Guide

### 1. System Health

```bash
python -m content_platform health
# → {"ok": true, "version": "0.2", "db_state": "initialized"}

python -m content_platform content-readiness
# → {"tools": {"ffmpeg": {...}, "yt-dlp": {...}, ...}}

python -m content_platform project-audit
# → {"ok": true, "scanned_files": 129}
```

### 2. Content Intelligence

```bash
python -m content_platform analyze-topic \
  --topic "AI agents 2026" \
  --brief '{"platforms":["wechat","douyin"],"reference_posts":[{"title":"Title","body":"Content"}]}'

python -m content_platform account-report \
  --topic "AI automation" \
  --brief '{"reference_posts":[{"title":"Title","body":"Content","account_handle":"example_creator","platform":"xiaohongshu"}]}'

python -m content_platform trends
```

### 3. Content Generation & Publishing

```bash
# Create → Generate → Approve → Publish
python -m content_platform create --topic "AI Workflows in Practice" --platform wechat
python -m content_platform run <job_id>
python -m content_platform approve <job_id> --actor "operator"
python -m content_platform publish <job_id>

# Or demo full flow in one command
python -m content_platform demo
```

### 4. Management Console

```bash
python -m content_platform admin-serve --password "<admin-password>"
# Outputs one-time access link → browser → enter password
```

Features:
- Multi-platform overview (published/pending/failed)
- Platform detail (account binding + status + works)
- Task center (run/approve/reject/publish)
- Draft version diff
- GEO trend chart
- Content heatmap
- Failure classification

### 5. SEO / GEO Analysis

```bash
# GEO quality check (file)
python -m content_platform seo-geo-check article.md

# GEO check (stdin)
echo "Your content..." | python -m content_platform seo-geo-check -

# OpenSERP keyword research
python -m content_platform keyword-research "AI trends" --engine google

# SEO page analysis
python -m content_platform seo-analyze https://example.com
```

### 6. RSS Ingest + Scheduling

```bash
python -m content_platform rss-ingest https://hnrss.org/frontpage --topic tech
python -m content_platform schedule-create --topic "AI News" --platform wechat --cron "@daily"
python -m content_platform schedule-list
```

### 7. Newsletter Generation

```bash
python -m content_platform newsletter https://hnrss.org/frontpage --keywords AI agent --max 10
# Outputs HTML to data/newsletters/
```

### 8. Voice Generation

```python
from scripts.voice_engine import VoiceEngine
engine = VoiceEngine("./output")
result = engine.synthesize("Hello, welcome to this tutorial.", lang="en", genre="tech")
# → {"audio": "./output/narration.mp3", "subtitle": "./output/subtitles.srt"}
```

### 9. MCP Interface (for AI Agents)

```bash
# stdio mode (recommended for AI agents)
pip install mcp
python -m content_platform.mcp_server --transport stdio

# SSE mode (HTTP port 9600)
python -m content_platform.mcp_server --transport sse --port 9600
```

Available MCP tools: `seo_geo_check`, `trends_query`, `create_job`, `run_job`, `approve_job`, `publish_job`, `review_status`, `generate_audio`

---

## API Reference

### intelligence.py

| Function | Description |
|----------|-------------|
| `collect_reference_posts(brief, limit)` | Collect same-track reference posts |
| `analyze_reference_posts(posts)` | Style extraction (formats/CTA/openings) |
| `build_generation_context(topic, brief)` | Build full generation context |
| `prompt_brief(topic, brief)` | Serialize to JSON prompt |

### pipeline.py (Pipeline)

| Method | Description |
|--------|-------------|
| `create(topic, platforms, brief)` | Create content job |
| `run(job_id)` | Generate→risk→compliance→GEO→media |
| `approve(job_id, actor, note)` | Approve review |
| `reject(job_id, actor, note)` | Reject review |
| `publish(job_id)` | Publish to platforms |
| `process_delivery_queue(limit)` | Consume delivery queue |
| `process_generation_queue(limit)` | Consume generation queue |

### seo.py

| Function | Description |
|----------|-------------|
| `geo_check(text)` | 7-dim GEO quality check |
| `openserp_search(query)` | OpenSERP keyword research |
| `seo_analyze(url)` | pyseoanalyzer page analysis |
| `format_geo_report(text)` | GEO report formatting |

### voice_engine.py (VoiceEngine)

| Method | Description |
|--------|-------------|
| `synthesize(script_text, lang, genre)` | Synthesize voice narration |
| `parse_script(raw_text)` | Parse dialogue/single scripts |
| `detect_language(text)` | Auto language detection |
| `detect_genre(text, lang)` | Auto genre detection |

### admin_data.py

| Function | Description |
|----------|-------------|
| `build_overview(db_path)` | Console overview |
| `build_platform_detail(db_path, platform)` | Platform detail (with LLM analysis) |
| `build_task_center(db_path)` | Task center |
| `build_task_detail(db_path, job_id)` | Task detail (diff, GEO scores) |
| `build_dashboard(db_path)` | Operations dashboard (KPI/GEO trend/heatmap) |

---

## Changelog

### 0.2 — 2026-07-08

- Phase 1-8 fully implemented
- GEO check integrated into `pipeline.run()` auto-flow, 5-gate quality contract
- Text de-AI fully upgraded (47 patterns/sycophancy/hedging/burstiness/term locking)
- Content calendar + RSS ingestion + Newsletter pipeline + MCP Server
- Operations dashboard (GEO trend/heatmap/failure classification)
- Multi-backend TTS stubs (Piper/Kokoro)
- Management console task center CRUD + version diff
- 157/157 tests passed, three-end consistent

### 0.1 — 2026-07-08

- Public baseline release
- Content intelligence MVP (niche analysis/viral scoring/strategy routing)
- Voice engine (edge-tts 84 languages)
- 23+ platform publishers
- Open Notebook deep research integration
- AiToEarn task market automation
- Topic clustering + historical performance learning + delivery queue

---

## Related Projects

- **[Knowledge-and-Memory-Management](https://github.com/<github-owner>/<related-repository>)** — AI knowledge collection & memory management plugin. 40+ collection tools, SenseNova document engine, 12+ cloud sync, 3-tier knowledge recall.
- **[Hermes Agent](https://github.com/nousresearch/hermes)** — Hermes agent framework
- **[edge-tts](https://github.com/rany2/edge-tts)** — 84+ language TTS engine
- **[Kokoro](https://github.com/hexgrad/kokoro)** — 82M parameter offline TTS

---

## License

MIT License © 2026
