# 7-Project Integration — 2026-07-06

## Integrated Projects

| # | Project | Status | Category | Integration Method |
|---|---------|--------|----------|-------------------|
| 1 | **html-anything** (nexu-io, 7.5k★) | ✅ | Content Formatting | CLI wrapper `/usr/local/bin/html-anything` |
| 2 | **last30days-skill** (mvanhorn, 10.6k★) | ✅ | Trend Discovery | CLI wrapper `/usr/local/bin/last30days` |
| 3 | **open-connector** (oomol-lab) | ⚠️ | Auth Gateway | Docker (port conflict), needs upstream migration fix |
| 4 | **alphacouncil-agent** (Zhao73) | ✅ | Multi-Agent Analysis | MCP server registered (lazy start) |
| 5 | **claude-obsidian** (AgriciDaniel, 8.5k★) | ✅ | Knowledge Pattern | Pattern extracted → KMM fusion doc |
| 6 | **translate-book** (deusyu) | ✅ | Translation | pip install, CLI wrapper |
| 7 | **nexu** (nexu-io, 3.2k★) | 📝 | Desktop Client | Recorded for future desktop deployment |

> **🧩 Hermes Skills 增强层（非独立项目）**：`content_gen_fusion.py` 可调用 Hermes 内置的写作/配图/审校/数据采集技能扩增项目一的内容生成能力。详见本目录 `CONTENT_GEN_ENHANCEMENT.md`。该层为可选增强，不替代项目一自有的 `generator.py`/`intelligence.py`。|

## Hermes Skills Created

- `/root/.hermes/skills/content/html-anything/SKILL.md`
- `/root/.hermes/skills/last30days/SKILL.md`
- `/root/.hermes/skills/open-connector/SKILL.md`
- `/root/.hermes/skills/investment/alphacouncil-agent/SKILL.md`
- `/root/.hermes/skills/knowledge/claude-obsidian/SKILL.md`
- `/root/.hermes/skills/content/translate-book/SKILL.md`

## Fusion Scripts

- `/root/.hermes/scripts/7project-fusion.py` — Unified fusion connector (trend/format/review/all modes)
- `/root/hermes-7project-fusion-architecture.md` — Architecture blueprint
- `/root/hermes-7project-hmfe-fusion.md` — HMFE stock strategy fusion
- `/root/hermes-7project-channel-fusion.md` — Channel tools fusion
- `/root/hermes-memory-installer/docs/CLAUDE_OBSIDIAN_FUSION.md` — KMM fusion

## Fusion Pipeline

```
last30days (trend)              → promo_pipeline content discovery
html-anything (format)          → channel_matrix WeChat/X/Zhihu export
alphacouncil-agent (review)     → quality_review multi-agent audit
claude-obsidian (knowledge)     → KMM hot cache + hybrid retrieval
translate-book (translation)    → multi-language publish
open-connector (auth)           → working_credentials unification (pending)
```

## Test Results

| Test | Result |
|------|--------|
| html-anything markdown→HTML | ✅ 1959B proper HTML |
| last30days mock research | ✅ 40992 chars trend data |
| alphacouncil MCP registration | ✅ lazy start registered |
| OpenDesign (existing) | ✅ running on :7456 |
| Fusion connector: trend mode | ✅ trend data saved |
| Fusion connector: format mode | ✅ 2022B HTML output |
| Fusion connector: review mode | ✅ PASS verdict |
| Vibe-Trading MCP (existing) | ✅ registered |
| open-connector Docker | ⚠️ upstream migration bug |
