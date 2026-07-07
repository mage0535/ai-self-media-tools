# Continuous Development

Last updated: 2026-07-07

## Mandatory Rules

- This document is the single ongoing handoff document for all future work.
- Every contributor must append real work, validation, blockers, and next steps here.
- Official GitHub repository: `<github-owner>/<repository>`
- The project must stay consistent across all three ends:
  - local working directory
  - official GitHub repository
  - Hermes server mirror
- Local, GitHub, and server-mirror copies must all remain clean, publishable, and installable.
- Never commit, sync, or retain private server information, passwords, SSH keys, tokens, cookies, personal account data, user-private paths, or other user-specific/private machine data in the publishable project.
- Runtime secrets must be stored in ignored local files only.
- Any future server deployment must keep secrets outside the synced repository.

## Project Purpose

Build a unified AI self-media toolkit that can:
- discover trends
- learn same-track popular writing and visual style
- generate stronger text, image, and video prompts
- stage drafts to multiple platforms
- automate eligible AiToEarn promotion tasks
- coordinate with Hermes and other agents without being hard-wired to one agent runtime

## Delivery Goal

This repository is the clean, publishable, continuously-developed home for:

1. Content intelligence and generation
2. Draft-first multi-platform distribution
3. AiToEarn promotion-task automation
4. Cross-agent installation and operation

It is intended to replace fragmented machine-local scripts with one syncable project directory.

## Architecture Summary

### 1. Content Intelligence
- trend collection
- same-track reference fetching
- style extraction
- topic angle selection
- draft metadata generation

### 2. Distribution Matrix
- official draft publishers
- AiToEarn draft/flow publishers
- browser-upload integration path
- local fallback drafts

### 3. Task Market Automation
- market scan
- allowlist policy
- promotion-first automation
- manual deferral for high-risk interaction tasks

### 4. Agent Compatibility
- Hermes-compatible
- Codex-compatible
- Claude Code compatible
- generic shell/CI compatible

## Design Principles

- Draft-first by default: do not treat draft staging as public publishing.
- Same-track learning before generation: prefer reference-style extraction over generic prompting.
- Trend-aware planning: every draft should know whether it is emerging, hot, or viral-candidate content.
- Agent-neutral packaging: no code path should require one specific agent runtime.
- Clean distribution: the local/GitHub project must remain publishable without private infrastructure data.

## 2026-07-08 Public Release 0.1 Wave

### Goal

Prepare the repository for public release as version `0.1`, unify version labels across local, GitHub, and Hermes, produce user-facing Chinese/English documentation, configure public GitHub metadata, and validate the full workflow again before final sync.

### Scope

- unify public version to `0.1`
- add Chinese default README with English switch
- add detailed Chinese/English project and installation guides
- add public acknowledgements page
- prepare GitHub Pages landing document
- create release notes for `0.1`
- publish repository metadata and release
- keep continuous-development handoff current for future contributors

### Validation Target

- local `python -m pytest -q`
- local `python -m content_platform project-audit`
- server `python3 -m pytest -q`
- server `python3 -m content_platform project-audit`
- GitHub repository visibility / about / website / topics / release configured

## 2026-07-08 Management Console And Public Release 0.2 Wave

### Goal

Ship a public `0.2` release with:

- a built-in management console
- Chinese-default and English-switchable public docs
- public GitHub metadata
- release publication
- full local + server verification

### Functional Work Completed

- added `admin_store.py`, `admin_data.py`, `admin_server.py`, and `platform_catalog.py`
- added one-time-link password-protected management console
- added platform overview and per-platform detail pages
- added multi-account binding persistence and account status checks
- added chart-driven overview and platform analytics
- added `content-platform admin-serve --password ...`
- updated public version from `0.1` to `0.2`
- rewrote public Chinese/English docs for project, installation, acknowledgements, and release notes

### GitHub Publication Work Completed

- repository visibility switched to public
- bilingual about text configured
- website configured to repository README entry
- repository topics configured
- release `v0.1` was created earlier
- release stream is now updated for `0.2` content preparation

### Validation

- local full suite: `151 passed`
- local `project-audit`: `ok: true`
- server full suite: `151 passed`
- server `project-audit`: `ok: true`
- server `health`: version `0.2`
- fresh-install workflow validation: passed
- admin-console API flow validation: passed

### Notes

- GitHub Pages could not be enabled because the current plan rejected Pages creation with HTTP `422`, so the repository website was set to the README URL instead.

## 2026-07-07 Core Capability Hardening Wave

### Goal

Turn the already-present intelligence, routing, quality, delivery, and provider abstractions into real working subsystems rather than thin placeholders.

### What Was Made Real

- Intelligence enrichment:
  - source normalization now records source host, stable fingerprints, content forms, and topic signals
  - niche analysis now records account sample counts, richer role inference, and narrative devices
- Viral and strategy upgrades:
  - viral scoring now includes topic saturation, account diversity, evidence strength, and recommendation state
  - strategy routing now outputs confidence, secondary platforms, warnings, and next-step guidance
- Quality gate loop:
  - humanize now returns a real quality gate with pass/fail dimensions
  - fallback generation writes `quality_gate` into `draft_meta`
  - pipeline escalates low-quality drafts to review instead of silently passing them through
- Delivery queue:
  - added `delivery_queue` storage, enqueue/claim/complete APIs, and queue-backed draft staging / publishing
- Provider abstraction:
  - tool adapters now include script-backed image/video providers in addition to OCR/transcription/analysis
  - media bridge now resolves providers through `ToolRegistry` instead of hand-building subprocess calls

### Validation

- targeted upgraded-flow tests: passed
- full test suite: `147 passed`
- `python -m content_platform project-audit`: `ok: true`

### Next Recommended Direction

- build durable topic clustering and evidence-backed account memory on top of the enriched source/account tables
- strengthen strategy and rewrite decisions with persisted historical performance, not only request-time heuristics
- separate live runtime deployment from repository checkout once the current server workflow allows it

## 2026-07-07 Topic Clustering And Full Workflow E2E Wave

### Goal

Finish the next recommended step from the prior hardening wave:

- make topic clustering durable
- feed historical performance back into generation-time decisions
- verify the publishable package from a fresh user-style install on Hermes

### Functional Changes Completed

- added durable `topic_clusters` storage and lookup
- added historical performance summarization by platform and related-topic lookup
- enriched generation-time briefs with:
  - `historical_feedback`
  - `cluster_memory`
- added `topic_clusters` into generation context and `draft_meta`
- made clustering visible in analysis outputs and persisted pipeline state

### End-To-End Validation On Hermes

A fresh install-style workflow was executed in a separate directory tree:

- clean source bundle exported to `<server-project-root>/src`
- clean install root created at `<server-project-root>/home`
- `scripts/install.py` executed successfully
- minimal external tool scripts created under `home/external/scripts`
- verified commands:
  - `health`
  - `content-readiness`
  - `delivery-readiness`
  - `analyze-topic`
  - `account-report`
  - OCR / transcription / analysis provider calls through `MediaBridge`
  - create -> run -> approve -> publish -> status
  - metrics export
  - `project-audit`

### Validation Evidence

- local full suite: `148 passed`
- server full suite: `148 passed`
- local `project-audit`: `ok: true`
- fresh Hermes install-root workflow:
  - install succeeded
  - tool scripts executed
  - artifacts generated
  - file-draft publishing succeeded for `wechat` and `xiaohongshu`
  - clean audit passed

### Observations

- Open Notebook was unavailable in the fresh-install test environment, but degraded cleanly as expected.
- `social_auto_upload` was not installed in the fresh-install test environment, and readiness correctly reported it as unavailable instead of failing the workflow.

## Current Project Structure

- `content_platform/`
  - workflow engine
  - generator
  - trend ranking
  - task-market automation
  - publisher adapters
  - readiness inspection
- `skills/content/content-copywriting-style/`
  - default copywriting and visual-style rules
- `tests/`
  - regression and behavior tests
- `systemd/`
  - deployment templates
- `scripts/install.py`
  - generic bootstrap installer
- `docs/`
  - this file plus installation and future handoff material

## What Is Already Implemented

- `content_platform` workflow engine
- `AiToEarnDraftPublisher`
- `AiToEarnFlowPublisher`
- `SocialAutoUploadPublisher`
- `TaskMarketRunner`
- `delivery-readiness` command
- content intelligence module with:
  - trend-stage labeling
  - same-track reference analysis
  - fallback to local trend cache when explicit references are absent
  - image/video prompt generation
  - `draft_meta` persistence
- `content-copywriting-style` skill upgraded with default generation rules
- generic install bootstrap:
  - OS detection
  - Python detection
  - common agent CLI detection
  - clean config rendering
  - installation report output

## Work Completed In This Packaging Phase

- copied the currently validated workflow engine into a standalone project directory
- removed hard-coded server-specific launch paths from repository-facing defaults
- added generic path helpers for:
  - install root
  - style-guide path
  - trend-cache path
  - optional social-auto-upload path
  - browser-profile checks
- added a publishable `pyproject.toml`
- added `.gitignore` rules that keep secrets, cookies, logs, and local runtime data out of sync
- added install entrypoints:
  - `scripts/install.py`
  - `install.ps1`
  - `install.sh`

## Verified State

- Local full test suite passed before packaging.
- Packaged project test suite passed after packaging changes.
- Hermes server runtime remained functional during earlier validation.
- The packaged repo is privacy-clean by design and uses generic default paths.
- Installer executed successfully and produced an installation report with detected agent CLIs.

## Validation Evidence

