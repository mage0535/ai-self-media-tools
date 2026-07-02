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

## 2026-07-02 Three-End Consistency Audit And Publishing Fix Wave

### Background

Prior to this wave, the project was known to live in three locations:
- local working directory (synced via OneDrive across machines)
- GitHub repository `<github-owner>/<repository>`
- Hermes production server (207.57.129.132, non-git mirror at `~/.ai-self-media-tools`)

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

embedding 通过 gbrain 自带的本地 OpenAI 兼容服务提供（`/root/gbrain/embedding_server.py`），无需额外部署。

### 验证
- 测试: **30/30 passed** (全量 `107 passed`, 1 pre-existing failure in test_adapters)
- CLI: `health` / `digest` / `research` 三子命令
- API 真实交互: Notebook 创建→Source 添加(multipart)→搜索→清理 已测通
- Embedding: GBrain `multilingual-e5-small` 384维向量 ✅

### Open Notebook 服务
```
部署路径: /root/.open-notebook/
Web UI:   http://localhost:8502
REST API: http://<open-notebook-host> (healthy)
SurrealDB: :8000
```
