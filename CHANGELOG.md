# Changelog

## 3.5.0 - 2026-07-07 - Hermes Skills 自适应增强

- **skills_adapter 模块**：`content_platform/skills_adapter.py` 桥接 AutoCLI + Hermes Skills 到项目一 CLI
  - 新 CLI 子命令：`gen-content`（自动分类写作）、`hot-data`（热点采集）、`skill-status`（能力探测）
  - 自动探测内容类型：article / video-script / social-post / topic-research
  - 自动检测 AutoCLI daemon / Chrome 扩展 / 73 个已安装 Hermes Skills
- **auto-gen 智能路由**：自然语言提示 → 意图分类 → 匹配写作/脚本/配图/审校链
- **follow-builders 集成**（⭐5,598）：26 位 AI builder 动态摘要作为数据源
- **Aliens_eye 探针**（⭐2,151）：840+ 平台用户名扫描，注册前预检
- **tool_registry 更新**：新增 skills_adapter 探针，登记 2 个新工具
- **文档更新**：CHANNEL_MATRIX.md / 7PROJECT_INTEGRATION.md / CONTENT_GEN_ENHANCEMENT.md

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
- **Channel tools integration**: fusion module (`content_platform/fusion.py`) with html-anything format, last30days trends, and council review embedded into `content-platform` CLI
- **Format upgrade**: `formatters.py` now uses html-anything for WeChat/Weixin channel HTML output (fallback to built-in converter)
|- **Fusion subcommands**: `content-platform fusion [trend|format|review|all]`

## 3.5.0 - 2026-07-06

- **Hermes Skills 增强层（可选）**：在 Hermes 运行环境下，项目一可通过 `content_gen_fusion.py` 桥接写作/配图/审校/数据采集技能作为可选增强
  - 来源：khazix-skills/kangarooking-skills/canghe-skills/huashu-skills（非独立项目，属 Hermes 内置能力）
  - 数据补充：AutoCLI v0.3.8 实时热点采集（bilibili/douban 已打通, Chrome 扩展已部署）
  - 参考：anthropic-skills-ref（17个官方技能格式参考）
  - 免费资源参考：ripienaar/free-for-dev
- **AutoCLI Chrome 扩展部署**：headless Chrome（port 9223）+ daemon（port 19925）
- **融合脚本**：`scripts/content_gen_fusion.py` — topic → trend → writing → pipeline output
- **能力登记**：`docs/CONTENT_GEN_ENHANCEMENT.md` 记录增强层详情
- **工具注册**：`content_platform/tool_registry.py` 新增 Hermes skills + AutoCLI 探针
- **自动识别**：`skill:tool-inventory` 按场景映射可用增强能力

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