- Packaged project tests: `57/57` passed locally.
- Packaged installer output confirmed:
  - Python version
  - OS
  - detected agents
  - install root
  - rendered config path
- No residual server IPs, passwords, tokens, SSH key paths, or private backup paths remained in the packaged repository scan.

## Packaging Notes

This repository is the clean distribution layer.
It intentionally does not bundle:
- real production secrets
- real account cookies
- real server-only config
- user-private OneDrive-only assumptions
- real server IPs
- private SSH material
- private agent runtime logs

## Recommended Next Steps

1. Keep the clean packaged project synced to the official GitHub repository `<github-owner>/<repository>`.
2. Sync this same directory to the OneDrive project path used by collaborators.
3. Store a clean server-side mirror of this same project directory for Hermes-side reference and future diffs.
4. Add GitHub Actions for tests and packaging checks.
5. Add article-sync integration path for long-form domestic text platforms.
6. Add browser session bootstrap helpers for optional upload tools.
7. Continue appending real implementation and validation evidence here after every development wave.

## 2026-07-02 Content Generation Research And Planning Wave

### Goal Of This Wave

Design the next major content-generation upgrade so the project can evolve from a draft generator into a server-integrated autonomous content factory that works together with the promotion toolchain.

Target closed loop:
- account and niche discovery
- same-track account analysis
- candidate viral-topic scoring
- content-form selection by platform and topic
- copy/script generation
- cover and content image generation
- video asset or video script generation
- anti-generic rewrite and quality scoring
- handoff to existing draft-first promotion and publishing pipeline

### Current Reality Check

The current implementation is a useful base, but it is still an early-stage generator rather than a full autonomous content engine.

What already exists:
- `content_platform/generator.py`
  - unified draft generation entry
  - Hermes CLI / remote model / fallback modes
- `content_platform/intelligence.py`
  - lightweight same-track reference extraction
  - trend-stage and prompt-brief context assembly
- `content_platform/media.py`
  - script-based image/video artifact bridge
- `content_platform/pipeline.py`
  - generation -> risk/compliance -> media -> review -> draft delivery orchestration
- existing distribution layer:
  - `AiToEarnDraftPublisher`
  - `AiToEarnFlowPublisher`
  - `SocialAutoUploadPublisher`
  - `TaskMarketRunner`
  - `delivery-readiness`

Main gaps:
- no account-level niche graph or creator profiling
- no durable content-intelligence store for cross-platform samples
- no candidate viral-score engine
- no structured platform strategy engine for choosing article / note / short video / cover style
- no multi-stage rewrite layer for removing generic AI phrasing
- no unified registry for all available image/video/audio/server tools
- no offline-first installation and capability probing for the future server-side content stack

### External Research Summary

Research and tool scan was performed across GitHub and arXiv on 2026-07-02. Main conclusions:

1. Virality prediction should not rely on text understanding alone.
   - Recent popularity-prediction work shows multimodal content plus temporal/contextual signals outperform content-only pipelines.
   - Useful direction: combine content features, creator/account features, early trend signals, and open-web context instead of asking one LLM to "guess爆款".

2. Open-web context is necessary for short-video popularity prediction.
   - Recent micro-video work indicates virality depends on external trends and structured web context, not only on the video itself.
   - This strongly supports building a niche-context evidence layer in this project.

3. Chinese long-text style transfer should be handled as explicit style modeling, not simple paraphrase.
   - Chinese article-style transfer literature supports extracting style descriptors and then rewriting against those descriptors.
   - This matches the already adopted "same-track reference analysis + style constraints" direction and justifies making it a first-class subsystem.

4. "去 AI 味" should be implemented as quality and style naturalization, not detector evasion.
   - Detection benchmarks show current detectors are brittle and easy to fool, so optimizing against detectors is the wrong target.
   - The right target is: preserve facts, reduce generic structure, inject account-specific rhythm, and score readability / novelty / platform fit.

5. The best practical server stack is composable, not monolithic.
   - One tool is not enough.
   - The most realistic path is: crawler + browser automation + embedding/topic analysis + multimodal understanding + image generation + video generation + media tooling, all behind this project's own adapters.

### Candidate Tools Worth Integrating

These are the most relevant current tools found during research. Recommendation means "prefer integrating first", not "install all immediately".

#### A. Data Collection And Web Acquisition

- `Crawl4AI`
  - good fit for turning public web pages into structured markdown/text for agent pipelines
  - recommended as the primary web-text ingestion layer
- `Playwright`
  - good fit for logged-in pages, dynamic pages, and browser-state-dependent capture
  - recommended as the browser fallback and uploader/session bootstrap base
- `yt-dlp`
  - good fit for reference video/audio capture and metadata extraction where legally and operationally appropriate
- `gallery-dl`
  - good fit for reference image and gallery collection across many sites

#### B. Topic / Niche / Similarity Analysis

- `sentence-transformers`
  - recommended for multilingual embeddings, nearest-neighbor retrieval, dedup, and same-track similarity
- `BERTopic`
  - recommended for niche clustering, trend grouping, and evolving topic buckets
- `KeyBERT`
  - recommended for lightweight keyword extraction from clustered content

#### C. Multimodal Understanding

- `Qwen2.5-Omni`
  - strong candidate as the unified multimodal analyzer for text + image + audio + video understanding on server
- `Whisper`
  - recommended default speech-to-text layer for short-video/audio transcription
- `PaddleOCR`
  - recommended OCR layer for covers, screenshots, posters, and text-heavy competitor assets

#### D. Image / Cover / Poster Generation

- `ComfyUI`
  - recommended as the central image/video workflow backend because it is modular and server-friendly
- `Qwen-Image`
  - especially strong candidate for Chinese text rendering, poster, cover, infographic, and text-heavy image generation/editing

#### E. Video Generation

- `FramePack`
  - strong candidate for image-to-video generation and progressive video diffusion
  - recommended as the first integrated video-generation path when the server GPU budget supports it

#### F. Orchestration

- keep this repository's own `content_platform` as the top-level orchestrator
- do not let any external tool become the new control plane
- external tools should be wrapped as adapters, capability probes, and jobs

### Recommended Product Direction

Adopt a two-layer architecture:

1. `content intelligence layer`
   - collects accounts, posts, transcripts, comments, covers, timestamps, and trend context
   - scores niches, accounts, topics, and candidate ideas

2. `content execution layer`
   - chooses output form
   - generates script/copy/image/video assets
   - runs anti-generic rewrite + quality gates
   - passes deliverables to the existing promotion and draft-publishing stack

This should stay draft-first by default.
Public posting remains a downstream decision of the delivery/promotion layer.

### Proposed Target Architecture

#### 1. Source Adapters

New module family:
- `content_platform/sources/`

Initial adapter classes:
- public web search adapter
- reference article/page adapter
- browser capture adapter
- optional platform-specific fetch adapters

Required outputs:
- normalized account
- normalized post/content item
- normalized media asset metadata
- fetch evidence and timestamps

#### 2. Intelligence Warehouse

New module family:
- `content_platform/intel_store/`

Store responsibilities:
- account snapshots
- post snapshots
- transcript / OCR / caption payloads
- embedding cache
- topic clusters
- viral-score features
- generation feedback and performance backfill

Storage recommendation:
- continue using SQLite for job-state compatibility
- add dedicated tables for:
  - accounts
  - source_items
  - media_features
  - topic_clusters
  - idea_candidates
  - generated_assets
  - performance_feedback

#### 3. Niche And Account Analysis Engine

New module:
- `content_platform/niche_analysis.py`

Responsibilities:
- cluster same-track accounts by niche
- identify account roles:
  - educator
  - storyteller
  - opinion leader
  - template / tool sharer
  - entertainment / emotional trigger
- infer content mix:
  - tutorial
  - listicle
  - case study
  - reaction
  - comparison
  - short script
- extract repeatable style signatures:
  - title patterns
  - hook types
  - paragraph rhythm
  - CTA patterns
  - visual composition patterns

#### 4. Potential Viral Analysis Engine

New module:
- `content_platform/viral_score.py`

Score dimensions:
- trend freshness
- topic saturation
- novelty gap
- cross-account repetition rate
- emotional trigger strength
- practical utility
- visual promise
- platform fit
- creator-fit confidence

Important principle:
- start with an interpretable weighted scoring system
- only introduce learned ranking models after enough local labeled history exists

#### 5. Content Strategy Router

New module:
- `content_platform/strategy_router.py`

Responsibilities:
- choose whether a topic should become:
  - long article
  - short note
  - image carousel
  - short talking script
  - image-to-video asset
  - pure script for downstream filming
- choose output structure by platform:
  - WeChat / article platforms
  - Xiaohongshu-style note
  - short-video platforms
  - overseas text platforms

#### 6. Multi-Stage Generator

Refactor current generator into stages:
- `research brief builder`
- `angle chooser`
- `outline/script generator`
- `image prompt planner`
- `video prompt planner`
- `style naturalizer`
- `quality scorer`

Suggested module split:
- `content_platform/generation/briefs.py`
- `content_platform/generation/angles.py`
- `content_platform/generation/scripts.py`
- `content_platform/generation/prompts.py`
- `content_platform/generation/rewrite.py`
- `content_platform/generation/score.py`

#### 7. Media Tool Registry

New module:
- `content_platform/tool_registry.py`

Responsibilities:
- detect installed server tools
- record version, command path, model path, GPU requirements, timeout defaults
- expose standard calls:
  - `generate_image(...)`
  - `edit_image(...)`
  - `generate_video(...)`
  - `transcribe_audio(...)`
  - `ocr_image(...)`
  - `analyze_multimodal(...)`

