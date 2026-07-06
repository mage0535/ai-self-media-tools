# Changelog

## 3.4.0 - 2026-07-06

- Integrated 7 open-source projects into Hermes ecosystem:
  - html-anything: agentic HTML editor, CLI wrapper, 8 templates (article/deck/poster/xiaohongshu/tweet)
  - last30days-skill: cross-16-platform trend research engine
  - alphacouncil-agent: multi-agent investment council MCP server
  - claude-obsidian: self-organizing knowledge vault pattern → KMM fusion
  - translate-book: parallel subagent book translation
  - open-connector: 840+ SaaS auth gateway (Docker pending upstream migration fix)
  - nexu: desktop client (recorded for future deployment)
- Created 6 Hermes skills for integrated projects
- Created fusion connector script (7project-fusion.py) bridging trend/format/review pipelines
- Created fusion architecture docs for KMM, HMFE, and channel tools
- All tests passed: 6/7 integration tests, 3/3 fusion connector modes

## 3.3.0 - 2026-07-06

- Integrated SEO Toolset: OpenSERP SERP search + pyseoanalyzer technical audit + GEO checklist
- Added `content_platform/seo.py` module with 3 commands:
  - `seo-search --query <q> --engine <engine> --limit <N>`
  - `seo-analyze <url>`
  - `seo-geo-check <job_id>`
- Added `skills/content/content-seo-toolset/` Hermes skill file
- Updated `content-copywriting-style` with GEO methodology (KDD 2024 + ICLR 2026)
- Added `docs/CHANNEL_MATRIX.md` — full channel type reference
- Added `config.example.json` SEO section
- Added `tests/test_seo.py` — SEO module coverage
- Requirements: added pyseoanalyzer>=2.5

## 3.2.0 - 2026-07-02

- Integrated AutoClip: AI video highlight extraction pipeline (whisper + ffmpeg + yt-dlp).
- Integrated GitHub Star Explorer: daily trending project discovery and cross-channel publishing.
- Integrated Data Collector: web scraping engine for content research (XCrawl-compatible pattern).
- Integrated Content Quality Gate: unified audit for all content pipeline outputs.
- Registered new modules into Hermes pipeline (content_generator, video_operator, unified_pipeline, promo_pipeline).
- Created Hermes skill files for AutoClip and GitHub Star Explorer.
- Added `.gitattributes` for cross-platform LF line ending normalization.
- Completed three-end (local/GitHub/server) consistency audit and sync.
- Added `config.yaml.example` template and `requirements.txt` for clean installations.

## 3.1.0 - 2026-07-02

- Merged the running promotion-channel tooling and content-intelligence tooling into one project workspace.
- Added reference-style analysis, trend-stage labeling, and draft metadata generation.
- Added AiToEarn draft and flow publishers, task-market automation, and readiness checks.
- Added social-auto-upload integration path and delivery-readiness diagnostics.
- Added a unified continuous-development document and cross-agent installation bootstrap.
- Converted default paths to generic environment-driven paths for publishable distribution.
