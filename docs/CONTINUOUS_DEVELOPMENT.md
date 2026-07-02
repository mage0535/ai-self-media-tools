# Continuous Development

Last updated: 2026-07-02

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