This is the key compatibility layer that lets promotion tools and content tools live inside one agent system.

#### 8. Asset Production Adapters

Refactor `content_platform/media.py` into adapter-backed providers:
- `ComfyUIImageProvider`
- `QwenImageProvider`
- `FramePackVideoProvider`
- `WhisperTranscriber`
- `PaddleOCRProvider`
- `QwenOmniAnalyzer`

#### 9. Anti-Generic Quality Layer

New module:
- `content_platform/humanize.py`

Target is not "evade AI detectors".
Target is:
- fewer empty transitions
- less template repetition
- stronger account-specific voice
- clearer scene and sensory detail
- preserved claims and facts
- stronger platform-native rhythm

Recommended implementation:
- style-signature extraction from same-track accounts
- forbidden generic phrase library
- sentence-length variance control
- rhetorical-pattern diversification
- compare-before-after semantic preservation with embeddings
- final quality scores:
  - authenticity
  - clarity
  - retention hook strength
  - platform fit

#### 10. Promotion Integration

Existing publishers and task-market tools remain downstream consumers.

New handoff payload should include:
- `draft_meta.topic_cluster`
- `draft_meta.account_style_refs`
- `draft_meta.viral_score`
- `draft_meta.content_form`
- `draft_meta.cover_strategy`
- `draft_meta.media_plan`
- `draft_meta.quality_scores`
- `draft_meta.rewrite_notes`

### Recommended Hermes Server Tooling Baseline

Preferred baseline to prepare for later installation:
- `ComfyUI`
- `ComfyUI-Manager`
- `Qwen-Image`
- `FramePack`
- `Whisper`
- `PaddleOCR`
- `ffmpeg`
- `yt-dlp`
- `gallery-dl`
- `Playwright`
- `Crawl4AI`

Installation policy recommendation:
- do not install everything blindly
- first implement capability registry and readiness probes
- then install tools in tiers based on direct product value and server resource cost

### Staged Delivery Plan

#### Phase 1: Intelligence Foundation

Scope:
- add source adapters
- add intelligence tables
- add account/post normalization
- add embeddings, clustering, and keyword extraction
- keep current generator working

Done standard:
- can ingest and normalize reference content from configured sources
- can cluster same-track content
- can produce an account/niche analysis report for one topic

#### Phase 2: Viral Candidate Engine

Scope:
- add interpretable viral-score engine
- add candidate idea generation
- add strategy router

Done standard:
- for a niche input, system outputs ranked candidate topics with evidence and reasons
- each candidate includes recommended content form and target platforms

#### Phase 3: Advanced Generation

Scope:
- split generator into staged pipeline
- add style naturalizer and quality scorer
- enrich `draft_meta`

Done standard:
- one command can generate:
  - final copy or script
  - image prompts
  - video prompts
  - quality report
- same-track style references are visible in metadata

#### Phase 4: Server Tool Integration

Scope:
- build tool registry
- implement ComfyUI / Qwen-Image / Whisper / PaddleOCR adapters
- implement FramePack path if server resources allow

Done standard:
- readiness command can report content-tool availability
- generator can call installed tools through standard adapters
- image/video/OCR/transcript results are persisted as artifacts and metadata

#### Phase 5: Promotion Unification

Scope:
- pass richer content metadata into existing distribution and AiToEarn layers
- add feedback ingestion from published or drafted outcomes

Done standard:
- promotion tools can consume generated assets and structured strategy metadata
- performance feedback can be written back into future ranking and style decisions

### What Should Be Built First

Recommended build order:
1. intelligence warehouse
2. source adapters
3. niche/account analysis
4. viral-score engine
5. generation refactor
6. tool registry
7. media adapters
8. promotion feedback loop

Reason:
- this order reduces blind generation
- keeps the current pipeline usable during migration
- allows server tooling to be added progressively without blocking analysis work

### Validation Standards For Future Development

Every future implementation wave should verify:
- no private paths, tokens, cookies, secrets, or server-only credentials are committed
- same input produces reproducible metadata and stable scoring within expected variance
- every adapter failure degrades gracefully and leaves explainable job events
- generated scripts preserve key facts from source evidence
- generated image/video artifacts are traceable back to the prompts and upstream evidence
- promotion handoff contains enough metadata to explain why a draft was created

### Immediate Next Implementation Recommendation

When development resumes, the first coding wave should focus on:
- intelligence storage schema
- source adapter abstraction
- niche/account analysis MVP
- viral-score MVP

Do not start with video generation first.
Reason:
- the current largest gap is decision quality, not rendering ability
- without a stronger intelligence layer, more generation tools will mostly scale low-confidence content

### Research References Used In This Planning Wave

- ComfyUI: https://github.com/comfy-org/comfyui
- FramePack: https://github.com/lllyasviel/FramePack
- Crawl4AI: https://github.com/unclecode/crawl4AI
- Playwright: https://github.com/microsoft/playwright
- Whisper: https://github.com/openai/whisper
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- Qwen2.5-Omni: https://github.com/QwenLM/Qwen2.5-Omni
- Qwen-Image: https://github.com/QwenLM/Qwen-Image
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- gallery-dl: https://github.com/mikf/gallery-dl
- BERTopic: https://github.com/MaartenGr/BERTopic
- sentence-transformers: https://github.com/huggingface/sentence-transformers
- MMG-Pop benchmark paper: https://arxiv.org/abs/2606.27539
- SMTPD benchmark paper: https://arxiv.org/abs/2503.04446
- Web-grounded micro-video popularity paper: https://arxiv.org/abs/2605.18653
- RAID detection benchmark: https://arxiv.org/abs/2405.07940
- CAT-LLM Chinese style-transfer paper: https://arxiv.org/abs/2401.05707

## 2026-07-02 Content Intelligence MVP Implementation Wave

### Scope Completed

Implemented the first integrated content-intelligence MVP inside the existing `content_platform` without breaking the current draft-first workflow.

Delivered capabilities:
- normalized source ingestion
- niche/account analysis
- interpretable viral scoring
- content strategy routing
- enriched draft metadata
- intelligence persistence in SQLite
- tool registry and content-tool readiness inspection
- new analysis CLI entrypoints

### New And Updated Modules

New modules added:
- `content_platform/sources.py`
- `content_platform/niche_analysis.py`
- `content_platform/viral_score.py`
- `content_platform/strategy_router.py`
- `content_platform/tool_registry.py`

Core modules upgraded:
- `content_platform/intelligence.py`
- `content_platform/generator.py`
- `content_platform/store.py`
- `content_platform/pipeline.py`
- `content_platform/readiness.py`
- `content_platform/media.py`
- `content_platform/cli.py`

### Behavioral Changes

#### 1. Intelligence Layer

Generation context now carries:
- `source_catalog`
- `source_summary`
- `niche_report`
- `viral_score`
- `strategy`

This means every generated draft can now explain:
- what reference material it looked at
- which accounts/platforms shaped the style
- why the topic scored well or poorly
- what content form was selected

#### 2. Persistence Layer

SQLite storage now includes:
- `source_items`
- `account_snapshots`
- `idea_candidates`
- `tool_inventory`

This allows the project to retain reusable intelligence rather than recomputing everything as prompt-only transient state.

#### 3. Pipeline Layer

`Pipeline.run(...)` now persists intelligence artifacts before risk/compliance handling:
- source items
- account snapshots
- ranked idea candidate metadata

This keeps the content-generation side and the promotion side aligned around one job record.

#### 4. Tooling Layer

`inspect_delivery_readiness(...)` now includes `content_tools` capability probing.

Current registry probes:
- `ffmpeg`
- `yt-dlp`
- `gallery-dl`
- `playwright`
- Python runtime
- configured image script
- configured video script

#### 5. CLI Layer

New commands added:
- `analyze-topic`
  - builds a full intelligence report for a topic + brief payload
- `content-readiness`
  - returns content-tool readiness and stores a tool-inventory snapshot

### Testing And Validation

Fresh verification completed after implementation:
- focused new-behavior tests: passed
- full test suite: `67/67` passed locally
- Python compile verification for all newly added and modified core modules: passed

Coverage added for:
- niche analysis
- viral scoring
- strategy routing
- intelligence persistence
- pipeline-side intelligence persistence
- CLI analysis command
- content-tool readiness command

### Notes

- This wave intentionally implemented an interpretable scoring and routing MVP first, not a learned ranking model.
- This wave did not install heavy server-side external tools automatically.
- The capability layer is now in place so those tools can be integrated cleanly in later work without hard-wiring them into the pipeline.

### Recommended Next Implementation Focus

After this MVP, the next highest-value work is:
1. real source adapters for public web / browser capture / platform-specific fetch
2. richer account snapshot enrichment
3. tool-backed image/video/OCR/transcription adapters behind the registry
4. feedback loop from delivery/performance back into scoring and routing

## 2026-07-02 Extended Integration Wave

### Additional Work Completed

Built the next integration layer on top of the MVP so the project now includes:
- tool-adapter classes for OCR, transcription, and multimodal analysis scripts
- account-report CLI output for same-track account summaries
- feedback-summary CLI output for performance aggregation
- feedback signal folded back into viral scoring
- project-audit CLI command for publishable-repo privacy and purity checks
- updated README and config template for the new content-tool stack

### New Files Added In This Wave

- `content_platform/tool_adapters.py`
- `content_platform/humanize.py`
- `content_platform/project_audit.py`

### Capability Expansion

The repository now supports:
- richer content-tool probing
- script-backed OCR / transcription / analysis adapters
- anti-generic rewrite and quality scoring as part of draft normalization
- performance feedback aggregation for future ranking decisions
- a local publishability audit before syncing across local / GitHub / Hermes mirror

