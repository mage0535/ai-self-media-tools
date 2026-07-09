# Changelog

## 0.3 - 2026-07-09 — 归藏材质插画集成

- **归藏材质插画桥接**：新增 `content_platform/illustrator.py` — 自动从文章内容提取核心概念，按归藏材质风格生成带中文标签的解释图提示词（8 种图解结构：循环/流程/中心辐射/对比/层级/数据场景/科学/文本场景）
- **管线集成**：`pipeline.run()` 新增插画生成步骤（草稿通过风险审查后 → 自动生成插画提示词 → 存入 artifacts）
- **媒体工厂扩展**：`media.py` 新增 `illustration` 媒体类型 + `_generate_illustration()` 方法
- **能力探测**：`skills_adapter.py` 新增 `_check_guizang_material_illustration()` — 检测归藏材质插画技能是否可用
- **工具注册**：`tool_registry.py` 新增 3 个归藏系列技能探针（material-illustration / social-card / ppt）
- **渠道推广矩阵增强**：`promo/HERMES_SKILLS_ENHANCEMENT.md` + 推广使用指南
- **技能安装**：`~/.hermes/skills/creative/guizang-material-illustration/` (归藏材质插画 v0.1, 54⭐)

- GEO check integrated into `pipeline.run()` auto-flow, 5-gate quality contract
- Text de-AI fully upgraded (47 phrases/sycophancy/hedging/burstiness/term locking)
- Content calendar + RSS ingestion + Newsletter pipeline + MCP Server
- Operations dashboard (GEO trend/heatmap/failure classification)
- Multi-backend TTS stubs (Piper/Kokoro)
- Management console task center CRUD + draft version diff
- 157/157 tests passed, three-end consistent
- Rewrote README.md + README_EN.md following KMM format

## 0.2 - 2026-07-08 — Management Console And Public Release Hardening

- Unified public version to `0.2`
- Added one-time-link password-protected management console with Win11 / Edge inspired UI
- Added platform overview, platform detail pages, multi-account binding flow, review/failure/queue panels, and chart-driven analytics
- Added admin persistence and APIs for platform account bindings
- Added `content-platform admin-serve --password ...` command
- Added deeper platform binding checks and a standalone `delivery-worker`
- Expanded Chinese/English project and installation docs with management console instructions
- Validated local and server workflows, including fresh-install and admin-console API verification
- Published public release preparation materials for GitHub
## 0.1 - 2026-07-08 - Public Baseline Release

- Unified public version to `0.1`
- Added public Chinese/English README and detailed project/installation guides
- Added acknowledgements and GitHub Pages landing doc
- Hardened intelligence memory, topic clustering, historical-feedback enrichment, quality gate, queue-backed delivery, and provider abstraction
- Validated local and server workflows, including fresh-install end-to-end verification on Hermes

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