### Verification Evidence

- Full test suite after this wave: `75/75` passed locally.
- `project-audit` command: returned clean result on the current repo state.
- `analyze-topic` command: returned niche report, viral score, and strategy payload successfully.
- `content-readiness` command: returned structured content-tool inventory successfully.

## 2026-07-02 Server Sync And Runtime Fix Wave

### Real Deployment Findings

During Hermes sync and runtime validation, two production issues were found:
- `TrendCollector` default refresh path incorrectly resolved to `data/external/scripts/trend_collector.py`
- `task-market-auto` failed hard when `AITOEARN_API_KEY` was not configured, causing the timer-backed service to enter failed state

### Fixes Applied

- corrected the default trend collector fallback path to `project_home()/external/scripts/trend_collector.py`
- changed task-market auto execution to return a clean zero-result summary with a `reason` field when the required AiToEarn key is absent

### Validation Evidence

- local full test suite after these runtime fixes: `78/78` passed
- local and GitHub were re-synced after the fixes
- Hermes server mirror was resynced after the fixes

## 2026-07-02 Three-End Consistency Audit And Publishing Fix Wave

### Background

Prior to this wave, the project was known to live in three locations:
- local working directory (synced via OneDrive across machines)
- GitHub repository `<github-owner>/<repository>`
- Hermes production server (deployment mirror under the operator home directory)

A formal end-to-end consistency audit was requested to ensure all three copies are aligned, privacy-clean, and publishable, and that the install bootstrap produces an identical config on any agent runtime.

### Findings From Audit

All core source files (31 `.py` files in `content_platform/`, all test files, all config templates, skill files, systemd timers) had matching MD5 hashes between local and the server — **61 of 64 tracked files were identical**.

Four files had discrepancies:

1. `docs/CONTINUOUS_DEVELOPMENT.md` — server copy was missing the "2026-07-02 Server Sync And Runtime Fix Wave" section (812 lines vs 831 lines locally).
2. `systemd/hermes-content-platform.service` — server repo-copy had `--profile tech`, while the actual running systemd unit used `--profile default`. The authoritative template in the repo correctly used `default`.
3. `tests/test_cli_v2.py` — content identical, but line endings differed (CRLF vs LF on Windows vs Linux).
4. `tests/test_trends.py` — same line-ending mismatch.

Additional runtime finding:
- Server `config.json` had `style_guide_path` pointing to a Hermes-project internal path (an older deployment convention), not the generic install-bootstrap path under `CONTENT_PLATFORM_HOME`.

### Fixes Applied

#### 1. Line Ending Normalization

Added `.gitattributes` at the project root to enforce LF line endings for all source file types:

```
* text=auto
*.py text eol=lf
*.sh text eol=lf
*.md text eol=lf
*.toml text eol=lf
*.json text eol=lf
*.service text eol=lf
*.timer text eol=lf
```

Executed `git rm --cached -r . && git checkout HEAD -- .` to re-checkout every file with the new rules. After this, all project files use LF, regardless of platform.

Committed as `ba7b02c` and pushed to `origin/main`.

#### 2. Server File Sync

Used `git show HEAD:<path>` piped through SSH to overwrite the four mismatched files on the Hermes server, ensuring LF line endings were preserved. After sync, all 64 tracked files have matching MD5 hashes across local and server.

#### 3. Server Config Fix

Updated the server's `config.json` style_guide_path from the old Hermes-project deployment path to the generic install-bootstrap path. The old path referenced a Hermes-internal project layout; the new path uses the standard install root convention:

```
OLD: <hermes-home>/projects/ai-self-media-tools/skills/content/content-copywriting-style/SKILL.md
NEW: CONTENT_PLATFORM_HOME/skills/content/content-copywriting-style/SKILL.md
```

This is the path that `scripts/install.py` generates by default, making future re-installs consistent.

### Validation Evidence

- Full test suite: **78/78 passed** (unchanged from prior wave)
- `project-audit` output: `ok: true, scanned_files: 77, issues: []`
- Local ↔ server MD5: all 64 tracked source files match
- GitHub: pushed commit `ba7b02c`, `origin/main` up to date
- Server systemd unit verified: `ExecStart` uses `--profile default` (matches repo template)
- No residual private paths, IPs, passwords, tokens, or cookies in any tracked file

### Notes For Future Contributors

- This codebase is synced via OneDrive. Never use absolute platform-specific paths (`D:\...` or `/Users/...`) in code, config templates, or documentation. Always prefer `project_home()` or environment-based defaults.
- The GitHub repository is currently **private**. The code is publishable, but visibility must be toggled to public in GitHub Settings before external sharing.
- The `.gitattributes` file ensures that Git always stores LF and checks out LF on all platforms. If a contributor reports "file modified but no diff", they should run `git add --renormalize .` to apply the attribute rules.
- To run the full purity check before any sync or publish: `python -m content_platform project-audit`
- To export a clean mirror bundle: `python scripts/release_bundle.py --target <export-dir>`

## 2026-07-02 Three-Project Integration Wave

### Background

Three independent content-creation patterns were identified in the self-media ecosystem, each addressing a different content production need:

1. **AutoClip** — "long video -> AI highlights -> clip compilation" (inspired by zhihu/pin/2055628331433858821)
2. **GitHub Star Explorer** — "daily trending project discovery -> cross-channel promo" (inspired by Douyin "GitHub-Star-OpenMontage")
3. **XCrawl Data Collector** — "web crawl -> structured data -> Excel/report" (inspired by Douyin "Codex-XCrawl")

All three were designed to integrate into the existing Hermes content pipeline without disrupting the running production system.

### Scope Completed

Four new modules were built and integrated:

#### 1. AutoClip Adapter (`scripts/autoclip_adapter.py`)

Core capabilities:
- `download_video(url, output_dir)` — yt-dlp download with auto-subs (en/zh)
- `transcribe_video(video_path)` — Whisper base model transcription
- `clip_segments(video_path, segments, output_dir)` — FFmpeg segment extraction
- `create_compilation(clips, output_path)` — concat compilation
- `run_autoclip_pipeline(url, task_id)` — end-to-end entry point
- `quality_check(clips)` — duration and file-existence validation

Design decisions:
- Did NOT clone the full AutoClip FastAPI/Redis/Celery stack (too heavy)
- Whisper runs locally (no external LLM API dependency for transcription)
- `llm_ready=True` flag allows upper-layer Hermes to inject LLM-based highlight refinement
- Registered as `video_autoclip` content type in `content_generator.py`

#### 2. GitHub Star Explorer (`scripts/github_star_explorer.py`)

Core capabilities:
- `fetch_trending()` — GitHub Search API with optional token auth
- `generate_content(project, lang)` — bilingual (en/zh) promo generation
- `daily_pick(lang)` — quality-filtered top project selection
- `quality_check(project)` — minimum stars and description validation

Design decisions:
- Falls back gracefully on API rate limits (60/hr unauthenticated)
- Template format compatible with `promo_pipeline.py` CONTENT_TEMPLATES_V2 structure

#### 3. Data Collector (`scripts/data_collector.py`)

Core capabilities:
- `scrape_urls(urls, timeout)` — batch URL fetching with requests
- `to_excel(data, columns, output_path)` — pandas XLSX or CSV fallback
- `content_research(topic, max_sources)` — HN + GitHub search aggregation
- `quality_check(data)` — source validity rate verification

Design decisions:
- Uses requests+BeautifulSoup (XCrawl npm package not available for Python)
- Compatible with promo_pipeline context injection pattern

#### 4. Unified Quality Gate (`scripts/content_quality_gate.py`)

Core capabilities:
- `run_quality_gate(content_type, content_data)` — single entry point
- `audit_autoclip(result)` — clip count and compilation validation
- `audit_github_star(project)` — star threshold and description check
- `audit_collected_data(data)` — source validity rate verification

Design decisions:
- Extensible dictionary-based gate registry (`GATES` dict)
- Reuses `promo_pipeline.py` `quality_review` patterns

### Pipeline Modifications

Four existing production files were patched with surgical insertions only (no lines deleted, no refactoring):

| File | Patch |
|------|-------|
| `content_generator.py` | Added `gen_autoclip_video()` function + `video_autoclip` entry in CONTENT_GENERATORS + dispatch branch |
| `video_operator.py` | Added `video_autoclip` handler branch calling `run_autoclip_pipeline()` |
| `unified_pipeline.py` | Added `github_stars` channel to CHANNEL_ROSTER with `use_github_explorer` flag |
| `promo_pipeline.py` | Added `github-star-explorer` template (en/zh) to CONTENT_TEMPLATES_V2 + GitHub trending injection before Step 3 |

Original files backed up as `*.bak.integration` on the server before patching.

### Skill Registration

Two new Hermes skills registered:

| Skill | Path | Trigger Keywords |
|-------|------|------------------|
| `content-ai-autoclip` | `skills/content-ai-autoclip/SKILL.md` | autoclip, highlight-extraction, video-slicing |
| `content-github-star-explorer` | `skills/content-github-star-explorer/SKILL.md` | github-star, trending, open-source-discovery |

### Configuration Templates

New files for clean installation:
- `config.yaml.example` — paths, API keys, channel config
- `requirements.txt` — pip dependencies (requests, pandas, openpyxl, openai-whisper, yt-dlp)

### Validation Evidence

- Server import test: all 4 modules importable, all deps satisfied (whisper + torch installed)
- Quality gate integration test: all 3 content types pass audit
- Local test suite: **78/78 passed** (no regressions)
- Project audit: **89 files scanned, 0 issues**

### Notes

- AutoClip downloads can take 2-5 minutes for a 10-minute video (download + whisper + ffmpeg)
- GitHub Star Explorer may return empty on first run if API is rate-limited; retries are automatic
- Data Collector requires `requests` package; falls back gracefully if unavailable
- The pipeline modifications follow the existing pattern of `sys.path.insert(0, SCRIPTS)` for intra-module imports
- All new modules include `__name__ == "__main__"` CLI entry points for independent testing

## 2026-07-02 Intelligent Multilingual Voice Engine

### Background

The content pipeline previously produced silent video artifacts — no voice narration, no dubbing, no subtitles. The `MediaBridge` only handled `image` and `video` artifact kinds. Audio generation was explicitly rejected with `ValueError`.

The voice engine fills this gap: any text script → natural-sounding speech + synchronized subtitles, fully integrated into the pipeline.

### Files

| File | Role |
|------|------|
| `scripts/voice_engine.py` | Core voice engine (643 lines) — language detection, genre mapping, TTS synthesis, de-AI post-processing, subtitle generation, CLI entry |
| `scripts/__init__.py` | Package init (enables `from scripts.voice_engine import ...`) |
| `content_platform/media.py` | `MediaBridge._generate_audio()` method — calls voice engine, returns audio artifact with checksums |
| `content_platform/pipeline.py` | Added `"audio"` to the media generation loop (line 70) |
| `content_platform/intelligence.py` | Added `narration_guide` to generation context — tells LLM how to write dubbing scripts |
| `content_platform/strategy_router.py` | Added `"audio"` to asset plan for `short_video` content form |
| `skills/content/content-voice-engine/SKILL.md` | Hermes skill registration |
| `config.example.json` | Added `audio` media configuration section |

### Capability Matrix

| Feature | Support | Detail |
|---------|---------|--------|
| Single-speaker mode | yes | Auto-detect: plain text → single voice narration |
| Multi-speaker dialogue | yes | `[Speaker A]` / `[Speaker B]` tags → alternating voices |
| Genre auto-adaptation | yes | tech/pets/finance/emotion/science/default, each with per-language voice tuning |
| Language auto-detection | yes | Character set analysis (CJK, Arabic, Thai, Cyrillic, Latin) |
| Supported languages | 84+ | All edge-tts locales, with curated voice profiles for zh/en/ja/ko/es/fr/de/pt/ru/it/ar/hi/th/vi |
| De-AI breathing | yes | Pink noise → bandpass filter → volume reduction at punctuation boundaries |
| Random pauses | yes | 200-1000ms silence between sentences (per-language calibrated) |
| Speed variation | yes | ±4-5% per sentence via FFmpeg atempo filter |
| Filler words | yes | Per-language filler word library (um/like/嗯/ええと/eh/pues/äh/é/nu) |
| EQ warmth | yes | +2-3dB at 200Hz per language profile |
| Noise floor | yes | -48 to -52dB pink noise ambience |
| Subtitle generation | yes | SRT format with word-level timestamps; CJK: phrase-level merging (3-8 chars); Latin: word-level (6 words) |
| edge-tts primary | yes | Free, 84+ languages, 400+ voices, zero new model download |
| Memory usage | ~200MB | edge-tts is network-bound API; only FFmpeg processes locally |

### Integration Points

**MediaBridge (`media.py:46-96`)**
```python
# Added "audio" to supported kinds and `_generate_audio()` method
def generate(self, kind, job):
    if kind not in {"image", "video", "audio"}:  # ← was {"image", "video"}

def _generate_audio(self, job, output_dir, cfg):
    from scripts.voice_engine import VoiceEngine
    narration = job["draft_meta"]["narration_script"] or job["body"]
    engine = VoiceEngine(output_dir)
    result = engine.synthesize(narration, lang="auto", genre="auto")
    return {"kind": "audio", "path": result["audio"], "subtitle": result["subtitle"], ...}
```

**Pipeline loop (`pipeline.py:70`)**
```python
for kind in ("image", "video", "audio"):  # ← was ("image", "video")
    artifact = self.media.generate(kind, job)
```

**Intelligence context (`intelligence.py:145-155`)**
```python
narration_guide = (
    "生成中文配音脚本。跟踪赛道和内容形式自动适配风格。"
    "单人播报模式：直接输出配音文本。"
    "多人对话模式：使用[角色A]台词\n[角色B]台词 格式。"
)
```

### Voice Engine Architecture

```
run_voice_pipeline(script_text, lang, genre, mode)
  │
  ├─ detect_language()        → zh/en/ja/ko/...
  ├─ detect_genre()           → tech/pets/finance/emotion/science/default
  ├─ parse_script()           → [ScriptSegment(speaker, text), ...]
  │
  ├─ EdgeTTSProvider.synthesize_with_timing()
  │   ├─ stream() once → collect audio + WordBoundary
  │   └─ write audio file + return timing list
  │
  ├─ DeAIProcessor.apply()
  │   ├─ Per-segment speed variation (atempo)
  │   ├─ Inter-segment silence/breath insertion
  │   ├─ Low-frequency EQ boost
  │   └─ Pink noise ambience injection
  │
  └─ SubtitleGenerator.merge()
      ├─ CJK: phrase merging (3-8 chars or punctuation boundaries)
      └─ Latin: word merging (6 words per segment)
```

### Testing Evidence

- Server import: `from scripts.voice_engine import detect_language, detect_genre, VoiceEngine` → OK
- Language detection: en/zh/ja/ko all correct
- Genre detection: tech/finance/pets all correct (cross-language)
- TTS synthesis: English tech narration → 3.3s MP3 generated successfully
- Full test suite: **78/78 passed**, no regressions
- Project audit: 0 issues

## 2026-07-02 Open Notebook 集成

### 集成内容
将 Open Notebook (lfnovo/open-notebook, 33.7k⭐) 深度研究能力集成到内容管线。

### 新增文件

| 文件 | 类型 | 说明 |
|------|:----:|------|
| `scripts/open_notebook_integrator.py` | 🔵 核心 | REST API 客户端 + digest/research 引擎 |
| `skills/content/content-open-notebook/SKILL.md` | 🟢 Skill | Hermes skill 注册 |
| `tests/test_open_notebook_integrator.py` | 🟣 测试 | 30 个单元/集成测试 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `content_platform/tool_registry.py` | 添加 `_probe_open_notebook()` 探测 |
| `content_platform/intelligence.py` | `build_generation_context()` 集成 `deep_research` 可选路径 |

### 能力矩阵

| 能力 | 状态 | 说明 |
|------|:----:|------|
| 素材消化 (URL→摘要) | ✅ | Notebook 创建→素材添加→搜索分析 |
| 多素材联合研究 | ✅ | 单 Notebook 内多来源综合提问 |
| 管线集成 | ✅ | `deep_research=True` 自动调用 |
| 工具探测 | ✅ | `ToolRegistry.probe()` 包含 open_notebook |
| `/api/search/ask` 提问 | ❌ | OpenCode 无 strategy/answer 模型类型，需更换供应商 |
| 错误降级 | ✅ | 非致命错误不阻断管线 |

### 模型配置
| 角色 | 模型 | 供应商 | 方式 |
|:----|:----|:----:|:----:|
| Chat | `deepseek-v4-flash` | OpenCode | REST API `/api/models/defaults` |
| Transformation | `deepseek-v4-flash` | OpenCode | REST API |
| Tools | `deepseek-v4-flash` | OpenCode | REST API |
| Embedding | `intfloat/multilingual-e5-small` | **GBrain** (`:8766`) | 手动注册 + 设默认 |

embedding 通过本地 OpenAI 兼容服务提供，无需额外部署。

### 验证
- 测试: **30/30 passed** (全量 `107 passed`, 1 pre-existing failure in test_adapters)
- CLI: `health` / `digest` / `research` 三子命令
- API 真实交互: Notebook 创建→Source 添加(multipart)→搜索→清理 已测通
- Embedding: GBrain `multilingual-e5-small` 384维向量 ✅

### Open Notebook 服务
```
部署路径: operator-managed local deployment
Web UI:   http://localhost:8502
REST API: http://<open-notebook-host> (healthy)
SurrealDB: :8000
```

## 2026-07-02 v3.1 — SEO/GEO & Content Matrix

### 功能扩展
将 SEO/GEO 质量检查、OpenSERP 关键词研究、内容矩阵管理和多渠道发布能力集成到内容管线。

### 新增文件

| 文件 | 类型 | 说明 |
|------|:----:|------|
| `content_platform/seo.py` | 🔵 核心 | GEO 7 维质量检查 + OpenSERP SERP 分析 + pyseoanalyzer |
| `content_platform/copy_manager.py` | 🔵 核心 | 内容矩阵管理：轮转调度、多格式适配 (blog/microblog/forum) |
| `tests/test_seo.py` | 🟣 测试 | 18 个 GEO/SERP 单元测试 |
| `tests/test_copy_manager.py` | 🟣 测试 | 18 个矩阵管理单元测试 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `content_platform/cli.py` | 新增 3 个 CLI 命令：`seo-geo-check`、`keyword-research`、`publish-matrix` |
| `content_platform/publishers.py` | 新增 8 个发布器：Mastodon、Bluesky、Nostr、WriteAs、GitHub Discussions、Buttondown、博客园、Steemit |
| `requirements.txt` | 新增依赖：`httpx`、`websocket-client`、`pynacl` |

### 能力矩阵

#### SEO/GEO
| 能力 | 状态 | 说明 |
|------|:----:|------|
| GEO 7 维质量检查 | ✅ | 数值声明/来源标注/权威引用/直接回答/短段落/结构化列表/FAQ |
| 加权评分 (0-100) | ✅ | 7 维度加权，≥85 通过 |
| OpenSERP 关键词研究 | ✅ | 环境变量配置 `OPENSERP_ENDPOINT` / `OPENSERP_API_KEY` |
| SERP 内容空白分析 | ✅ | 自动检测对比内容/教程类空白 |
| pyseoanalyzer 集成 | ✅ | pip pyseoanalyzer 或 seo-analyze CLI fallback |
| 管线集成 | ⏳ | CLI 手动触发，未接入 `pipeline.run()` 自动流 |

#### Content Matrix
| 能力 | 状态 | 说明 |
|------|:----:|------|
| 矩阵目录加载 | ✅ | 从 `data/matrix/copy/` 读取 .md 文件 |
| 按日轮转选择 | ✅ | `pick_copy(day_seed)` 确定性调度 |
| 多格式适配 | ✅ | blog(完整) / microblog(≤500字) / forum(摘要+链接) |
| 发布日志 | ✅ | JSONL 格式，记录平台/结果/URL/错误 |
| 内容规则配置 | ✅ | `content_rules.json` 定义渠道启用/禁用 |
| 管线集成 | ⏳ | CLI 手动触发 `publish-matrix`，未接入自动流 |

#### 新增发布器
| 发布器 | 类型 | 认证方式 | 依赖 |
|--------|:----:|---------|------|
| Mastodon | ActivityPub | 实例 URL + Access Token | `httpx` |
| Bluesky | AT Protocol | 标识符 + 密码 → OAuth JWT | `httpx` |
| Nostr | 去中心化协议 | 私钥签名 + WebSocket 广播 | `pynacl` `websocket-client` |
| WriteAs | REST API | Token | `httpx` |
| GitHub Discussions | GraphQL | GitHub Token | `httpx` |
| Buttondown | REST API | API Key | `httpx` |
| 博客园 | 连通性测试 | — | `httpx` |
| Steemit | 连通性测试 | — | `httpx` |

### 技术改进
- `seo.py` `short_paragraphs`: 修复 CJK+English 句数检测，改用严格模式（任何长段落即失败）
- `seo.py` `faq_section`: 扩宽 Q/A 模式匹配，支持行内 `Q:` `A:` 格式
- `publishers.py` Nostr: 添加 `try/except` 包裹 `pynacl` 导入，缺失时返回清晰错误而非崩溃

### 验证
- 测试: **142/144 passed** (2 pre-existing: project_audit dirty repo, CLI hardcoded path)
- 新增: **36/36 passed** (18 SEO + 18 Copy Manager)
- 无回归

### 下一步计划
- [ ] SEO/GEO 接入 `pipeline.run()`：在生成后自动运行 `geo_check()` 并将结果写入 draft_meta
- [ ] 注册 Hermes skill: `skills/content/content-seo/SKILL.md`
- [ ] 注册 Hermes skill: `skills/content/content-copy-matrix/SKILL.md`
- [ ] 添加新发布器单元测试 (Mastodon/Bluesky/WriteAs 的 mock 测试)
- [ ] `publish-matrix` 与 systemd 定时器集成，支持定时矩阵发布

---

# 2026-07-07 技术雷达 & 生态调研

> 综合 GitHub、学术论文、工具生态的全域扫描，为项目后续演进提供参考。
> 建议团队集体讨论优先级后，逐项纳入开发计划。

---

## 1. GEO (Generative Engine Optimization) — 学术前沿

AI 搜索引擎 (ChatGPT/Perplexity/Gemini/Claude) 已从"排名列表"转向"引用合成回答"，
传统 SEO 不再直接适用，GEO 是新的必然方向。以下是关键论文：

### 1.1 基础论文

| 论文 | 年份 | 会议 | 核心贡献 | 链接 |
|------|:----:|------|----------|------|
| **GEO: Generative Engine Optimization** | 2024 | ACM KDD | 首个 GEO 范式定义；9 种启发式优化策略；GEO-Bench 基准；Perplexity.ai 实测 +40% visibility | [arXiv:2311.09735](https://arxiv.org/abs/2311.09735) |
| **FeatGEO** | 2025 | arXiv | 特征级多目标优化，而非 token 级改写；NSGA-II 搜索特征空间；三引擎 GPT-4o/Gemini/Qwen +37~96% | [arXiv:2604.19113](https://arxiv.org/abs/2604.19113) |
| **MAGEO** | 2025 | arXiv | 多智能体 GEO 框架；策略学习 + 可复用 skill 蒸馏；DSV-CF 双轴评估指标；三个引擎实测 | [arXiv:2604.19516](https://arxiv.org/abs/2604.19516) |
| **Mind Reader** | 2025 | ACL 2026 | 潜在用户需求引导的 GEO；DRQA 查询增强 + RCCO 推理覆盖优化；2.44× objective 提升 | [ACL 2026](https://aclanthology.org/2026.acl-long.1894.pdf) |
| **AgenticGEO** | 2025 | arXiv | 自演化智能体 GEO；MAP-Elites 存档 + Co-Evolving Critic 代理评估；14 基线 × 3 数据集最优 | [arXiv:2603.20213](https://arxiv.org/abs/2603.20213) |
| **GEO-SFE** | 2025 | arXiv | 结构特征工程 GEO；3 级结构 (宏观/中观/微观)；6 引擎 ±17.3% 引用提升 | [arXiv:2603.29979](https://arxiv.org/abs/2603.29979) |
| **GEO: How to Dominate AI Search** | 2025 | arXiv | AI 搜索 vs Google 系统对比；Earned Media 压倒性偏向；多语言稳定性分析 | [arXiv:2509.08919](https://arxiv.org/abs/2509.08919) |

### 1.2 核心方法论（已在 seo.py 中部分落地）

| 策略 | 效果 | 本项目状态 |
|------|:----:|-----------|
| Cite Sources（引用可靠来源） | +30-40% 引用率 | ✅ `geo_check.claims_with_sources` |
| Quotation Addition（添加权威引用） | +30-40% | ✅ `geo_check.authority_quotes` |
| Statistics Addition（添加统计数据） | +30-40% | ✅ `geo_check.claims_with_numbers` |
| 结构化列表 + FAQ 格式 | +28% 引用 | ✅ `geo_check.structured_list/faq_section` |
| 前200字直接回答 | +340% 引用 | ✅ `geo_check.direct_answer` |
| Feature-level optimization | +37-96% | ❌ 需重写引擎（FeatGEO/MAGEO） |
| Strategy learning & reuse | 多引擎泛化 | ❌ 需 agentic 架构 |

### 1.3 建议
- **短期**: 当前 `seo.py` 的 GEO 检查已覆盖 7 个基础维度，接入 pipeline 即可
- **中期**: 引入 OpenSERP 研究数据反哺内容生成（已在 cli.py 注册命令）
- **长期**: 参考 MAGEO 的 strategy learning 架构，将 SEO 优化从"检查"升级为"自我优化"

---

## 2. 内容生成 — AI 写作工具 & Pipeline

| 项目 | ⭐ | License | 定位 | 链接 |
|------|:--:|:-------:|------|------|
| **ContentForge** | — | MIT | 11 阶段 pipeline + 29 模式去 AI 化 + C2PA 签名 + .docx 输出；企业级内容工厂 | https://github.com/smarks26/contentforge |
| **claude-blog** | — | MIT | 30 子技能 + 5 智能体 + 5 门交付合约 (≤90 分重写)；blog 全生命周期 | https://github.com/AgriciDaniel/claude-blog |
| **seo-blog-writer-claude** | 30 | MIT | Claude Code skill；6 条反 AI 检测规则 + 完整 SEO 字段填充 | https://github.com/rediumvex/seo-blog-writer-claude |
| **SEO Machine** | — | — | Claude Code 工作空间；10 智能体 + 5 分析模块；GA4/GSC/DataForSEO 集成 | https://github.com/kuishou68/seomachine |
| **Poindexter** | — | Apache 2.0 | 本地优先 Ollama 驱动；多模型对抗 QA + 抗幻觉验证；Grafana 可观测；LangGraph 编排 | https://github.com/Glad-Labs/poindexter |
| **WriteHERE** | — | MIT | 异质递归规划写作文法（arXiv:2503.08275）；任务分解 + 检索/推理/组合动态集成 | https://github.com/adsensex/WriteHERE |
| **gemini-blog** | 4 | MIT | Claude-blog 的 Gemini CLI 移植；12 模板 + 5 分类评分 (100 分) | https://github.com/imitry/gemini-blog |

### 关键观察
- **Pipeline 化 > 单次 Prompt**：ContentForge/Claude-blog 都验证了多阶段 pipeline 的产出质量远高于单次生成
- **Quality Gate 是标配**：所有成熟项目都有强制质量门，低于阈值自动重写
- **Anti-Hallucination 多策略合并**：多模型对抗审查 + 程序化验证 + URL 可达性检查
- **本地 LLM 路线可行**：Poindexter 用 Ollama + qwen3:8b + gemma3:27b 完成完整链路

### 对本项目建议
- 当前 `generator.py` 是单次生成的 fallback 模式
- 建议引入 **质量门机制**：生成后 → 评分 → 低于阈值触发重写（参考 claude-blog 的 5 门合约）
- 建议引入 **多模型对抗审查**：至少 2 个模型独立评分，综合判断（参考 Poindexter）

---

## 3. AI 文本去 AI 化 (Humanization)

| 项目 | ⭐ | License | 核心技术 | 链接 |
|------|:--:|:-------:|----------|------|
| **untell** | 3 | MIT | 闭环检测-重写循环；实时 GPTZero/Originality/Turnitin 反馈；语义保真门 | https://github.com/ssamba1/untell |
| **StealthHumanizer** | 66 | MIT | 35 提供商 + 4 级改写 + 6 风格 + 16 语言；12 指标本地检测；非 LLM 后处理 | https://github.com/rudra496/StealthHumanizer |
| **UnMask.AI** | 3 | MIT | 3-pass pipeline；25 检测模式；单 HTML 文件无服务器 | https://github.com/imsv1301/unmask-ai |
| **ai-humanizer** | 2 | MIT | 检测器引导外科手术式改写（arXiv:2506.07001）；锁定术语/数字/引用 | https://github.com/recomby-ai/ai-humanizer |
| **TextHumanizer** | — | MIT | 47 谄媚模式 + 词汇堆叠 + 模糊语言 + 破折号识别；多语言规则集 | https://github.com/edsondviana8/ai-humanizer-core |

### 关键发现
1. **检测信号 ≠ 连接词**：Band-9 IELTS 范文满篇 "furthermore" 但 ZeroGPT 仅 19.6%；真正信号是**流畅度**（丝滑 = AI）和**词汇可预测性**
2. **反复改写闭环 > 单次盲改写**：untell 的 closed-loop 比商业工具 (Undetectable.ai/QuillBot) 的单次改写更有效
3. **术语锁定是关键差异点**：粗鲁改写会破坏数字/引用/命名实体，ai-humanizer 的术语锁定机制是最佳实践
4. **语义门槛 0.76**（P-SP 阈值）：低于此值的改写会导致意义漂移

### 对本项目建议
- 当前 `voice_engine.py` 的 De-AI 处理 (呼吸音/停顿/语速波动/底噪) 只覆盖语音层面
- 应引入**文本级去 AI 化**：在 `humanize.py` 基础上集成逆折度检测 (perplexity/burstiness 注入)
- 参考 untell 的闭环架构：生成 → 检测 → 改写 → 再检测，直到通过

---

## 4. 视频制作 — AI 视频工具

| 项目 | ⭐ | License | 核心能力 | 链接 |
|------|:--:|:-------:|----------|------|
| **OpenMontage** | — | AGPLv3 | 12 管线 + 52 工具 + 500+ agent skills；零付费 API key 可运行；Remotion + HyperFrames 双引擎 | https://github.com/calesthio/OpenMontage |
| **ViMAX** | 10.9k | MIT | Idea→Video 全自动；多智能体 (导演/编剧/制片)；小说→视频适配 | https://github.com/HKUDS/ViMax |
| **CineGen** | — | MIT | 专业 NLE 编辑器 + AI 生成集成；50+ 模型；节点式工作流；LLM 聊天助手 | https://github.com/christopherjohnogden/CineGen |
| **Milimo Video** | 78 | — | 本地优先 NLE；LTX-2 19B 电影级生成；SAM 3 分割；Gemma 3 提示增强 | https://github.com/mainza-ai/milimovideo |
| **BlueFish** | — | — | 剧本→分镜→视频 Web UI；多提供商；角色/场景管理；ElevenLabs TTS | https://github.com/bluefish2026/BlueFish |
| **Kiwi-Edit** | 297 | MIT | 指令/参考引导视频编辑；MLLM 编码器 + 视频 DiT；Wan2.2-TI2V-5B 基础 | https://github.com/showlab/Kiwi-Edit |
| **LTX Desktop** | — | — | 首个开源本地 NLE AI 视频编辑器；LTX-Video 引擎；LoRA 支持；8GB VRAM | https://github.com/Lightricks/LTX-Video |

### 关键架构模式
| 模式 | 说明 | 代表项目 |
|------|------|---------|
| **Agent-is-Orchestrator** | AI 编码代理本身就是编排器，Python 脚本是工具，Markdown/技能文件是知识 | OpenMontage |
| **Pipeline-first** | 标准化工作流：研究→剧本→分镜→资产→组合→审查 | OpenMontage, ViMAX |
| **Provider Abstraction** | 统一的提供商接口，可随时替换底层模型 | OpenMontage (12 提供商), BlueFish, CineGen |
| **Self-review before render** | ffprobe/帧采样/音频分析/交付承诺验证 | OpenMontage |
| **Remotion 引擎** | React-based 程序化视频：弹簧动画、图表、字幕、场景过渡 | OpenMontage, 当前 AutoClip |

### 对本项目建议
- AutoClip 仅覆盖"视频高光提取"，缺乏完整的"创意→成片" pipeline
- 建议参考 OpenMontage 的 agentic 架构：Pipeline 是 Markdown 指令 → Agent 调用工具 → 自我审查
- Remotion 作为 React-based 视频引擎，适合生成数据可视化 + 动态字幕的短视频
- 本地 GPU 路线：Wan 2.1 / LTX-Video / CogVideo 可完全免费本地运行

---

## 5. 语音/TTS — 配音引擎

| 项目 | ⭐ | License | 核心能力 | 链接 |
|------|:--:|:-------:|----------|------|
| **Kokoro** | 7.5k | Apache 2.0 | 82M 参数 TTS；8 语言；24000Hz；速度质量比最优 | https://github.com/hexgrad/kokoro |
| **KokoClone** | 146 | Apache 2.0 | 基于 Kokoro-ONNX 的零样本声音克隆；文本→语音 + 音频→音频转换 | https://github.com/Ashish-Patnaik/kokoclone |
| **Sirène** | — | MIT | 自托管多后端 TTS 平台；Kokoro/Qwen3-TTS/F5-TTS/Piper/CosyVoice/OpenAudio/Chatterbox 7 后端 | https://github.com/KevinBonnoron/sirene |
| **F5-TTS** | — | — | 零样本声音克隆 + 流式生成；多语言 | — |
| **CosyVoice** | — | — | 9 语言；零样本克隆 + 情感控制 + 语速控制 | — |
| **Qwen3-TTS** | — | — | 阿里出品；10+ 语言；零样本克隆 | — |

### 当前状态对比

| 维度 | 当前 (voice_engine.py + edge-tts) | Kokoro | KokoClone |
|------|:---:|:---:|:---:|
| 语言 | 84+ (edge-tts) | 8 (en/zh/ja/fr/es/it/pt/hi) | 8 |
| 声音克隆 | ❌ | ❌ | ✅ zero-shot |
| 本地离线 | ❌ (需联网) | ✅ ONNX/GPU | ✅ ONNX/GPU |
| 去 AI 化 | ✅ (FFmpeg 后处理) | ❌ | ❌ |
| 内存 | ~200MB (python process) | ~500MB (82M 模型) | ~1GB |
| 延迟 | ~1-3s per segment | ~0.5-1s | ~1-2s |

### 建议
- **当前保持不变**：edge-tts 以 84 语言覆盖面 + 零部署成本是主力引擎
- **Kokoro 可作为离线备选**：在无网络环境下降级使用，或用于低延迟场景
- **KokoClone 评测优先**：如需声音一致性（同一角色多部视频），克隆功能是关键差异点
- **多后端路由**：参考 Sirène 设计，在 `VoiceEngine` 中实现多引擎可选 + 自动 fallback

---

## 6. 社交媒体分发 & 矩阵发布

| 项目 | ⭐ | License | 定位 | 链接 |
|------|:--:|:-------:|------|------|
| **BrightBean Studio** | 1.8k | AGPLv3 | 自托管社交管理；10+ 平台；MCP 接口；可视化日历；多工作区 | https://github.com/brightbeanxyz/brightbean-studio |
| **Open-Dispatch** | 3 | MIT | 单一 API 分发至 7 平台；自托管；JSONL/Redis/PG 队列；n8n 集成 | https://github.com/Matthew-Selvam/Open-Dispatch |
| **OpenPost** | 10 | MIT | Typefully 式编辑器；单二进制；5 平台；工作区 + 媒体库 | https://github.com/rodrgds/openpost |
| **USP** | 6 | MIT | 1 个 Markdown → 9 平台 (含 Reddit/Discord)；AI 平台适配；GitHub Action | https://github.com/adamarutyunov/usp |
| **SocialPulses** | — | — | 15+ 平台；FastAPI；PG + Redis；AI 内容生成；分析 + 报告 | https://github.com/newdim001/socialpulses |
| **MagicSync** | 41 | — | Nuxt 4 全栈；11 平台；AI 生成；批量调度；模板系统 | https://github.com/leamsigc/magicsync |

### 关键架构对比

| 特性 | 本项目 (publishers.py) | Open-Dispatch | BrightBean |
|------|:---:|:---:|:---:|
| 发布器数量 | 23+ (含新增 8) | 7 | 10+ |
| 队列/重试 | ❌ 仅内存重试 | ✅ JSONL/Redis/PG | ✅ |
| 调度 | ❌ | ✅ | ✅ 可视化日历 |
| API/MCP | ❌ | ✅ REST + n8n | ✅ REST + MCP |
| AI 内容适配 | ❌ | ✅ LLM per-platform rewrite | ✅ |
| 媒体转码 | ❌ | ✅ 10 平台规格 | ✅ |
| 分析/报告 | ✅ metrics.py | ❌ | ✅ |

### 建议
- **Open-Dispatch 设计最契合**：MIT + FastAPI + 单文件分发模式，与我们的 `publishers.py` 理念一致
- **引入队列机制**：将当前同步 `_deliver()` 升级为异步队列，支持重试 + 速率限制（参考 Open-Dispatch 的 JSONL 队列）
- **BrightBean MCP**：可直接从 AI Agent 调度发布，与我们的 agent-neutral 理念对应
- **USP 的 Markdown→跨平台**：一个源文件自动适配多平台格式，可与 `copy_manager.py` 整合

---

## 7. 内容研究 & 题材发现

| 项目 | ⭐ | License | 定位 | 链接 |
|------|:--:|:-------:|------|------|
| **OmniSearch** | 1 | — | 多智能体自主研究平台；MCTS 查询分解 + Crawl4AI + pgvector 混合检索 | https://github.com/CypherXXXX/OmniSearch |
| **crawl4ai** | — | Apache 2.0 | 大规模 LLM 友好的网页提取；Markdown 输出 | https://github.com/unclecode/crawl4ai |
| **ScrapeGraphAI** | — | — | LLM + 图逻辑驱动的爬虫管线 | https://github.com/ScrapeGraphAI/Scrapegraph-ai |
| **Firecrawl** | — | — | 搜索/抓取/交互 API；Markdown + 结构化数据 | https://github.com/firecrawl/firecrawl |
| **FeedRay** | 3 | Apache 2.0 | RSS→事件聚类→时间线→推荐；pgvector + 重要性评分 | https://github.com/johnvonneumann36/FeedRay |
| **Clawler** | 2 | MIT | 75+ 源 CLI 新闻聚合；智能去重；质量评分；8 输出格式 | https://github.com/clawdiard/clawler |
| **PipePost** | — | — | AI 内容策展管线：发现→翻译→改写→分发；OpenClaw 23+ 渠道 | https://github.com/densul/pipepost |

### 建议
- **Firecrawl**：替代当前简单的 `data_collector.py`，提供 LLM 友好的结构化网页提取
- **Clawler**：作为趋势源替代/补充 `github_star_explorer.py`，75+ 源覆盖面更大
- **FeedRay 的事件聚类**：将离散的趋势项聚类为持续事件，提升内容策划深度
- **OmniSearch 的 MCTS 查询分解**：可应用于 `intelligence.py` 的 research_topic 流程

---

## 8. 内容分发 — RSS / Newsletter / 邮件

| 项目 | ⭐ | License | 定位 | 链接 |
|------|:--:|:-------:|------|------|
| **AI Newsletter Agent** | — | MIT | 90+ 文章评分 → 精选 25 → LLM 写社论 → 发布；$0.006/run；6 行业配置 | https://github.com/anmolgupta824/ai-newsletter-agent |
| **Broadside** | 1 | AGPLv3 | AI-native 自托管 Newsletter 平台；RSS/GitHub/HN 源 + 管线阶段 | https://github.com/hizachlee/broadside |
| **RSS AI Digest** | — | GPLv3 | RSS→LLM 筛选→翻译→HTML 渲染→Resend 发送；GitHub Actions 自动化 | https://github.com/wyivz/rss_AI_digest_email_pipeline |
| **feedmail** | — | AGPLv3 | Cloudflare Workers 驱动的 RSS→邮件微服务；双重选择加入；零追踪 | https://github.com/alexmensch/feedmail |
| **rss2newsletter** | — | — | 任意 RSS→邮件 Newsletter；Mailchimp RSS-to-email 替代 | https://github.com/ElliotKillick/rss2newsletter |

### 建议
- **Newsletter 管线**：这是本项目缺失的一大块。RSS→筛选→翻译→模板→发送的完整链路
- AI Newsletter Agent 的评分+社论模式可复用：收集素材 → LLM 评分 → 精选 → 写开篇
- feedmail 的零追踪设计适合隐私优先的内容分发
- 可结合 `content_platform/publishers.py` 新增 Newsletter 发布器（已有 Buttondown）

---

## 9. 工作流自动化 & MCP 生态

| 项目 | ⭐ | License | 定位 | 链接 |
|------|:--:|:-------:|------|------|
| **n8n + MCP** | — | Fair-code | 400+ 集成 + 原生 MCP 支持；AI Agent 节点可调用 MCP 工具；HITL 审查 | https://n8n.io |
| **n8n Unified MCP Server** | — | — | 30 工具 → AI Coding Agent 控制 n8n 工作流 | https://github.com/anshwysmcbel2710/n8n-unified-mcp-server |
| **mcp-agent** | — | Apache 2.0 | MCP 全栈框架；自动管理 MCP server 生命周期；OpenAI/Anthropic agent | https://github.com/lastmile-ai/mcp-agent |
| **n8n MCP Client Node** | — | — | n8n 社区节点，在 workflow 中调用 MCP server 工具 | https://github.com/nerding-io/n8n-nodes-mcp |

### 对本项目的建议

- **n8n 作为调度层**：systemd 定时器触发 n8n workflow，n8n 内串联多步骤（趋势获取→生成→审查→分发）
- **MCP 接口**：将 `content_platform` 的功能封装为 MCP server，使外部 AI agent 可直接调用：
  - `trends()` → 获取热点话题
  - `create_job()` → 创建内容任务
  - `publish()` → 发布到指定平台
  - `geo_check()` → GEO 质量检查
  - `voice_generate()` → 配音生成
- **HITL (Human-in-the-Loop)**：利用 n8n 的审批节点，在关键环节（发布前审查、任务分配）引入人工确认

---

## 10. 优先级建议 (团队讨论)

### P0 — 尽快落地 (1-2 周)
1. **GEO 接入 pipeline**：`pipeline.run()` 后自动运行 `geo_check()`，结果写入 `draft_meta`
2. **引入发布队列**：参考 Open-Dispatch 的 JSONL 队列模式，替换当前同步 `_deliver()`
3. **系统化去 AI 化**：文本层面集成 StealthHumanizer/untell 的关键模式到 `humanize.py`

### P1 — 中期优化 (2-4 周)
4. **质量门机制**：参考 claude-blog 的 5 门交付合约，引入"评分+自动重写"机制
5. **多后端 TTS 路由**：Kokoro 离线备选 + KokoClone 声音克隆（同一角色多视频场景）
6. **Newsletter 管线**：RSS→筛选→翻译→邮件 完整链路

### P2 — 架构演进 (1-3 月)
7. **MCP Server 封装**：将 content_platform 能力封装为 MCP 工具
8. **Agentic GEO**：参考 MAGEO/FeatGEO 的策略学习架构
9. **本地 LLM 路线**：Ollama + qwen3 做低成本内容生成 + 评分

### P3 — 探索方向
10. **Video Pipeline 升级**：参考 OpenMontage 的 agentic 架构重建视频生成链路
11. **n8n 深度集成**：用 n8n 替换 systemd 定时器做复杂工作流编排
12. **多模型对抗审查**：至少 2 个独立 LLM 对产出质量交叉评分
## 2026-07-07 Three-End Consistency Repair Wave

### Goal

Bring the local workspace, GitHub main branch, and Hermes server runtime back to one auditable baseline while keeping the repository publishable and the server deployment continuously usable.

### Real Findings

- Local and GitHub were aligned at commit `e3944b0`.
- Hermes had two repository copies:
  - active runtime copy at `~/.ai-self-media-tools`
  - stale secondary copy at `~/ai-self-media-tools`
- The active server copy was on the correct commit, but it mixed runtime files into the working tree.
- The repository still contained tracked machine-specific references:
  - Hermes-home absolute paths
  - server-specific deployment notes
  - Linux-only cwd assumptions in tests
- `project-audit` and the full test suite were not green before this wave.

### Local Fixes Applied

- Reworked `content_platform.project_audit` so ignored runtime directories such as `data/`, `secrets/`, `logs/`, `artifacts/`, `outbox/`, and `cookies/` do not invalidate the publishable scan.
- Replaced hardcoded Hermes absolute paths in `content_platform.skills_adapter` with `${HERMES_HOME}` or `~/.hermes` resolution.
- Removed the duplicate broken early `seo-geo-check` branch in `content_platform.cli`.
- Updated package version metadata from `3.4.0` to `3.5.0` to match the current release line.
- Fixed cross-platform CLI tests so they no longer assume a Linux-only working directory.
- Rewrote Hermes/Open Notebook related docs and skill notes to be path-neutral and publish-safe.

### Server Fixes Completed

- Kept `~/.ai-self-media-tools` as the only authoritative runtime copy.
- Archived the stale `~/ai-self-media-tools` copy under `~/archive/ai-self-media-tools-stale-20260707`.
- Replaced token-bearing remote URLs in both server-side repository copies with the clean public remote form.
- Kept runtime data under ignored paths only so the active runtime tree still passes `project-audit`.

### Validation Evidence

- local commit: `4b17771`
- GitHub `origin/main`: `4b17771`
- server active runtime commit: `4b17771`
- local `python -m content_platform project-audit`: `ok: true, scanned_files: 107`
- local `python -m pytest -q`: `144 passed`
- local `python scripts/release_bundle.py --target <temp-dir>`: passed
- server `python3 -m content_platform project-audit`: `ok: true, scanned_files: 107`
- server `python3 -m pytest -q`: `144 passed`
- server `systemd` authority confirmed:
  - `WorkingDirectory=%h/.ai-self-media-tools`
  - `CONTENT_PLATFORM_HOME=%h/.ai-self-media-tools`

### Notes For Future Contributors

- This repository may be deployed into a live runtime directory, but tracked files must remain path-neutral and publish-safe.
- Runtime-only state must stay inside ignored paths or outside the repository mirror entirely.
- Server access details, private tokens, and machine-specific deployment paths must never be written into tracked docs again.
