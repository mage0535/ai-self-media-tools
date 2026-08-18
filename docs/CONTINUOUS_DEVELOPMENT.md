# Continuous Development

## 2026-08-16: bounded video narration and renderer budget guard

### Implemented
- Pinned `bin/content-platform` to LF in `.gitattributes`. A server checkout with CRLF made Bash append `\r` to CLI subcommands, which made `project-audit` and other commands fail despite the Python module being healthy.
- `MediaBridge` now compiles a separate `video_script_v1` before any cinema or standard video renderer runs. It preserves the article body for publishing, converts narration into at most eight paragraph-separated beats, and caps each beat at 40 characters.
- Every video artifact directory now contains `video_script_manifest.json` with the source, input/output character counts, beat count, and exact narration passed to the provider. This is the audit source for proving that a video did not narrate an entire long article.
- `film_renderer.py` now rejects invalid TTS timing before launching browser or FFmpeg work: a segment over 20 seconds or total narration over 100 seconds fails closed. Limits are configurable only through `FILM_RENDERER_MAX_SEGMENT_SECONDS` and `FILM_RENDERER_MAX_TOTAL_SECONDS` for a separately declared long-form plan.

### Root Cause And Verification
- An isolated Douyin AI canary reached the real renderer after trend, content, image, and quality gates, but exposed a production contract error: the full article body was passed to the video renderer and produced a 265-second TTS segment. The canary was stopped without delivery or publication.
- The next isolated canary exposed two separate fail-closed defects: one transient Edge TTS `NoAudioReceived` response aborted rendering instead of retrying, and generic card rendering omitted `tts_config.json`. The renderer now retries boundedly after deleting an empty partial file, records every segment's display text, compiled TTS text, provider and measured duration, and acceptance resolves the registered MP4's directory instead of assuming the database and artifact directories are siblings.
- A route-specific follow-up found the same gap in `film_renderer.py`: content-driven routing could bypass the generic renderer's TTS safeguards. The cinema renderer now uses the same bounded Edge retry behavior and writes the canonical `tts_config.json` in addition to its legacy `tts_records.json`; it cannot hand off without the same audio evidence.
- Fixed an upstream platform-definition drift: `douyin_ai` and `douyin_pet` are short-video lanes everywhere the strategy, source classifier, and video-plan builder decide content form. A low-visual-score video slot now chooses `knowledge_card_video` rather than a checklist article. Video prompts require eight short narration paragraphs (280-420 Chinese characters) and use a smaller focused style context, reducing provider latency and preventing long-article generation from reaching renderers.
- Regression coverage verifies long-draft compaction, oversized explicit-script normalization, manifest persistence at the provider boundary, and fail-closed runaway-duration rejection. Focused video regressions passed locally.
- Required follow-up acceptance is an isolated `handoff` canary. It must produce `video_script_manifest.json`, a bounded final MP4, packet/quality evidence, and `handoff_ready`; it must not create a live delivery or publication.

## 2026-08-12: WeChat Publish License Gate Acceptance

### Implemented
- Overnight provider reliability: the generator now sends its configured Hermes provider and model explicitly, classifies printed HTTP 401/403/429/5xx responses before JSON parsing, and records a stable provider failure code rather than treating an authentication message as draft content. The nightly wrapper runs a systemd-equivalent provider JSON smoke before it creates any jobs.
- Overnight result semantics: failed platform rows remain terminal for safe resume but aggregate to batch `failed`; expected source/strategy blocks aggregate to `partial`; only a batch without failed or blocked due work is `completed`. The systemd wrapper now emits distinct completed, partial, blocked, and failed notifications and returns nonzero for failed or non-admitted batches.
- Accepted the Hermes-side WeChat publish-license direction but corrected the integration to fail closed. `scripts/hermes_wechat_adapter.py` now blocks when the license script is missing, returns invalid JSON, exits nonzero without a clear block payload, or receives an empty title.
- Added `scripts/gzh_publish_license.py` to the publishable repository so the live server no longer depends on an untracked script. The script enforces the WeChat cadence gate before draft push: at most three recent WeChat articles in seven days, no 00:00-06:00 publish window, recent title similarity blocking, and homogeneous title keyword blocking.
- Follow-up acceptance fixed over-counting in the cadence gate. The script now counts only structured WeChat recap records with delivery evidence plus successful publish receipts / delivery queue rows. Bare generated jobs and unstructured Markdown operation recaps are not counted as delivered articles.
- Kept the private v5 strategy file server-local under ignored `data/`; publishable code contains only generic policy logic and no account-private strategy tables.

### Acceptance Notes
- Hermes-side change was directionally correct: putting the gate inside `publish_packet()` is the right integration point because it runs before token/theme/draft operations.
- Original live patch had a P0 bypass: if the license subprocess failed or printed invalid JSON, the adapter defaulted to `passed=True`. That has been replaced with explicit `blocked` results.
- The first publishable version also counted ordinary `jobs` rows and Markdown recap headings, which could report six recent WeChat items on Hermes even when the v5 policy baseline intended three current structured article records. That has been corrected to evidence-based counting.
- The server-local `channel-operations-workflow` skill correctly references `data/growth_strategy_20260812.md` and the publish-license reference, but this remains a server skill update rather than public repository code.

### Verification
- New tests cover missing title, missing script, invalid JSON output, and `publish_packet()` blocking before WeChat API work when the license fails.
- New cadence tests prove bare WeChat jobs and unstructured Markdown recaps are ignored, while successful WeChat publish receipts are counted.
- Focused local regression: `tests/test_hermes_wechat_adapter_script.py tests/test_publishers_v2.py tests/test_wechat_growth_strategy.py tests/test_wechat_toolchain.py` => `34 passed, 10 subtests passed`.
- Project audit returned `ok: true`.

## 2026-08-12: Strategy Routing and Recoverable Overnight Execution

### Implemented
- Background-resource hardening: content-generating background tasks now fail closed when the required account growth strategy snapshot is missing or stale. `overnight-prepare` records `growth_strategy_status` and blocks only the affected platform row instead of silently selecting a topic.
- `scripts/run_overnight_batch.sh` now runs `performance-cycle` before `overnight-prepare`, so midnight batches refresh analytics and `growth_strategy:<platform>:latest` before topic selection.
- The legacy `auto` command now checks the same growth-strategy snapshot status before creating jobs. Missing/stale strategy returns a blocked platform result and does not run Pipeline generation.
- `hermes-content-platform.service` now refreshes growth strategy before its `auto` run. `hermes-content-platform-growth-cycle.service` now covers the full default platform set: WeChat, Kuaishou, Bilibili, Zhihu, Juejin, Douyin, Shipinhao, Xiaohongshu, YouTube, TikTok, and X.
- Background task boundary after audit: growth-cycle refreshes strategy only; overnight and auto refresh then consume strategy; health-refresh refreshes delivery health; metrics/metrics-server expose status; maintenance prunes runtime data; task-market accepts external task-market jobs and remains separate from account-growth strategy routing.
- Added `growth_recipe_v1`, generated before quality evaluation. It records actual source status, topic-growth signals, selected tools, process evidence for tool demonstrations, and a concrete CTA. In enforced mode, incomplete recipes block rather than silently falling back to generic card content.
- The `auto` command now creates one job per platform with platform-scoped topic history and collection evidence. It no longer creates one multi-platform job and treats a shared trend as independent platform analysis.
- Added `overnight-plan` and `overnight-run`. Plans reserve the final ten minutes before the 05:00 morning-report window, reject work that cannot fit before admission, run one platform at a time, and atomically checkpoint state after every platform.
- Manual channels normalize to `handoff_ready`; overnight execution does not implicitly approve or publicly publish any channel.
- Added append-only, redacted `events.jsonl` for real-time Hermes reporting that survives an agent-session or process restart.
- Added unenabled systemd templates for a midnight direct worker. The worker does not use a Hermes conversation as its execution context and exits safely when no private due-channel slots file exists.
- Follow-up hardening: the systemd entrypoint now rejects a late persistent-timer catch-up outside its bounded 60-minute admission window, so a reboot cannot shift content work into the 05:00 morning-report window. The service uses an explicit `CONTENT_PLATFORM_BIN` because systemd does not guarantee `HOME`.
- First dry-run capacity check rebalanced the private weekly rotation so every due-day plan fits the 280-minute work budget; the run created no jobs or publications.

### Verification
- Added regressions for missing growth-strategy snapshots in `overnight-prepare`, core due-task building, the legacy `auto` command, and systemd/script ordering.
- Focused regressions for growth recipes, independent auto routing, the resumable batch, CLI, and Pipeline passed.
- Full local regression: `629 passed, 29 subtests passed`.
- Compile, whitespace, and project audit passed locally. Target-server synchronization and repeat verification remain required before enabling the new timer.

## 2026-08-11: render evidence and truthful source evidence

- Added a bounded tool catalog: Shotcraft/OpenMontage/KrillinAI are pattern or reuse sources, while Agent-Reach is collection-only and never a publisher.
- Final original-video acceptance now requires both frame-difference evidence and per-segment Shotcraft-to-FFmpeg evidence. A plan or manifest declaration is not execution proof.
- Generation no longer marks planned sources as successful collection. Missing channel evidence is represented as unavailable and must be repaired or explicitly degraded before a platform-independent source gate can pass.
- Manual delivery packets now use `handoff_ready` in the delivery queue rather than `completed`; prepared output is not a public post.
- Added `docs/ACCEPTANCE_COMMANDS.md` for Hermes read-only verification.

## 2026-08-11: resumable video rendering without lowering quality gates

- `scripts/pre_render_gate.py` validates card text, placeholders, source paths, required cover/background inputs, and BGM provenance before expensive rendering. A quiet source track is classified for automatic gain handling rather than rejected when it is repairable.
- `scripts/build_subtitles.py` is the shared ASS subtitle builder for Kuaishou, Douyin, Shipinhao, TikTok, YouTube, and Bilibili. It writes dot-format timestamps, platform-safe lower-third profiles, bounded line wrapping, and accepts UTF-8 BOM card files from Windows.
- `scripts/render_checkpoint.py` stores input/output hashes for cards, TTS, segments, concat, and final output. Existing legacy `.done` markers are adopted once for backward compatibility; later input changes rerender only affected stages.
- `scripts/render_timing.py` records per-stage duration evidence and writes `render_timing_summary.json` in each render directory so speed work targets measured bottlenecks rather than removing quality checks.
- Final H.264 encoding defaults to `VIDEO_FINAL_PRESET=fast` (CRF 23, baseline, yuv420p). It was benchmarked against `medium` on Hermes before adoption; operators may explicitly set `medium` for a slower fallback. The selected profile is part of the final checkpoint and is written to `final_encode_settings.json`.
- `scripts/kuaishou_render.py` now uses the shared subtitle service, runs the pre-render gate, reuses only hash-matching intermediate artifacts, waits for browser fonts/images instead of fixed per-card sleeps, and carries the validated stronger layered background motion. It is also safe for UTF-8 console output on Windows.
- `scripts/video_toolchain_runner.py` passes the selected platform into the renderer so subtitle safe areas are platform-specific.
- The common video runner now requires eight distinct narrative beats before a real render and writes `pre_render_gate.json` for every generated card package. It no longer expands short scripts with `Step N` or generic production instructions.
- Timing evidence now distinguishes a real render from a hash-checkpoint reuse and is written atomically.
- BGM policy remains strict: a new video selects a new licensed real-instrument track. Metadata, license evidence, and fingerprints may be cached for lookup and collision prevention, but an old BGM or `final.mp4` is never reused for a different video.

Last updated: 2026-08-11

## 2026-08-10 Zhihu Open Platform Skill/MCP Integration

- Root cause: Hermes had installed the Zhihu Open Platform skill and a server-local adapter, but the publishable local/GitHub code did not yet contain the adapter, MCP tools, or explicit capability probes. That made the feature usable on the live server only as a dirty runtime patch.
- Added `content_platform.zhihu_open_adapter`, a read-only wrapper around the `zhihu-search` CLI. Credentials stay in the CLI-managed runtime config; repository code contains no Access Secret and no server-private path.
- Zhihu trend collection now tries the official open-platform hot list first, then falls back to the existing cookie-based `zhihu` CLI and the previous web-search fallback. This lets the heat/topic workflow use the new channel automatically without making production depend on it exclusively.
- MCP now exposes `zhihu_open_search`, `zhihu_open_ask`, `zhihu_open_user_contents`, `zhihu_open_user_followees`, `zhihu_open_user_collections`, `zhihu_open_trending`, and `zhihu_open_quota`. `capability_status` lists the same tools so Hermes lazy discovery/auto-wake can see them before execution.
- `ToolRegistry.probe()` now reports `zhihu_open_platform`, `zhihu_publisher_skill`, and `zhihu_open_cli`, making it possible to distinguish "Zhihu skill installed" from "Zhihu open-platform CLI callable".
- Follow-up server validation found `zhihu-search` installed in the default user binary path but not on PATH. `ToolRegistry` now checks `ZHIHU_SEARCH_BIN`, PATH, and the default user binary path so Hermes capability discovery does not falsely report the open-platform CLI as unavailable.
- Follow-up deep scan found that `python -m content_platform.mcp_server` did not execute `main()`, so Hermes MCP registration could not reliably auto-start the server. The module now has a real CLI entrypoint and a regression test for `--help`.
- Hermes runtime registration was completed as a stdio MCP named `content-platform`. `hermes mcp test content-platform` discovered 20 tools, including all 7 `zhihu_open_*` tools, confirming that new Hermes sessions can auto-wake this project MCP instead of relying on manual imports.
- Verification targets: `tests/test_zhihu_open_adapter.py`, `McpServerTests.test_zhihu_open_platform_tools_are_exposed_for_mcp_autowake`, `McpServerTests.test_mcp_server_module_exposes_cli_entrypoint`, and `ToolRegistryTests.test_registry_reports_zhihu_open_platform_skill_and_cli`.

## 2026-08-10 Hermes Runtime Drift Cleanup For Video And Metrics

- Resolved the remaining server drift that was not part of the Zhihu adapter itself. The preserved online changes were production fixes, not local-only state, so they were promoted into the publishable code path with regression coverage.
- `content_platform.performance_collectors` now normalizes `socks5h://` to `socks5://` before launching Playwright. This matches Chromium's supported proxy scheme and prevents creator-backend collection from failing with unsupported-proxy errors.
- `scripts.kuaishou_render` accepts a valid existing BGM only while resuming the same hash-identified render package; every newly planned video must select a distinct licensed real-instrument track. The minimum real-BGM size remains 500 KB for short licensed clips. The text layer has continuous overlay motion independent from the background layer.
- `scripts.render_landscape_video` now renders background and text as separate layers and composes them with `zoompan` background motion. This prevents landscape videos from degenerating into static cards.
- Verification targets: `PerformanceCollectorTests.test_backend_browser_route_normalizes_socks5h_for_playwright`, `VideoToolchainRunnerTests.test_kuaishou_layered_text_filters_are_distinct_motion_paths`, `VideoToolchainRunnerTests.test_bgm_download_reuses_valid_existing_bgm`, and `VideoToolchainRunnerTests.test_landscape_renderer_uses_separate_background_and_text_layers`.

## 2026-08-10 Operations Evidence Gates And Final-Artifact Verification

- Added `content_platform.ops_run` and `scripts/ops_run.py`. A date-scoped manifest now records topic direction choices before generation. Same-direction topics are blocked across platforms even when titles use different wording; a documented follow-up must carry the prior platform, a distinct angle, and a reader-facing reason.
- `scripts/check_platform_topic_independence.py` now reads the same-date direction register. This closes the old bypass where source-matrix checks passed while multiple platforms selected the same core direction.
- Added `content_platform.video_artifact` and `scripts/verify_video_artifact.py`. Final-video checks inspect the encoded artifact and render manifest for vertical dimensions, short duration, subtitle dimensions, placeholder titles, and measurable motion. `video_toolchain_runner.py` writes card-title/subtitle evidence and fails the render if the final artifact gate fails.
- Added an executable operations-policy contract plus `scripts/audit_strategy_skill_conflicts.py`. `validate_channel_rulebook.py` now blocks when declared WeChat cadence, newspic dual-track, vertical subtitle format, short duration, or layered-motion rules drift from the public policy contract.
- The quality directive now documents the required run order and resolves the old 40-100 second short-video wording: vertical short-video platforms have a hard 60-second maximum, while long-form requires its own plan.
- Verification: new regression coverage plus existing related suites passed; the final handoff must still run the complete test suite, rulebook validation, and project audit in the target runtime.

## 2026-08-08 Zhihu Similarity Recovery And Cross-Platform Anti-Spam Gate

- Zhihu companion pins no longer reuse an article title or opening paragraph. `content_platform.zhihu_promotion` now generates an independent short commentary and validates it for source overlap, title overlap, copied article fragments, content length, discussion question, and visible article URL before publish mode can call the Zhihu CLI.
- `scripts/zhihu_pin_promotion.py` now prints validation evidence in review mode and fails closed in publish mode when the anti-spam gate rejects the pin. This addresses the platform risk where a pin is limited to self-visible because recent content is highly similar or low-value.
- The rulebook now has `anti_spam_similarity_policy` for all channels and a Zhihu-specific `short_form_policy`: review-first pins, one pin per article, at least 48 hours between pins, no article excerpt as pin hook, and answer/article/pin differentiation.
- Growth strategy now covers Zhihu and Juejin. Zhihu carries `zhihu_similarity_recovery`, while Juejin requires engineering-specific value and must not reuse Zhihu or WeChat copy.
- Verification: Zhihu promotion/growth tests passed, full pytest passed, channel rulebook validation passed, and project audit returned 0 issues.

## 2026-08-08 Platform Boundary And International Growth Hardening

- Bilibili is now aligned with the operator boundary used by the runtime: generate a complete local handoff package for user publishing, not automatic upload or schedule. The rulebook now requires manual handoff, platform render identity, media delivery evidence, BGM source, and no cross-platform final-video reuse.
- YouTube and TikTok now have explicit growth rules and remain manual-handoff-only with AiToEarn publishing forbidden. Their packets must carry platform render identity, media delivery contract, unique render evidence, and anti-spam similarity planning.
- X/Twitter now has short-form growth rules: one specific observation per post, no repeated link dump, a reply/profile-click prompt, max one post per run, and at least 24 hours between similar posts.
- `content_platform.content_policy` now treats YouTube as a manual-handoff platform, matching the rulebook and preventing future publisher-routing drift.
- Verification: platform-boundary tests passed, full pytest passed, channel rulebook validation passed, and project audit returned 0 issues.

## 2026-08-08 Data-Driven Growth Response And Metrics Trust Hardening

- Performance-cycle now rejects more creator-backend scrape artifacts before they can update strategy: Bilibili likes without reach, huge Juejin-style view counts with tiny engagement, Xiaohongshu page-chrome work counts, and TikTok zero-view save placeholders.
- Growth strategy now carries `data_driven_improvement_plan`. Low engagement triggers hook/cover/comment-prompt rebuilding; low saves trigger checklist density and knowledge-card payoff; low follow conversion triggers explicit series promise and profile follow reason; missing metrics require 1h/24h/72h collection before confidence is raised.
- `config/growth_quality_policy.json` and the rulebook require this improvement plan before generation, so future content work cannot ignore current account performance.
- Verification: performance-cycle tests passed, full pytest passed, channel rulebook validation passed, and project audit returned 0 issues.

## 2026-08-01 Public Release 1.0.0

- Public version unified to `1.0.0` in package metadata, runtime version output, examples, and GitHub-facing docs.
- GitHub README files were rewritten in clean Chinese and English for external operators.
- Added `scripts/onboard_operator.py` as a beginner-friendly wizard for local checks, config creation, platform binding guidance, tool matching, and workflow reminders.
- Added `RELEASE_NOTES_1.0.0.md` for GitHub Releases.
- Public distribution remains privacy-safe: release bundles copy only Git-tracked files, skip runtime/private paths, and audit both source and target.

## 2026-08-01 Growth Metrics And Retired Baijiahao Cleanup

- Baijiahao is retired from current routing. It is no longer included in current domestic platform selection or Chinese-platform language inference. Historical rows may remain in old databases, but new regional automation should not select it.
- Performance review storage now records the growth metrics required by the rulebook: saves, follows, completion rate, three-second view rate, and average watch seconds. `feedback-summary`, historical performance context, and Prometheus metrics expose these fields so growth strategy can use real review data instead of only views/likes/comments/shares.
- `scripts/image_gen.py --skip-preflight` and `--skip-visual-gate` remain available for legacy CLI compatibility but now require `IMAGE_GEN_ALLOW_SKIP_GATES=1`; otherwise the command fails closed.
- Verification: local full test suite passed, project audit returned ok, and channel rulebook validation passed after the change.

## 2026-08-01 Hermes Drift Review Cleanup

- Remaining Hermes runtime edits were reviewed and normalized back into the project: generator evidence now carries explicit asset mix and humanization inputs, Pipeline keeps full-ops brief fields when using pre-populated body content, and Zhihu publishing tolerates an intentionally empty proxy instead of passing a blank Playwright proxy.
- Kuaishou video quality remains strict vertical-only. The temporary Hermes relaxation that accepted horizontal `1280x720` output was not kept, and a regression test now rejects horizontal video probes.
- Unreferenced `scripts/dynamic_mix.py` was removed from Hermes runtime. The supported BGM path remains the guarded `mix_bgm_with_gate.py` / video toolchain route, so future work does not accidentally use an unverified parallel mixer.
- Verification: local and Hermes full test suites passed, project audit returned ok, and channel rulebook validation passed after the cleanup.

## 2026-07-11 Project Alias Registry Wave

### Goal

Reduce future multi-agent project confusion by defining a stable public alias
for this repository and separating public alias policy from server-private path
registries.

### Work Completed

- defined the primary public alias for this repository as `自媒体推广工具`
- kept `AI自媒体运营推广工具` as a compatible legacy alias
- added a publishable alias-policy document:
  - `docs/PROJECT_ALIAS_POLICY.md`
- added a publish-safe agent-neutral routing snippet:
  - `docs/AGENT_CONTEXT_SNIPPET.md`
- documented that server-specific absolute paths must live in a private alias
  registry outside the repository
- reserved distinct naming space so this repository is not treated as a loose
  synonym for:
  - generic `promo`
  - generic `matrix`
  - older `content-platform` mirrors or backups

### Expected Hermes Usage

- `自媒体推广工具` should resolve only to this repository and its paired
  domestic browser-publishing runtime
- similar parallel workspaces such as promotion matrices or older content
  stacks should use their own aliases and their own anchor sets

## 2026-07-11 Domestic Browser Publisher Recovery Wave

### Goal

Fix the server-side mismatch between the main project and the working browser-publishing toolchain, restore a maintainable Bilibili path, and make the new Douyin Chrome/cookie workflow a first-class publisher backend instead of a one-off server script.

### Root Cause

- The active project expected `social-auto-upload` under `CONTENT_PLATFORM_HOME/external/social-auto-upload` unless `SOCIAL_AUTO_UPLOAD_HOME` was set.
- The server's working browser-publishing tool was installed as a separate runtime directory, so the main project could not reliably discover it.
- The active project had no runtime `config.json`, so Douyin/Bilibili publisher selection fell back to defaults or older AiToEarn/env-cookie assumptions.
- Bilibili had two incompatible credential models in circulation:
  - the older built-in publisher expects `BILIBILI_SESSDATA` / `BILIBILI_JCT`
  - `social-auto-upload` expects `cookies/bilibili_<account>.json`
- No `bilibili_<account>.json` file was found during the server inspection, so Bilibili credentials could not be reconstructed from the filesystem.

### Work Completed

- `social_auto_upload_home()` now resolves in this order:
  - explicit `SOCIAL_AUTO_UPLOAD_HOME`
  - bundled `CONTENT_PLATFORM_HOME/external/social-auto-upload`
  - user-home sibling `~/social-auto-upload`
- `delivery-readiness` now reports:
  - resolved `social-auto-upload` home
  - project and Python runtime existence
  - lightweight CLI startup probe
  - Douyin and Bilibili cookie/account file counts
- platform binding checks now treat Douyin, Bilibili, and Xiaohongshu as `social-auto-upload` account-file based bindings instead of hardcoding Bilibili to `BILIBILI_SESSDATA`.
- `SocialAutoUploadPublisher` now supports `video_extra_args` and `note_extra_args`, so Bilibili category `--tid` and future platform-specific CLI flags can be configured without code changes.
- added generic `FallbackPublisher`, so a new browser backend can be tried first while an older backend remains available as a rollout safety path.
- README now documents the domestic browser publisher model, Bilibili recovery login command, and future channel integration pattern.

### Server Remediation Applied

- The active runtime should keep `CONTENT_PLATFORM_HOME` pointing at the main project runtime directory.
- The external browser publisher should be exposed through `SOCIAL_AUTO_UPLOAD_HOME`.
- The runtime `config.json` should map Douyin and Bilibili to `type: "social-auto-upload"` with `account_name: "main"`.
- During recovery, Douyin and Bilibili can use `type: "fallback"` with `social-auto-upload` first and the previous draft backend second.
- Bilibili recovery requires a fresh interactive login if `cookies/bilibili_<account>.json` is absent:

```bash
cd "$SOCIAL_AUTO_UPLOAD_HOME"
./venv/bin/python sau_cli.py bilibili login --account <account-alias>
./venv/bin/python sau_cli.py bilibili check --account <account-alias>
```

### Validation

- Local targeted regression tests: `14 passed`
- Local full suite: `161 passed`
- Local `project-audit`: `ok: true`
- Server full suite: `161 passed`
- Server `project-audit`: `ok: true`
- Server `social-auto-upload` checks:
  - Douyin `main`: `valid`
  - Bilibili account: `invalid` until `cookies/bilibili_<account>.json` is created by interactive login; fallback backends are configured.
- Added tests for:
  - configured `SOCIAL_AUTO_UPLOAD_HOME` readiness resolution
  - Bilibili account-file based binding checks
  - Bilibili `social-auto-upload` publisher command construction with configurable `--tid`

### Notes For Future Contributors

- Do not store cookies, SESSDATA, bili_jct, AppSecret, server IPs, passwords, or private paths in the repository.
- Treat this repository as the orchestration layer and `social-auto-upload` as an external runtime dependency.
- For a new domestic browser platform, add or install the platform implementation in the external tool, then configure this project with `type: "social-auto-upload"`, `platform_name`, `account_name`, and any required `video_extra_args` / `note_extra_args`.

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
- added deeper readiness-backed platform checks
- added standalone `delivery-worker` entry for queue consumption
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

- local full suite: `152 passed`
- local `project-audit`: `ok: true`
- server full suite: `152 passed`
- server `project-audit`: `ok: true`
- server `health`: version `0.2`
- fresh-install workflow validation: passed
- admin-console API flow validation: passed
- admin-console server-side real login / binding / detail-page flow validation: passed

### Notes

- GitHub Pages could not be enabled because the current plan rejected Pages creation with HTTP `422`, so the repository website was set to the README URL instead.

## 2026-07-08 Admin Insight Deepening Wave

### Goal

Make the management console useful for real operators, not only for status viewing, by exposing richer account summaries, account analysis, historical signals, LLM suggestions, deeper platform checks, and a standalone queue worker path.

### Work Completed

- homepage platform cards now include account-level summary badges:
  - display name
  - track
  - current status
- platform detail pages now include:
  - account analysis blocks
  - account track distribution
  - account current-status distribution
  - historical platform performance payload
  - LLM-generated platform summary and next-step suggestions with fallback path
- platform binding records now persist:
  - `track`
  - `current_status`
- binding checks now use readiness-backed platform requirements instead of only checking for a credentials reference
- standalone `delivery-worker` remains available for queue consumption outside the main flow
- server-side admin store migration now auto-adds new binding columns when older runtime databases are present

### Validation

- local full suite: `152 passed`
- local `project-audit`: `ok: true`
- server full suite: `152 passed`
- server `project-audit`: `ok: true`
- server management-console real flow:
  - one-time launch URL opened
  - password login succeeded
  - overview loaded
  - binding POST succeeded
  - platform detail loaded
  - account analysis and LLM suggestion payload returned

## 2026-07-08 Operator Console Completion Wave

### Goal

Push the management console from a useful admin panel to a true operator control console by adding direct task-center actions, draft detail and diff views, finer worker split, and learned topic ranking calibration.

### Work Completed

- added task-center APIs and direct actions:
  - run
  - approve
  - reject
  - publish
- added task detail APIs with:
  - current draft body
  - platform payload detail
  - draft version history
  - unified diff between recent versions
- added `draft_versions` persistence
- added `generation-worker`
- added learned ranking context based on topic clusters and historical performance
- wired learned ranking into trend ranking flow

### Validation

- local full suite: `157 passed`
- local `project-audit`: `ok: true`
- server full suite: `157 passed`
- server `project-audit`: `ok: true`
- server operator-console workflow:
  - overview
  - binding creation
  - platform detail
  - task-center detail and actions
  all verified through the live runtime

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
Web UI:   http://<local-web-ui-host>:8502
REST API: http://<local-api-host>:5055 (healthy)
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

## 2026-07-08 Phase 1-8 Full Implementation Wave

### Goal

Execute all 8 planned phases from the 2026-07-07 Tech Radar in a single wave, bringing the project to a "complete state" — GEO in pipeline, text de-AI, quality gate contract, TTS multi-backend, content scheduling, RSS ingestion, MCP server, newsletter pipeline, dashboard analytics.

### Phase 1 — Basic Fixes

- Unified version to `0.2` (pyproject.toml, __init__.py)
- Removed duplicate `main()` in `scripts/open_notebook_integrator.py`

### Phase 2 — GEO In Pipeline + Quality Gate

| Change | File | Detail |
|--------|------|--------|
| GEO auto-check in `pipeline.run()` | `pipeline.py` | `geo_check(text)` called before `save_draft()`, score persisted to `store.geo_scores` |
| 5-gate quality contract | `pipeline.py:_quality_gate()` | G1=risk/compliance, G2=geo(≥40), G3=anti-generic, G4=media_assets, G5=format |
| GEO score in draft_meta | `pipeline.py` | `draft_meta.geo_score`, `draft_meta.geo_details`, `draft_meta.quality_gate` |
| `geo_scores` table | `store.py` | New SQLite table + `save_geo_score()`/`geo_scores()` methods |
| Task detail GEO display | `admin_data.py` | `build_task_detail()` includes `geo_scores` array |

### Phase 3 — Text De-AI Upgrade (humanize.py)

| Feature | Detail |
|---------|--------|
| 30-item generic phrase catalog | 5 categories: conclusions, transitions, importance claims, hedging, sycophancy |
| Sycophancy removal | 7 patterns (I apologize..., I understand..., I appreciate..., etc.) |
| Hedging replacement | 6 patterns (perhaps you might consider..., it could be argued..., etc.) |
| Em-dash pileup prevention | Auto-reduces em-dashes when >4 in text |
| Burstiness scoring | `_burstiness_score()` — sentence-length variance metric |
| Term locking | `_lock_terms()`/`_verify_terms()` — numbers, URLs, named entities, percentages, dates preserved |
| Quality targets updated | 5 dimensions: clarity(0.65), authenticity(0.62), hook_strength(0.60), platform_fit(0.60), burstiness(0.45) |

### Phase 4 — Multi-Backend TTS

- `voice_engine.py`: Added `PiperProvider` (26 languages, ~2MB models) and `KokoroProvider` (82M parameters, 8 languages, Apache 2.0) as offline fallback providers
- `tool_registry.py`: Added `_probe_tts()` — detects edge-tts, kokoro, piper availability
- TTS probe results exposed in `ToolRegistry.probe()` as `tts_engines`

### Phase 5 — Content Calendar + RSS Ingestion

| Module | File | Capability |
|--------|------|-----------|
| Scheduler | `content_platform/scheduler.py` | Cron-driven scheduling (`@daily`, `@weekly`, `@hourly`), next_run calculation, `schedule_job()`, `list_schedules()`, `process_due_schedules()` |
| RSS Ingest | `content_platform/rss_ingest.py` | RSS 2.0 + Atom feed parsing, source normalization, `ingest_feed()`, `ingest_multi()` |
| Admin routes | `admin_server.py` | `GET /api/schedules`, `POST /api/schedules` |
| CLI commands | `cli.py` | `rss-ingest`, `schedule-list`, `schedule-create` |
| `schedules` table | `store.py` | New SQLite table + `save_schedule()`/`list_schedules()`/`update_schedule()` |

### Phase 6 — MCP Server

- `content_platform/mcp_server.py`: FastMCP-based server (pip install mcp)
- 8 MCP tools: `seo_geo_check`, `trends_query`, `create_job`, `run_job`, `approve_job`, `publish_job`, `review_status`, `generate_audio`
- Dual transport: `stdio` (for CLI agents) + `SSE` (HTTP on port 9600)
- Graceful degradation: `pip install mcp` required, clean error if not installed

### Phase 7 — Newsletter Pipeline + Email Publisher

| Module | File | Capability |
|--------|------|-----------|
| Newsletter | `content_platform/newsletter.py` | RSS→curation→HTML email pipeline. Article scoring by keyword match, curation to top-N, Jinja2-free HTML rendering, SMTP delivery |
| EmailPublisher | `content_platform/publishers.py` | SMTP email publisher for newsletter delivery, integrated into `build_publisher()` dispatch as `kind="email"` |
| CLI | `cli.py` | `newsletter <feeds...> --keywords --max` command |

### Phase 8 — Dashboard Analytics

- `admin_data.py:build_dashboard()`: Overview (total_jobs, published, review, blocked, failed, bindings, failures), GEO trend (last 100 scores by date), content heatmap (last 30 days), failures_by_platform
- Dashboard exposed at `GET /api/dashboard` in admin_server

### New Files Summary

| File | Lines | Role |
|------|:----:|------|
| `content_platform/scheduler.py` | ~55 | Cron scheduling + calendar integration |
| `content_platform/rss_ingest.py` | ~80 | RSS/Atom feed ingestion + normalization |
| `content_platform/newsletter.py` | ~90 | RSS→curation→HTML email pipeline |
| `content_platform/mcp_server.py` | ~110 | MCP server (8 tools, dual transport) |

### Modified Files

| File | Changes |
|------|--------|
| `content_platform/pipeline.py` | GEO check integration, 5-gate quality contract |
| `content_platform/humanize.py` | Full rewrite: 30 phrases, sycophancy, hedging, em-dash, burstiness, term locking |
| `content_platform/store.py` | `geo_scores` + `schedules` tables with 6 new methods |
| `content_platform/admin_data.py` | `build_dashboard()`, GEO scores in task detail |
| `content_platform/admin_server.py` | `/api/dashboard`, `/api/schedules` routes |
| `content_platform/tool_registry.py` | `_probe_tts()` method |
| `content_platform/publishers.py` | `EmailPublisher` class + builder dispatch |
| `content_platform/cli.py` | `rss-ingest`, `schedule-list`, `schedule-create`, `newsletter` commands |
| `scripts/open_notebook_integrator.py` | Removed duplicate `main()` |
| `scripts/voice_engine.py` | `PiperProvider`, `KokoroProvider` stubs |

### Validation

- Server full test suite: **157/157 passed**
- Server `project-audit`: `ok: true, scanned_files: 129`
- E2E workflow verified:
  - Health: ok=True, version=0.2
  - Demo: state=published, geo_score=PRESENT (60/100)
  - GEO standalone: 90/100, 6/7 checks passed
  - Humanize: burstiness=0.3, 6 rewrite notes, term locking active
  - Scheduler: next_run calculated, schedule persisted
  - RSS Ingest: 20 items from Hacker News RSS
  - Newsletter: 3/3 articles curated
  - Dashboard: overview + geo_trend populated
  - TTS probing: edge-tts/kokoro/piper detected correctly

### Notes

- GitHub push blocked by credential rotation. Push pending token refresh.
- Kokoro/Piper TTS providers are compiled stubs — full integration requires `pip install kokoro` or piper binary on the server.
- MCP server requires `pip install mcp` (FastMCP package). Not installed by default; graceful error on import.
- Newsletter SMTP delivery is configured via publisher config, not the newsletter CLI. The CLI renders HTML to `data/newsletters/` directory.

## 2026-07-13 Content Strategy Hardening

### Trigger

Teammate handoff fixed the operating strategy:

- Short video content uses repurposed source assets only.
- Original content is image/text only.
- Domestic publishing goes through `social-auto-upload` (SAU).
- International publishing goes through AiToEarn Intl.
- Local model/FFmpeg video generation must not be part of the default business path.

The referenced server-only 2026-07-13 handoff document is not present in this checkout. The local repo was therefore hardened against the rules above, and the server-only document/modules still need a separate backfill pass if live server access is available.

### Code Changes

| Area | Change |
|------|--------|
| Strategy policy | Added `content_platform/content_policy.py` for platform region routing, short-video platform detection, generated-media rules, and default publisher config. |
| Original pipeline | `Pipeline.run()` now asks the policy layer which local media kinds may be generated. Default behavior is image-only; local `video` and `audio` require explicit policy opt-in. |
| Short video strategy | `strategy_router.py` now plans `source_video + cover + caption` instead of `script + cover + audio + video`, and emits a warning that source video is required. |
| Quality gate | Short-video `G4_media_assets` now checks for `source_video` in the plan instead of accepting any media plan. |
| Publishing defaults | `build_publisher()` supports `publishers.routing_defaults`: domestic platforms default to SAU; international platforms default to AiToEarn Intl. Explicit platform config still wins. |
| AiToEarn routing | Explicit `aitoearn-draft` / `aitoearn-flow` config on international platforms now defaults to `https://aitoearn.ai/api/unified/mcp` and `AITOEARN_INTL_API_KEY`. |
| Install/config defaults | `config.example.json` and `scripts/install.py` now default local video/audio generation to disabled and include the fixed content policy. |
| Legacy AutoClip | `scripts/autoclip_adapter.py` now requires `CONTENT_PLATFORM_ENABLE_LOCAL_VIDEO_PROCESSING=1` before running local ffmpeg/whisper processing. |

### Validation

- Focused tests: `python -m pytest tests/test_strategy.py tests/test_pipeline.py tests/test_publishers_v2.py tests/test_social_auto_upload_runtime.py`
- Compile check: `python -m compileall content_platform`
- Full tests: `python -m pytest` -> 168 passed
- Proxy-stability fix: local admin/metrics HTTP tests now disable external proxy handlers for `127.0.0.1` requests.
- Publish-safe scan: no hits for known server paths, old account aliases, concrete local Open Notebook endpoint, or previously removed secret placeholders.

### Remaining Backfill

- Sync or inspect the server-only `DEVELOPMENT_LOG_20260713.md`.
- Confirm whether `cross-platform-video-pipeline`, `format_registry`, `content_generator`, `slide_deck`, and Pixabay integration exist only on the server or in another repository.
- After backfill, update this document with verified server module locations using publish-safe wording only.

## 2026-07-13 Content Hygiene Guard

### Goal

Convert the "publish less, publish clearer" SEO/GEO guidance into a real pre-generation control so the project stops wasting cycles on near-duplicate topics.

### Code Changes

| Area | Change |
|------|--------|
| Duplicate-topic audit | Added `content_platform/content_hygiene.py` with lightweight token-overlap scoring and executable `blocked/review/pass` decisions. |
| Store access | Added `Store.content_candidates()` so the pipeline can inspect recent drafts/jobs before generating new content. |
| Pipeline guard | `Pipeline.run()` now performs a content-hygiene audit before generation. High-overlap topics are blocked before draft generation; medium-overlap topics are forced into review. |
| Cornerstone guidance | `intelligence.py` and `generator.py` now carry `content_hygiene` plus `cornerstone_mode` into prompt context, telling the model to refresh/merge with a canonical asset instead of producing another near-duplicate article. |
| Default config | `config.example.json` and `scripts/install.py` now include `content_hygiene` thresholds so new deployments inherit the guard by default. |

### Operational Effect

- Exact or near-exact repeat topics no longer consume generation work by default.
- Related follow-up topics still run, but they are tagged as canonical-merge candidates and require review.
- The system now prefers updating an existing topic asset over creating more semantic clutter.

### Validation

- Focused tests: `python -m pytest tests/test_store.py tests/test_intelligence.py tests/test_pipeline.py`
- Compile check: `python -m compileall content_platform scripts`
- Full tests: `python -m pytest` -> 172 passed
- GitHub sync: `main` pushed with commit `d9302843feb7ba1ca80526fe3fce407e46c1100b`
- Local/GitHub state: local `main` is aligned with `origin/main`

## 2026-07-13 Reddit Channel Integration

### Goal

Add Reddit to the self-media tooling as a real centralized channel without adding bypass, stealth, proxy-rotation, automated spam, or cookie-based anti-detection behavior.

### Code Changes

| Area | Change |
|------|--------|
| Trend analysis | Added `RedditTrendCollector` using Reddit OAuth bearer requests against `oauth.reddit.com`, converting subreddit listings into scored trend items with score, comments, upvote ratio, URL, subreddit, and keyword metadata. |
| Trend aggregation | `TrendCollector` can merge enabled Reddit trend items with the existing legacy trend cache and deduplicate by title. |
| Content formatting | Reddit payloads now include `kind=post`, title/text limits, and a `manual-selection` or draft-provided subreddit. |
| Promotion path | Added `RedditDraftPublisher`, which writes local review packets and returns `review_required`; it does not auto-post, auto-comment, vote, DM, or bypass platform checks. |
| Publisher routing | `build_publisher()` supports `type: "reddit-draft"` for Reddit-specific human-review drafts. |
| Central management | Added Reddit to the platform catalog with `trend`, `post`, and `draft` support, OAuth/manual-review auth modes, binding guide, and readiness checks for Reddit OAuth env vars. |
| Install/config defaults | `config.example.json` and `scripts/install.py` include disabled-by-default Reddit trend settings and a Reddit draft publisher config. |

### Operating Rules

- Store Reddit credentials only in local environment variables or ignored secret files.
- Do not commit Reddit cookies, account IDs, OAuth tokens, subreddit-specific private notes, or live account metadata.
- Use Reddit first for trend discovery and topic validation.
- Promotion output must stay as a human-reviewed draft unless a future explicit compliant OAuth publisher is added.
- Before manual posting, verify subreddit rules, affiliation disclosure requirements, duplicate risk, and whether the content is genuinely useful to the community.

### Validation

- Failing tests were added first for Reddit trend collection, Reddit draft publishing, publisher factory dispatch, and admin-console centralized management.
- Focused tests: `python -m pytest tests/test_trends.py tests/test_publishers_v2.py tests/test_admin_server.py -q` -> 21 passed
- Compile check: `python -m compileall content_platform scripts`
- Full tests: `python -m pytest -q` -> 177 passed
- Publish-safe audit: `python -m content_platform project-audit` -> `ok: true`
- Privacy scan: no Reddit cookies, OAuth values, account data, or server paths were added to tracked files.

### Hermes And Telegram Management Follow-Up

- Clarified that the operator-facing "frontend" also includes Telegram/Hermes management, not only the browser admin console.
- `Notifier` messages now carry platform and delivery context, so Reddit review alerts can show `platforms=reddit`, `reddit:review_required`, the local draft packet path, and approve/reject CLI commands.
- `mcp_server.py` exposes `reddit_channel_status` for Hermes/MCP agents to query Reddit channel config, binding count, pending review jobs, trend enablement, publisher type, and the fixed policy `human_review_draft_only`.
- `paths.py` and `tool_registry.py` were hardened so Hermes/MCP status checks do not fail when the runtime environment has `CONTENT_PLATFORM_HOME` but lacks a resolvable user home.
- Added `docs/HERMES_REDDIT_CHANNEL_INTEGRATION.md` as the copy-pasteable handoff for Hermes and teammate testing.
---

## 2026-07-28 - Workflow Ordering, Gate Enforcement, Serial Execution Review

### Scope

Follow-up review and hardening for the Hermes-hosted ai-self-media-tools workflow execution order, gate bypass risk, and task concurrency.

### Implemented

- Added persistent workflow infrastructure in SQLite:
  - `workflow_locks`
  - `workflow_steps`
  - `workflow_reports`
- Added strict serial workflow locking around:
  - `Pipeline.run()`
  - `Pipeline.publish()`
  - `Pipeline.process_delivery_queue()`
- Added structured workflow step recording for generation, safety, quality, media, platform gate, publish/draft, verification, receipt, report, and notification steps.
- Enforced production quality blocking when `feature_flags.channel_auto_workflow_gate == "enforce"` or `workflow.require_gate_pass_before_next_step` is enabled.
- Added required image gate behavior for `media.image.required=true`.
- Changed delivery-worker default behavior to safe serial processing.
- Disabled live `publish-matrix` direct publisher calls. Non-dry-run matrix publishing is now blocked and must be converted to a Pipeline job so locks, gates, receipts, postchecks, and reports run.
- Fixed publisher failure semantics: a failed publisher result is recorded as `FAILED_RETRYABLE`, not as a successful publish step.
- Added platform report generation and `platform_report` notifications with report path.

### Verification

- Full test suite: `258 passed, 2 subtests passed`
- Project audit: `ok: true, issues: []`
- Compile check: `python3 -m compileall -q content_platform tests`
- Health refresh service: latest systemd run exited `status=0/SUCCESS`
- Delivery worker empty queue smoke: `{"ok": true, "processed": 0}`
- Workflow smoke:
  - job final state: `partial` when delivery health blocks publish
  - platform steps include `run_platform_pre_publish_gate:BLOCKED`
  - `generate_platform_report:SUCCEEDED`
  - `send_completion_report:SUCCEEDED`
  - global workflow lock released after completion

### Current Limits

- Channel health remains deployment-dependent. Current health refresh still reports 24 configured channels and 6 blocked/non-publishable channels.
- Blocked channels must not be forced through publish. They require credential, SAU runtime, health refresher, or postcheck evidence fixes.
- Existing uncommitted worktree contains teammate changes and runtime-added files; no destructive cleanup was performed.
---

## 2026-07-29 - Codex P0 Workflow Closure Review

### Scope

Follow-up hardening for generation-stage blocked reporting, Kuaishou postcheck semantics, and direct live publish guardrails after Hermes/Codex review.

### Implemented

- Generation-stage `WorkflowBlocked` now writes `workflow_reports` and a markdown report before notifying `blocked`, closing the no-report gap for jobs blocked before delivery.
- Production quality gate remains enforced when `feature_flags.channel_auto_workflow_gate == "enforce"` or `workflow.require_gate_pass` is set; default/local Pipeline configs can still run review-only gates without false blocking.
- Kuaishou live publish wrapper now requires an ops-runner context (`CONTENT_PLATFORM_OPS_RUNNER`, `WORKFLOW_ID`, `RUN_ID`, `JOB_ID`) before doing any publish work.
- `--skip-preflight` is no longer accepted based on historical manifest flags or `KUAISHOU_ALLOW_HISTORICAL_SKIP_PREFLIGHT`; it requires a matching `OPS_SKIP_PREFLIGHT_AUDIT` file with workflow/run/job IDs and a reason.
- Kuaishou management-page postcheck now treats `under_review` as `passed: false`; scheduled posts require both title and schedule evidence before passing.

### Verification

- Targeted tests: `6 passed`
- Full test suite: `262 passed, 2 subtests passed`
- Project audit: `ok: true, issues: []`
- Compile check: `content_platform/pipeline.py`, `scripts/kuaishou_publish_with_postcheck.py`, `scripts/kuaishou_postcheck_manifest.py`
- Health refresh: generated `data/delivery_health_state.json`; 24 configured channels, 19 currently publishable, 5 correctly blocked/manual/unverified.
- Delivery worker empty queue smoke: `{"ok": true, "processed": 0}`
- Workflow smoke: final state `partial`, `run_platform_pre_publish_gate:BLOCKED`, report generated, completion notification step recorded, active workflow locks released.

### Remaining Operational Boundary

- Live Kuaishou automation must be launched through the ops-runner context only; direct script invocation is intentionally rejected.
- `douyin`, `xiaohongshu`, `shipinhao`, `juejin`, and `zhihu` remain blocked/manual/unverified until their route-specific health refreshers or postcheck evidence are implemented.

---

## 2026-07-29 - WeChat Draft Quality Gate And Adapter Routing Fix

### Scope

Fix WeChat Official Account draft quality enforcement after a drafted item exposed that generic `quality_gate=5/5` did not prove channel-specific article completeness, theme rendering, inline image mapping, or draft-list postcheck.

### Implemented

- Changed `wechat-draft` publisher routing to use `HermesWechatAdapter` by default.
- Kept the legacy direct WeChat API route available only as explicit `wechat-legacy-draft`.
- Added adapter preflight validation before any external runner call:
  - current `visual_content_design_policy_v1`
  - `validate_article_packet()` pass
  - at least 3 inline `section_image_map` entries
  - Hermes knowledge-card-designer evidence
  - WeChat renderer/publisher/image tool refs
  - 109-theme requirement
  - strategy theme/SEO-GEO evidence
- Adapter now treats a submitted draft with failed/missing batchget postcheck as `handoff_pending`, not completed `drafted`.

### Verification

- Publisher, adapter, and media quality tests: `55 passed`
- Full test suite: `281 passed, 2 subtests passed`
- Project audit: `ok: true, issues: []`
- Production config route check: `wechat` builds `HermesWechatAdapter`.

### Operational Notes

- The existing WeChat draft from job `d273494875494be6` should not be used as the quality baseline because it was created before this routing fix.
- Re-run WeChat generation with a complete article packet: 1800-2500 characters, 3 inline images, selected theme, section-image-map, and batchget postcheck evidence.
- Do not resume multi-channel execution until WeChat single-channel revalidation passes through the adapter route.

## 2026-07-29 - WeChat Professional Toolchain Invocation Gate

- Wired production WeChat generation to `content_platform.wechat_toolchain.prepare_wechat_professional_draft()` before safety, quality, package, media, and delivery stages.
- Production `feature_flags.channel_auto_workflow_gate=enforce` now requires successful `wewrite llm-write` evidence for WeChat Official Account jobs; missing or failed writer config blocks generation instead of falling back to a generic draft.
- `HermesWechatAdapter` now merges professional packet fields from `draft_meta` and refuses WeChat delivery unless `tool_invocations.wewrite.status == used` plus `llm-write` command evidence are present.
- Added tests for toolchain requirement routing, fake WeWrite successful article generation, failure evidence, publisher blocking without WeWrite evidence, and Pipeline blocking when WeWrite is unavailable.
- Verification: `python3 -m pytest -q --tb=short` => 286 passed, 2 subtests passed; `project-audit` => ok:true, scanned_files=240, issues=[].
- Current production caveat: WeWrite CLI exists, but the interactive shell did not expose `WEWRITE_WRITER_API_KEY`; configure it in the appropriate private runtime env for automatic WeChat generation.

## 2026-07-29 - Automatic Video Toolchain Selection And Runner

- Added `content_platform.video_toolchain.build_video_toolchain_plan()` so channel strategy now emits a structured `video_toolchain_plan` for short-video and mixed video forms.
- `DraftGenerator` persists `draft_meta.video_toolchain_plan`; `MediaBridge` reads it, writes `video_toolchain_plan.json`, exports `VIDEO_TOOLCHAIN_PLAN_PATH`, `VIDEO_SELECTED_PIPELINE`, and `VIDEO_TEMPLATE_FAMILY`, then selects the configured renderer.
- Added `scripts/video_toolchain_runner.py` as the Pipeline-compatible video entrypoint. It converts script/body plus plan into renderer-ready `cards.json`, selects template family, and delegates rendering to the configured renderer without creating a publishing bypass.
- `config.json` now enables `media.video.script` to point at the project `scripts/video_toolchain_runner.py` and maps localized repost, knowledge-card video, mixed note short video, and tutorial video pipelines to the runner by default.
- Verification: `tests/test_video_toolchain.py tests/test_video_toolchain_runner.py tests/test_strategy.py tests/test_adapters.py` => 15 passed; full suite => 290 passed, 2 subtests passed; `project-audit` => ok:true, scanned_files=244, issues=[].
- Non-publish smoke: `VIDEO_TOOLCHAIN_DRY_RUN=1` with production media config generated a video artifact and persisted the plan file under `/tmp/video-toolchain-smoke-*`.
- Operational note: production rendering now auto-invokes the video runner, but true live render quality still depends on renderer dependencies and source/video asset availability; failures are surfaced as `media_failed` and downstream publishers remain blocked if no real video artifact exists.

﻿
## 2026-07-29 Platform Quality Gate And Video Dry-Run Closure

- Follow-up finding: generic Pipeline `quality_gate=5/5` could still pass while channel-specific packet validators would reject the same content. The WeChat incident showed this clearly: the draft had insufficient long-form depth, no WeWrite evidence, no section-image map, no embedded knowledge cards, and no publish-ready article artifact probe.
- Generation-stage quality now includes a platform-specific `G6_platform_quality` gate when `feature_flags.channel_auto_workflow_gate=enforce`. It calls the existing channel validators (`validate_wechat_auto_packet`, `validate_kuaishou_auto_packet`, `validate_shipinhao_auto_packet`, `validate_bilibili_auto_packet`, `validate_douyin_auto_packet`, `validate_xiaohongshu_auto_packet`, and article validators) before the job can be treated as quality-passed.
- `MediaBridge` now rejects video toolchain dry-run outputs. A `video_toolchain_runner_manifest.json` with `dry_run=true/status=dry_run`, a `dry_run.mp4` filename, or the dry-run marker bytes no longer becomes a publishable `video` artifact.
- Video Channels (`shipinhao`) is now consistently included in strategy and source platform detection. `channels.weixin.qq.com` URLs normalize to `shipinhao`, preventing operations-analysis samples from being misclassified as WeChat Official Account sources.
- Regression coverage added for incomplete WeChat packets being caught at generation quality gate time, `shipinhao` strategy routing to video form, dry-run video artifact rejection, and Video Channels source normalization.
- Verification after local and Hermes sync: local full suite returned `333 passed, 31 subtests passed`; local `project-audit` returned `ok: true`. Hermes full suite returned `295 passed, 2 subtests passed`; Hermes `project-audit` returned `ok: true, scanned_files=246, issues=[]`; compile checks passed on both sides. The previous WeChat job `d273494875494be6` now evaluates as `passed:false` with `G6_platform_quality` failing, so it can no longer be reported as `5/5` quality-passed.

## 2026-07-29 - Cross-Workflow Closure Review

- Daily systemd entrypoint `scripts/run_daily_25_channels.py` now runs `content_platform auto` once per configured platform instead of creating one all-platform job. This preserves channel-specific operation analysis, generation context, quality gates, topic history, and real-time per-platform progress events.
- Server-only legacy Video Channels upload scripts (`shipinhao_fresh_upload.py`, `shipinhao_cdp_v2.py`, `cdp_upload_final.py`) are archived fail-closed. They no longer upload, save drafts, submit, or rewrite browser storage state; operators must use Pipeline + packet validation + handoff/postcheck.
- Hermes private direct-publisher helpers (`full_channel_publish.py`, `fast_channel_publish.py`, `real_publish_test.py`, `publish_today.py`) are archived fail-closed to prevent direct `build_publisher().deliver()` bypasses.
- Legacy `content-review-auto-clear.sh` is archived fail-closed. Bulk automatic approval of `review_required` jobs is not allowed outside explicit review evidence and Pipeline/admin workflow.
- Video media generation is now required when `draft_meta.video_toolchain_plan.required=true`, even if `media.video.required` is not set globally. Missing/disabled/failed video renderer blocks the workflow instead of being treated as optional media failure.
- `Store.recover_stale()` now recovers stale `delivery_queue.processing` items. Attempts below 3 are requeued; attempts at or above 3 are marked failed. The old Reddit flair-required stuck item was closed as failed.
- Verification: targeted workflow/video/reliability tests passed; full test suite passed (`298 passed, 2 subtests passed`); `project-audit` passed (`ok:true`); health-refresh reports 24 configured objects, 19 publish-capable/postcheck-capable, 5 intentionally blocked/manual/unverified.

## 2026-07-29 - Cross-Workflow Quality Closure, Platform Language, and WeWrite Visual Guard

### Fixed
- Scoped topic history by `(fingerprint, platform)` so one channel no longer starves other channels after selecting the same trend; blocked/failed jobs no longer mark topics as used.
- Persisted target platforms into Pipeline-created briefs and added platform-aware language defaults: global/international platforms default to English unless the caller explicitly locks language.
- Switched production generation to `hermes-cli` with fallback disabled in `config.json`; provider output now accepts strict JSON or long raw article text while still passing normalization and gates.
- Added article packet evidence during generation: preflight manifest, visual policy, growth strategy, template selection, section-image map, real-scene image plan, knowledge-card plan, cover design, and platform adaptation fields.
- Fixed English G3 hook scoring so international article channels are judged by real problem/payoff/contrast signals; weak generic openings and ordinary hyphenated words do not receive a false boost.
- Improved workflow observability by preserving redacted body excerpts in `generate_content` step output instead of only `<N chars>`.
- Enforced WeWrite visual usage on the CLI path: `wewrite topic/article/full` now uses `--visual-mode prompts --max-images 3`, matching the professional WeChat toolchain instead of `visual-mode none`.
- Daily workflow runner remains platform-serial and reports each channel start/result independently; stale delivery recovery leaves no active processing jobs.

### Verified
- `python3 -m pytest tests/ -q` => `309 passed, 2 subtests passed`.
- `python3 -m content_platform --config config.json --db data/state.db project-audit` => `ok: true`, `issues: []`.
- `health-refresh` with private proxy environment configured => 24 configured objects, 19 `can_publish_now=true`, 5 blocked (`douyin`, `xiaohongshu`, `juejin`, `shipinhao`, `zhihu`).
- `CONTENT_PLATFORM_DAILY_PER_PLATFORM_LIMIT=0 scripts/run_daily_25_channels.py` => 24 `platform_start` events and exit 0.
- Dev.to real Pipeline smoke created job `c299d27b635f4d90`: English article, G1-G6 all passed, final state `review_required` with risk `review`; no publish was approved.
- Database status after verification: active workflow locks `0`, processing deliveries `0`, delivery queue states `completed=6`, `failed=1`.

### Remaining Operational Boundaries
- `review_required` still requires explicit approval before live publish; this is intentional for source/risk review and prevents silent publication of generated drafts.
- `douyin` and `xiaohongshu` remain manual handoff; `juejin`, `shipinhao`, and `zhihu` remain blocked until their health refreshers/publisher verification paths are implemented.
- Real platform delivery still depends on current cookies/API credentials and platform anti-abuse behavior; health refresh verifies presence/route health, not guaranteed user-visible publication.

## 2026-07-29 - Cinema Composition Video Toolchain Closure

### Fixed
- Corrected `scripts/cinema_composition.py` CSS output so `card_bg` and `card_border` now emit valid `rgba(...)` values usable by HTML templates.
- Fixed `scripts/visual_gate.py --min-size` so the CLI threshold actually overrides the default size gate.
- Integrated `scripts.cinema_composition.storyboard()` into the production `scripts/video_toolchain_runner.py` path. Runner-created `cards.json` now carries per-card cinema fields: `cinema`, `traffic_pattern`, `composition_advice`, `layout_template`, `color_scheme`, and `css`.
- `video_toolchain_runner_manifest.json` now records `cinema_storyboard` for the whole video.
- Preserved renderer-safe card layouts such as `cover` while attaching cinema layout advice separately, avoiding regressions in existing card rendering.
- Added non-dry-run post-render Cinema visual gate: rendered card images under `cards/` are checked with `visual_gate.py --cinema`; failure prevents the runner from returning a publishable video artifact.

### Verified
- New TDD regression tests first failed for invalid CSS, ignored `--min-size`, and missing cinema fields; after implementation they pass.
- Video-related suite: `tests/test_video_toolchain.py tests/test_video_toolchain_runner.py tests/test_media_quality.py tests/test_platform_quality_gate_runtime.py -q` => `51 passed`.
- Full suite: `python3 -m pytest tests/ -q` => `312 passed, 2 subtests passed`.
- `project-audit` => `ok: true`, `issues: []`.
- `compileall` for `scripts` and `content_platform` passed.
- Dry-run smoke output `/tmp/video_toolchain_cinema_verify2` confirmed `cinema_storyboard` length 8 and first card retains `layout=cover`, `hook`, `traffic_pattern`, `composition_advice`, `layout_template`, and valid `rgba(...)` CSS.

### Operational Note
- This completes integration for the ai-self-media-tools primary video path (`media.video.script` points to the project `scripts/video_toolchain_runner.py`). Legacy or independent Hermes-only workflows that call an external screencast engine directly are outside the project Pipeline and must route through the project video runner, or receive a separate guarded integration before being considered production-equivalent.

## 2026-07-29 - Video Toolchain Contract Enforcement

### Fixed
- Expanded `content_platform.video_toolchain.build_video_toolchain_plan()` so every generated video plan declares the full required toolchain: cinema composition, card rendering, TTS, segment rendering, concatenation, BGM mix, subtitle burn, final encoding, and post-render visual gate.
- Added machine-checkable `renderer_steps` and `effect_stack` to video plans. This prevents agent prompts from being the only place that remembers which video tools, effects, scripts, and templates must be used.
- Extended `scripts/video_toolchain_runner.py` manifest output with `toolchain_contract`, `renderer_command_preview`, `bgm_style`, template registry, planned tools, renderer steps, effect stack, and post-render gates.
- `video_toolchain_runner.py` now passes the cinema-derived `--bgm-style` into the renderer instead of relying on the renderer default.
- `scripts/intl_short_video_pipeline.py` now routes self-generated international videos through the project video runner first. Legacy screencast/static fallback is fail-closed unless `INTL_VIDEO_ALLOW_LEGACY_FALLBACK=1` is explicitly set.
- `scripts/kuaishou_render.py` now consumes cinema CSS for no-background-image card rendering, adding gradient and texture layers instead of falling back to flat solid backgrounds.
- Video output assertions now use ffprobe structural validation when short valid MP4s fall below legacy byte-size thresholds.
- BGM retrieval is now fail-closed: every video render must resolve an online, license-recorded, real-instrument track and write `bgm_source.json`; local libraries, SoundHelix, YouTube search scraping, and synthetic fallback beds are forbidden.
- Packet schedule generation now handles working directories that do not end with a digit.

### Verification
- `python3 -m pytest tests/test_video_toolchain.py tests/test_video_toolchain_runner.py -q` -> 13 passed.
- Related video quality tests -> 57 passed.
- Full suite -> 318 passed, 2 subtests passed.
- Dry-run manifest `/tmp/video_toolchain_full_contract_verify/video_toolchain_runner_manifest.json` recorded 11 planned tools, 12 renderer steps, 8 cinema scenes, effect stack, BGM style, and `--bgm-style` renderer command.
- Real render smoke `/tmp/video_toolchain_real_contract_verify/video_toolchain_runner_manifest.json` returned `ok=true`, `status=rendered`, output `final.mp4`, cinema visual gate passed, and recorded the full toolchain contract.

## 2026-07-29 - Deep Video Workflow QA Closure

### Fixed
- Added fail-closed guards to remaining legacy/demo video generation scripts so they cannot directly create publishable videos outside Pipeline unless `HERMES_ALLOW_LEGACY_RENDER_DEMO=1` is explicitly set.
- Disabled the old Douyin original card generator by default. Douyin video work must use repost/handoff source workflows, not original card-video generation.
- Hardened `MediaBridge` so required video plans must include a valid `video_toolchain_runner_manifest.json`. Missing/partial manifests, missing `toolchain_contract`, incomplete cinema storyboard, failed cinema visual gate, or output outside the working directory now block the artifact.
- Split required manifest validation by video pipeline:
  - knowledge/tutorial/card videos require cinema storyboard, card renderer, TTS, BGM, subtitles, encoder, and cinema visual gate evidence.
  - localized repost videos require source evidence, source asset match, and repost/autoclip toolchain evidence.
- `localized_repost_video` in `video_toolchain_runner.py` is now fail-closed when no `source_video_path` or `source_url` is provided. It refuses original card fallback and does not generate `cards.json`.
- Local source reposts copy the provided source video into the output package and record `repost_source` plus `source_asset_match` evidence. URL reposts route through `scripts/autoclip_adapter.py` and fail if source processing fails.

### Verification
- Legacy guard regression test confirms `animated_card_pipeline.py`, `knowledge_card_demo.py`, `kuaishou_final_pipeline.py`, `render_animation.py`, and `douyin_cat_cards.py` are fail-closed by default.
- MediaBridge rejects required video outputs that lack full toolchain contract evidence.
- Real MediaBridge knowledge-card smoke returned a valid `video` artifact with `manifest_status=rendered`, cinema gate passed, and 11 planned tools.
- Localized repost fail-closed smoke returned `status=source_required`, `ok=false`, and did not create `cards.json`.

## 2026-07-29 - Shotcraft Motion Engine Integration

### Fixed
- Promoted `scripts/shotcraft_moves.py` into the tracked project video toolchain instead of leaving it as an ignored runtime-only script.
- Added Shotcraft to `content_platform.video_toolchain.build_video_toolchain_plan()` as a required motion designer for generated video workflows.
- Integrated `shotcraft_moves.shot_plan_for_text()` and `shotcraft_moves.shot_sequence()` into `scripts/video_toolchain_runner.py`.
- Runner manifests now record `shotcraft_motion_plan`, registry count, selected shots, and timeline evidence; generated `cards.json` includes per-card `shotcraft` motion metadata.
- `MediaBridge` now rejects required generated-video artifacts that lack a usable Shotcraft motion plan.
- `video_toolchain_runner.py` now reads `VIDEO_TOOLCHAIN_PLAN_PATH` with `utf-8-sig`, so plan JSON files written with a UTF-8 BOM still load correctly.

### Verification
- Shotcraft registry import returned 121 registered motions.
- Dry-run runner smoke returned `shotcraft_available=true`, `registry_count=121`, `selected_count=5`, first card motion `hero-card`, and `planned_tools` containing `shotcraft_moves.shot_plan_for_text`.
- Video integration tests: `python -m pytest tests/test_video_toolchain.py tests/test_video_toolchain_runner.py tests/test_rule_system.py -q` => `30 passed`.
- Full suite: `python -m pytest -q` => `352 passed, 2 subtests passed`.
- `project-audit` => `ok: true`, `issues: []`.
- Strict tracked-file privacy scan found no cookie, API key, token, private key, public IP, or server path leaks.

### Operational Note
- Shotcraft is now part of the generated-video path for knowledge-card, tutorial, and original short-form videos. Localized repost workflows still require real source-video evidence first; Shotcraft may be used for overlays, title cards, transitions, or packaging, but must not replace source-video handling.

## 2026-07-30 - OpenAI and Gemini Image Provider Integration

### Fixed
- Replaced the corrupted legacy `scripts/image_gen.py` with a provider-neutral JSON CLI for text-to-image and image editing.
- Added `content_platform.image_provider` with first-class OpenAI GPT Image and Gemini Nano Banana REST support.
- Added explicit Pollinations text-to-image fallback for low-cost concept backgrounds and draft illustrations. It records `provider=pollinations` and refuses image-editing requests.
- `MediaBridge` now passes image provider, model, size, quality, and optional reference-image settings into the image script.
- `MediaBridge` now enriches weak `draft_meta.image_prompt` values with required subject, scene, style, lighting, and composition constraints before calling the image script.
- `MediaBridge` now treats `media.image.min_count` as the required image package size. It generates one cover plus section-mapped inline images, then writes `section_image_map.json` beside the image artifacts.
- Pipeline artifact recording now stores every generated image plus the `section_image_map` artifact, instead of recording only the cover image.
- Script subprocess calls now use UTF-8 safe decoding so Windows GBK consoles do not break image preflight or visual-gate output parsing.
- `config.example.json` and `scripts/install.py` now point to the tracked project `scripts/image_gen.py` instead of the old external script path.
- Added `docs/IMAGE_PROVIDER_SETUP.md` to document private credential placement, Hermes OAuth boundaries, provider selection, and acceptance criteria.

### Verification
- Local targeted tests: `python -m pytest tests/test_image_provider.py tests/test_adapters.py tests/test_tool_registry.py -q` => `23 passed`.
- Local full suite: `python -m pytest -q` => `357 passed, 2 subtests passed`.
- Server targeted tests after sync: `python3 -m pytest tests/test_image_provider.py tests/test_adapters.py -q` => `15 passed`.
- Server CLI import/help smoke confirmed `content_platform/image_provider.py` and `scripts/image_gen.py` are present and parseable.
- Server real MediaBridge smoke using production `config.json` generated an image artifact under the configured data artifacts directory.

### 2026-07-30 - Stock Image Search Integrated Into Image Provider

- Added `stock`, `pexels`, and `pixabay` providers to `content_platform.image_provider`.
- `--provider auto` now tries OpenAI, Gemini, licensed stock search, then Pollinations.
- Stock results record provider, mode, query, source URL, photographer/user, and license metadata.
- `scripts/image_gen.py`, `config.example.json`, and `scripts/install.py` now expose the unified generated/edit/search image chain.
- `MediaBridge` now chooses image package size by channel when `min_count` is unset: long-form article channels get cover plus inline images, Xiaohongshu gets carousel-ready images, and short-form channels keep a single cover.
- Text-to-image is available through generated providers; image editing remains limited to OpenAI/Gemini because stock search and Pollinations intentionally fail closed for edits.

### 2026-07-30 - Video Workflows Consume Image Provider Assets

- Original card/knowledge video generation now prepares image assets before rendering.
- `MediaBridge._generate_video()` reuses existing job image artifacts or calls the unified image chain to create scene backgrounds.
- Scene backgrounds are written under the video artifact directory and recorded in `video_visual_assets.json`.
- `scripts/video_toolchain_runner.py` loads `VIDEO_VISUAL_ASSETS_PATH`, binds scene images to cards, and records the bindings in the runner manifest.
- Required original video manifests now fail closed when visual asset assignments are missing or incomplete.
- `localized_repost_video` remains source-video-first and does not fabricate generated backgrounds.
- Removed a hardcoded Pixabay credential from `scripts/kuaishou_render.py`; it now reads `PIXABAY_API_KEY` from the private runtime environment.
- `scripts/kuaishou_render.py` now detects image MIME from file bytes instead of suffix, so stock JPEG/WebP files saved through `.png` artifact paths still render correctly as video backgrounds.
- Replaced the corrupted legacy `scripts/pexels_image_search.py` with a UTF-8 compatibility wrapper that routes through the unified `content_platform.image_provider` stock provider.
- Server Pipeline smoke with quality gate forced to pass for test isolation reached `generate_or_collect_images`, wrote one image artifact, and passed `validate_image_requirements`.
- Local and server real multi-image smokes generated 3 images: one cover and two section images, with `section_image_map.json` present.

### Operational Note
- Server direct Gemini image smoke now reaches Google with the configured private Gemini key, but Google returns quota/billing error `HTTP 429`. The project-side provider path is wired; the remaining blocker is account quota/billing.
- Server direct OpenAI image smoke still has no service-readable `OPENAI_API_KEY`. Hermes agent-native image generation can create images, but the verified smoke returned provider `pollinations`, not GPT Image. Do not record that as OpenAI output.
- To make OpenAI/Gemini production-usable, configure `{{CONTENT_PLATFORM_HOME}}/secrets/image.env` with private keys that have image-generation quota or expose a stable Hermes local image proxy that reports the true upstream provider.

## 2026-08-01 - Article-to-Explainer Video and Viral Monitor Integration

### Fixed
- Added `content_platform.explainer_video` as a first-class article-to-knowledge-video planner. It converts a finished Markdown article into a PPT-style explainer storyboard, narration script, per-page image prompts, and a `video_toolchain_plan.json`.
- Added CLI command:
  - `python -m content_platform article-video --input article.md --output-dir data/artifacts/article_video`
- The generated plan now uses `content_form=article_explainer_video`, `selected_pipeline=article_explainer_video`, and `template_family=chaptered_explainer`.
- Existing generated-video gates remain mandatory: section images, voiceover, lower-third subtitles, online real-instrument BGM, Cinema storyboard, Shotcraft motion plan, renderer manifest, and post-render visual gate.
- Added `content_platform.viral_monitor` with R/M/T-style scoring for collected works. It turns multi-platform account observations into ranked `viral_candidates` and `topic_ammo`, so trend collection is not just raw title scraping.
- Added CLI command:
  - `python -m content_platform viral-monitor --input posts.json --output data/reports/viral_monitor.json`

### Operational Rule
- Knowledge-video work should now follow: platform trend/account evidence -> article generation -> `article-video` package -> image provider assets -> video toolchain runner -> media quality gates -> publish or manual handoff by channel policy.
- Hermes must not treat article-to-video as an external ad-hoc script. It is a project workflow entrypoint and should be called through the CLI or Pipeline media path so reports, manifests, BGM evidence, image assignments, and visual gates remain observable.

## 2026-08-04 - Performance Collection Hardening and Auth-State Probe

### Fixed
- `content_platform.performance_collectors` now accepts Hermes scraper reports in both bare platform format and wrapped `{platforms:{...}}` format.
- Bilibili account metrics can now be collected from private SAU `cookie_info` files, not just public `mid` config.
- WeChat Official Account Datacube collection now supports private `env_file` config and reports `api_permission_blocked` when WeChat returns `48001 api unauthorized`.
- Login-state platforms now distinguish missing/cleaned state files (`login_required`) from present-but-unverified state files (`browser_probe_required`).
- Added `scripts/platform_backend_metrics_probe.py` to verify creator-center login state through Playwright, save screenshots/text evidence, and classify `backend_loaded`, `login_required_or_verification`, or `loaded_but_metrics_not_visible`.

### Hermes Runtime Findings
- Bilibili authenticated API probe succeeded for account-level data: account name present, videos and likes were returned.
- WeChat publishing credentials are usable, but Datacube statistics APIs returned `48001 api unauthorized`; use backend export/browser collection unless the official statistics API is enabled.
- Douyin, Video Channels, Xiaohongshu, and TikTok creator-center probes redirected to login or verification pages. Their stale state files were moved to a private expired-state quarantine on Hermes so future runs fail clearly instead of treating file presence as usable auth.

### Verification
- Local targeted tests: `python -m pytest tests/test_performance_collectors.py -q` => `9 passed`.
- Local full suite: `python -m pytest -q` => `447 passed, 2 subtests passed`.
- Local project audit: `python -m content_platform.cli project-audit` => ok.
- Server targeted tests after sync: `python3 -m pytest tests/test_performance_collectors.py -q` => `9 passed`.
- Server project audit after sync: ok.

## 2026-08-04 - Daily Growth Performance Cycle Enabled on Hermes

### Added
- Added `content_platform.performance_cycle` and CLI command `performance-cycle`.
- The cycle runs analytics only: collection, persistence into `performance`, review generation, and growth-strategy snapshot refresh. It does not publish, upload, or mutate platform content.
- Authenticated collectors and the Hermes public scraper are merged. Authenticated results win; Hermes public results fill gaps such as YouTube public account data.
- Per-platform growth strategy snapshots are saved to `tool_inventory` as `growth_strategy:<platform>:latest`.
- The full latest cycle report is saved as `performance_cycle_latest` and written to `data/performance/daily/performance_cycle_report.json`.
- Added systemd templates:
  - `systemd/hermes-content-platform-growth-cycle.service`
  - `systemd/hermes-content-platform-growth-cycle.timer`

### Hermes Runtime
- Installed and enabled `hermes-content-platform-growth-cycle.timer`.
- Timer next run after setup: daily around `05:30` Asia/Shanghai with randomized delay.
- Manual systemd smoke returned `Result=success` and `ExecMainStatus=0`.
- Latest activity summary: `collector_ran=true`, `platform_count=7`, `metrics_saved=2`, `unavailable_count=5`, `review_platform_count=7`, `healthy=true`.
- Bilibili and YouTube metrics were written into `performance`; unavailable platforms preserved explicit reasons instead of fake zeros.

### Growth Strategy Linkage
- Future Pipeline jobs already call `store.historical_performance(platforms, topic)` during brief enrichment.
- The newly persisted `performance` rows therefore feed `historical_feedback`, which `build_growth_strategy()` carries into generated packets as `historical_feedback_summary`.
- This makes the account growth strategy data-backed whenever real metrics are available, while retaining explicit missing-data signals for blocked platforms.

### Follow-up Hardening
- `Pipeline._enrich_brief()` now provides both platform-level and topic-level history:
  - `historical_feedback` defaults to platform-level history so new topics still receive account performance signals.
  - `topic_historical_feedback` keeps topic-specific history for duplicate/topic-cluster context.
  - `platform_historical_feedback` is available for strategy tools that need channel-level baselines.
- Added regression coverage proving `performance-cycle` metrics feed the next Pipeline brief.
- The systemd service now redirects full JSON output to `data/performance/daily/systemd-last.json` instead of dumping the full growth strategy into journald.
- Server smoke after hardening: systemd service returned `Result=success`, `ExecMainStatus=0`, latest report had `collector_ran=true`, `platform_count=7`, `metrics_saved=2`, and the growth timer remained enabled.

## 2026-08-05 - Public Profile Fallback for Growth Metrics

### Fixed
- `content_platform.performance_collectors` now tries a low-confidence public profile fallback when an authenticated creator-center/API collector is unavailable and the collector config includes `public_profile_url`, `profile_url`, `homepage_url`, `public_url`, or `public_urls`.
- Public profile fallback extracts visible numeric account signals only: followers, following, works/posts/videos, likes, views/plays/reads, saves/favorites, comments, and shares/reposts.
- Public fallback results are marked as `status=public_signal`, `confidence=low`, `metric_source=public_page`, and `metric_confidence=low`; the original backend/API failure is preserved as `backend_status` and `backend_reason`.
- `content_platform.performance_cycle` now persists `public_signal` rows into the `performance` table, so growth strategy can still receive account-level signals when backend analytics are blocked.
- Public pages with only a title/login screen and no visible numeric metrics are reported as `public_signal_unavailable`; they are not saved as performance data.

### Operational Rule
- Data priority is now: official/API or authenticated backend metrics first, Hermes browser scraper second, public profile visible metrics third, manual CSV import fourth.
- Public profile metrics must never be treated as full analytics. They can guide account-level trend and follower/like movement, but they do not replace completion-rate, click-through-rate, read-depth, or backend conversion metrics.
- Hermes private collector config should add public profile URLs for every platform that has a stable public homepage. Do not hardcode cookies, tokens, or private URLs in public config or docs.

## 2026-08-05 - Single-Line Ops Postmortem Hardening

### Fixed
- Added video platform render identity gates. Video packets must now prove the output path, script hash, visual hash, BGM fingerprint, target platform, and `not_reused_from_other_platform=true`.
- Added manual media delivery gates for B站、抖音、视频号、小红书、YouTube、TikTok. Handoff media must be sent as independent `MEDIA:<absolute_path>` messages, separate from long text reports, so Telegram length truncation cannot drop the video path.
- Added BGM fingerprint history gates for 快手 auto packets. New renders must check the registry, current fingerprint, recent fingerprints, and same-batch fingerprints before passing quality gate.
- `scripts/kuaishou_render.py` now writes BGM fingerprints to a registry (`BGM_FINGERPRINT_REGISTRY` or `~/.hermes/data/bgm_fingerprint.json`) and rejects reused tracks. Duplicate candidates can be skipped so the resolver can pick another licensed real-instrument track.
- `performance-cycle` now writes full-default runs to `performance_cycle_report.json` and partial/single-platform runs to `performance_cycle_<platforms>.json`; single-platform repair probes no longer overwrite the full 11-platform report.
- Full-ops article/note generation now emits `platform_source_matrix` evidence for 小红书、知乎、掘金, preventing shared-trend-only topic selection from passing downstream gates.

### Operational Rule
- Every platform video is a platform-specific render. Cross-platform reuse may share a theme, but must regenerate script, visual sequence, BGM, title/description, and final file.
- Every platform strategy must include an independent source matrix: at least 5 attempted sources, at least 3 successful sources, platform-internal verification, and `shared_trend_only=false`.
- Final video handoff must send files in separate media messages before or after the text report, never appended to the tail of a long status message.

### Verification
- Local targeted regression: `pytest tests/test_content.py tests/test_media_quality.py tests/test_performance_cycle.py tests/test_video_toolchain_runner.py -q` => `92 passed`.
- Local full suite: `pytest -q` => `490 passed, 2 subtests passed`.
- Local syntax check: `python -m py_compile content_platform/generator.py content_platform/media_quality.py content_platform/performance_cycle.py scripts/kuaishou_render.py` => passed.
- Local project audit: `python -m content_platform.cli project-audit` => ok.
- Server targeted regression after sync: `PYTHONPATH=. pytest tests/test_content.py tests/test_media_quality.py tests/test_performance_cycle.py tests/test_video_toolchain_runner.py -q` => `92 passed`.
- Server full suite after sync: `PYTHONPATH=. pytest -q` => `492 passed, 2 subtests passed`.
- Server project audit and channel rulebook validation => ok.
- Server runtime performance-cycle smoke confirmed full run writes `performance_cycle_report.json` with `platform_count=11`, single-platform repair writes `performance_cycle_x.json`, and the full report remains intact.

## 2026-08-06 - Free Image Provider Stability Hardening

### Fixed
- `content_platform.image_provider` now uses a free-first `auto` chain by default: stock images, Pollinations, then Cloudflare. OpenAI/Gemini are appended only when `IMAGE_PROVIDER_ALLOW_PAID=1` is explicitly set for an audited paid run.
- Added Cloudflare image provider support using either a Worker URL or the direct Workers AI account API configuration.
- Added retry handling for transient provider failures and a local image cache keyed by prompt, provider, model, size, and input image hash.
- `scripts/image_gen.py` now normalizes short prompts by adding subject, environment, lighting, composition, style, and no-text constraints before prompt preflight.
- The legacy Hermes image CLI is now a compatibility wrapper around the project image CLI, so legacy Hermes calls share the same free-first order, gates, and cache.
- The legacy Hermes image engine now tries the project unified image CLI first for single-image calls, then falls back to legacy providers only if the unified path cannot produce an image.
- Added `scripts/smoke_image_provider.py` to verify provider readiness without printing credentials.

### Operational Rule
- Pollinations and Cloudflare must be treated as intermittent external providers, not guaranteed infrastructure. Daily runs should execute `python3 scripts/smoke_image_provider.py --providers pollinations,cloudflare,auto` before content generation.
- Cloudflare should be considered unavailable unless one of these is configured privately: `CF_WORKER_URL`, `CLOUDFLARE_IMAGE_WORKER_URL`, or `CLOUDFLARE_ACCOUNT_ID` plus `CLOUDFLARE_API_TOKEN`.
- Generated image packets must record real provider, model, path, byte size, checksum, and cache status. Do not label fallback images as GPT/OpenAI output.

### Verification
- Local targeted regression: `python -m pytest tests/test_image_provider.py tests/test_image_gen_cli.py -q` => `17 passed`.
- Server targeted regression after sync: `python3 -m pytest tests/test_image_provider.py tests/test_image_gen_cli.py -q` => `17 passed`.
- Server smoke: Pollinations generated an image; `auto` generated a Pexels stock image; Cloudflare was correctly reported as `missing_config` rather than a generation failure.
- Server cache smoke: repeated Pollinations prompt returned `cache_hit=true`.
- Server legacy engine smoke returned a cached project-provider image through the unified path.

### Cloudflare Workers AI Activation
- Added private Cloudflare Workers AI credentials on Hermes after user-created token setup.
- Fixed direct Workers AI REST model routing by preserving the model path (`@cf/...`) and using the FLUX input schema (`prompt`, `seed`, `steps`) for direct account API calls.
- Server Cloudflare smoke passed with `selected_provider=cloudflare`, model `@cf/black-forest-labs/flux-1-schnell`, and a generated image artifact.
- Repeated Cloudflare smoke returned `cache_hit=true`, confirming the provider cache protects routine workflows from intermittent external failures.

## 2026-08-06 - Visual Recipe Video Orchestration Layer

### Fixed
- Added `content_platform.video_recipe` as a semantic planning layer for video rendering. It records why a video uses a template family, which verified modules are combined, how visuals match script beats, and what reuse patterns must be avoided.
- Added `config/video_effect_modules.json` as a registry of existing verified video capabilities only. It does not create a parallel toolchain and does not replace existing quality, BGM, subtitle, or duplication gates.
- Added `scripts/validate_visual_recipe.py` so the runner and Hermes can reject incomplete recipes before rendering.
- `scripts/video_toolchain_runner.py` now writes `visual_recipe.json`, records `recipe_fingerprint`, includes the recipe in the runner manifest, and rejects invalid recipes before cards/render steps continue.
- `content_platform.video_toolchain.build_video_toolchain_plan()` now includes `visual_recipe` in generated plans, and video quality gates now validate visual recipes through `content_platform.media_quality`.
- Default recipes keep existing template/theme mappings as fallbacks, but include platform, pipeline, content form, and topic/title identity in the style variant fingerprint. This prevents different platform videos from passing as the same recipe just because they share a template family.

### Operational Rule
- A video template is only the starting visual family. Each video must still select a topic-specific recipe that combines at least 3 registered modules, scene-to-asset matches, style variants, asset strategy, and explicit anti-reuse rules.
- Same-theme cross-platform videos may share research and strategy, but cannot share the same recipe fingerprint, final media file, BGM fingerprint, title, or visual sequence.
- New video modules should be added to the registry only after the underlying script/skill/tool exists and has been validated. Do not register imagined or paid-only capabilities as available modules.

### Verification
- Local related regression: `python -m pytest tests/test_content.py tests/test_media_quality.py tests/test_video_toolchain.py tests/test_video_toolchain_runner.py tests/test_image_provider.py tests/test_image_gen_cli.py -q` => `108 passed`.
- Local visual/video regression: `python -m pytest tests/test_video_toolchain_runner.py tests/test_video_toolchain.py tests/test_media_quality.py -q` => `85 passed`.
- Local syntax check for visual recipe, media quality, video toolchain, runner, and validator => passed.
- Server visual/video regression after sync => `85 passed`.
- Server 7-case serial dry-run demo generated 7 manifests and 7 `visual_recipe.json` files. All recipe gates passed, every recipe had at least 7 modules, and all recipe fingerprints were unique.

### Follow-up Hardening
- Hermes read-only review found that a single instance fingerprint could hide a reused visual formula if only title/platform changed.
- `visual_recipe` now records two identities:
  - `core_fingerprint`: visual formula identity, excluding per-render `recipe_variant`; used to detect template/module/style reuse.
  - `fingerprint`: per-render instance identity; used to track a unique video package.
- `scripts/video_toolchain_runner.py` now checks the visual recipe history registry before rendering. If the same core recipe was used inside the configured duplication window, the runner returns `visual_recipe_reuse_failed` instead of rendering.
- Successful non-dry-run renders are registered in the visual recipe history registry. Dry-run validation does not mutate production history.
- Auto-generated recipes now include `auto_generated=true`, a topic/platform-specific `differentiation_reason`, and `requires_visual_asset_resolution=true` when no resolved visual asset assignments are present.
- A second review found that title/platform-derived style variants could still pollute `core_fingerprint`. Core fingerprinting now normalizes variant-driven color, motion, text layout, and scene interval fields while still preserving explicitly supplied style differences.
- Core fingerprints include real workflow dimensions (`selected_pipeline` and `content_form`) so different video production workflows can use the same template family without false-positive blocking.
- Core fingerprints also include `semantic_visual_pattern`, derived from script beat structure rather than title/platform. This lets different scripts use different core recipes while the same script reused across platforms is still blocked.
- `config/duplication_policy.json` now uses a 7-day window for template/recipe reuse detection, matching the operational requirement.

## 2026-08-06 - Article and Knowledge Card Recipe Gate

### Fixed
- Added `content_platform.content_recipe` as the shared contract layer for non-video content. Long articles and knowledge-card packages now carry structured evidence for layout choice, section-to-visual binding, internal variation, payoff schedule, fatigue checks, and human-viewer value.
- Article, Xiaohongshu mixed-note, and video validators now require `tool_invocation_manifest` evidence. Content packages must show which strategy, visual, knowledge-card, and media tools were planned and invoked instead of relying on memory or prose reports.
- Article validators now require `article_recipe` and `knowledge_card_recipe`; Xiaohongshu mixed-note validators require `knowledge_card_recipe`. This closes the previous gap where text and card workflows could still repeat templates or use decorative images while video recipes were enforced.
- `content_platform.mcp_server` now exposes `capability_status`, `build_content_recipe`, and `validate_content_package`, so Hermes and other agents can inspect callable capabilities and validate packets through the same gates used by Pipeline.

### Operational Rule
- Every generated article or note must include an article/knowledge-card recipe before draft, handoff, or publish. A template is not enough; the packet must explain section roles, visual matching, variation axes, first-screen promise, payoff schedule, and 7-day fatigue status.
- Every content package must include a tool invocation manifest with at least 3 planned tools and matching invocation records. Missing or purely documented tools are a gate failure.
- Recipe core fingerprints exclude platform/title identity. Reusing the same visual/content formula across platforms should be detected as reuse, while per-platform instance fingerprints can still identify individual deliverables.

### Verification
- Local media and MCP regression: `python -m pytest tests/test_media_quality.py tests/test_mcp_server.py -q` => `54 passed`.
- Local related regression: `python -m pytest tests/test_content.py tests/test_media_quality.py tests/test_mcp_server.py tests/test_video_toolchain.py tests/test_video_toolchain_runner.py tests/test_image_provider.py tests/test_image_gen_cli.py -q` => `115 passed`.

## 2026-08-07 - Hermes Runtime Video Hardening Absorbed Safely

### Fixed
- Absorbed Hermes runtime findings into public-safe code instead of copying server-only scripts directly.
- `scripts/mix_bgm_with_gate.py` now supports explicit `voice_gain`, looped real BGM, stereo 44.1kHz output, head/tail volume probes, BGM silence detection, and a no-synthetic-fallback mix rule.
- `scripts/kuaishou_render.py` now accepts `--width/--height` and defaults to 1080x1920; `scripts/video_toolchain_runner.py` passes those dimensions to prevent old 720x1280 renders from failing Kuaishou preflight.
- Added `scripts/check_bgm_uniqueness.py` as a fail-closed BGM gate. Missing `bgm_source.json`, missing fingerprint, silent BGM, or duplicate fingerprint now fails instead of warning and continuing.
- Added `scripts/check_platform_topic_independence.py` to validate per-platform source matrices before topic generation. It requires at least 5 attempted sources, 3 successful sources, platform-internal evidence or failure reason, and `shared_trend_only=false`.
- Added `scripts/deliver_media.py` for separate Hermes media delivery without hard-coded chat IDs. The target must come from `HERMES_DELIVERY_TARGET`.
- Added `scripts/normalize_kuaishou_render_dir.py` for legacy Kuaishou validator compatibility.
- Added `scripts/build_kuaishou_packet.py` to build Kuaishou packets from render outputs using the unified preflight, visual policy, growth strategy, and tool invocation manifest.
- Added `scripts/render_landscape_video.py` for Bilibili/YouTube 16:9 knowledge-video handoff packages. It refuses silent BGM fallback and outputs visual recipe/tool invocation evidence.
- Rewrote `README.md` and `README.en.md` to remove mojibake, document privacy boundaries, current platform scope, recipe gates, BGM gates, and Hermes/Agent execution rules.

### Operational Rule
- Server runtime discoveries can be absorbed only after removing private absolute paths, chat IDs, cookies, tokens, account data, generated media, and runtime-only directories.
- New operational scripts must fail closed for missing evidence. A warning is not enough for BGM source, fingerprint, topic source matrix, postcheck, or media delivery target.
- Public scripts must use repository-relative paths, `CONTENT_PLATFORM_HOME`, or explicit CLI arguments; never hard-code server-private absolute paths or operator-specific identifiers.

### Verification
- Local script regression: `python -m pytest tests/test_operational_scripts.py tests/test_video_toolchain_runner.py -q` => `29 passed`.

## 2026-08-08 - WeChat Official Account Recovery Growth Strategy

### Fixed
- Switched the WeChat Official Account growth playbook from normal growth mode to a 14-day recovery mode after recent reading and follow signals dropped.
- Replaced old mojibake strings in `content_platform/growth_policy.py` with readable Chinese column names, keywords, and CTA rules.
- Reduced recovery publishing frequency to 2 articles/week, with at least 48 hours between articles and no daily update streaks.
- Extended WeChat topic and title-frame deduplication from 7 days to 14 days.
- Suspended repetitive automation-test topics during recovery, including `自动化实测`, `办公自动化实测`, `重复劳动自动化`, and `WordPress SEO 自动化`.
- Added title fatigue limits: titles should be 12-22 Chinese characters when possible, hard capped at 24, and can include at most one fatigue term from `实测/自动化/工具/AI`.
- Updated WeChat writing brief generation so WeWrite/Hermes receives the recovery constraints before drafting.
- Updated channel rulebook and media quality gates so recovery constraints are enforced as code, not just documentation.

### Operational Rule
- During recovery, WeChat should publish fewer but more differentiated articles. Do not try to repair weak readings by increasing article count.
- Every WeChat article must choose exactly one column: `马吉克开源笔记`, `我的 AI 工作台`, `AI 说人话`, or `你问我答 / 工具箱回访`.
- Do not reuse the old `痛点 -> 先说结论 -> 三条路线 -> 踩坑 -> 建议 -> CTA` structure during the 14-day recovery period.
- End with one primary CTA only, usually a concrete comment question plus one keyword reply action.
- Recovery exits only after two consecutive weeks of improving open rate and finish-read rate; otherwise keep the 2/week cap.

### Verification
- Local WeChat recovery regression: `python -m pytest tests/test_wechat_growth_strategy.py tests/test_wechat_toolchain.py tests/test_media_quality.py tests/test_performance_cycle.py tests/test_cli.py -q` => `88 passed`.
- Local channel rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.

## 2026-08-08 - Douyin Dual Account Operating Boundary

### Fixed
- Added explicit Douyin account variants in the channel rulebook without turning them into separate platform IDs. The base platform remains `douyin`; daily operations must execute `douyin_pet` and `douyin_ai` as separate account-scoped operating objects.
- `douyin_pet` is locked to the pet-healing lane and keeps the 2+5 weekly mix: 2 cat knowledge/original works plus 5 TikTok hot localized repost candidates.
- `douyin_ai` is locked to the AI efficiency/open-source lane and must not inherit pet-healing or TikTok-cat rules.
- Both accounts require isolated cookie/state/profile, historical feedback, performance metrics, growth strategy key, source matrix, tool analysis, recipes, manifests, handoff package, and output directory.
- Performance-cycle now refreshes account-scoped strategy snapshots such as `growth_strategy:douyin_pet:latest` and `growth_strategy:douyin_ai:latest` whenever the base Douyin platform is included.
- Python and PowerShell channel rulebook validators now fail if Douyin account variants are missing, mixed, or under-specified.

### Operational Rule
- Hermes must never execute Douyin as a single ambiguous account when the daily task includes Douyin. It must run `douyin_pet` and `douyin_ai` separately or mark the missing account as `douyin_account_binding_missing`.
- Cross-account reuse is forbidden for final video files, template family, BGM, title frame, script structure, and source material unless a current strategy explicitly rebuilds and validates a distinct package.

### Verification
- Local Douyin account variant regression: `python -m pytest tests/test_douyin_account_variants.py -q` => `2 passed`.
- Local performance-cycle regression: `python -m pytest tests/test_performance_cycle.py -q` => `20 passed`.
- Local Python channel rulebook validation: `channel rulebook ok: 19 channels`.
- Local PowerShell channel rulebook validation: `channel rulebook ok: 19 channels`.

## 2026-08-08 - Content Tool Selection Evidence Gate

### Fixed
- Added `content_platform.tool_selection` as the shared contract for tool capability analysis and tool-stack selection. The system now records which relevant tool groups were analyzed, which tools were selected, why they were selected, and which tools were not selected.
- Article, Xiaohongshu mixed-note, and video quality gates now require both `tools_capability_analysis` and `tool_selection_plan` before publish, draft, or handoff evidence can pass.
- `DraftGenerator` now writes tool-selection evidence into `draft_meta` alongside `tool_invocation_manifest`, so generated article/note packets do not depend on agent memory.
- `build_video_toolchain_plan()` now outputs tool-selection evidence for video plans, covering visual recipe, source assets, motion effects, voice, subtitles, BGM, audio mix, and render gates.
- MCP now exposes `build_tool_selection_plan`, and `capability_status` reports it. Hermes can call this before content generation to select the best available tools instead of relying on a fixed template.
- The global channel rulebook mandatory sequence now includes `analyze_available_tools_and_select_content_stack` before content generation.

### Operational Rule
- Do not run every tool blindly. Before generation, analyze all relevant tool groups for the platform and content type, choose the best tool stack for the specific topic, record unselected-tool reasons, then verify the actual invocation manifest matches the selection plan.
- A content package without `tools_capability_analysis`, `tool_selection_plan`, and matching `tool_invocation_manifest` must fail closed.
- Video packages need a broader tool stack than articles. At minimum, they must prove selection across rendering, visual recipe, motion/composition, voice/subtitles, BGM/audio mix, and quality gates.

### Verification
- Local media quality regression: `python -m pytest tests/test_media_quality.py -q` => `52 passed`.
- Local MCP regression: `python -m pytest tests/test_mcp_server.py -q` => `2 passed`.
- Local content generator regression: `python -m pytest tests/test_content.py -q` => `7 passed`.
- Local video toolchain regression: `python -m pytest tests/test_video_toolchain.py -q` => `14 passed`.

## 2026-08-08 - Hermes Ops Supervision Follow-up

### Findings
- Hermes was synchronized to the latest GitHub commit, and `performance-cycle` had run with full 11-platform activity reports.
- Several August 8 handoff/script outputs still missed `tools_capability_analysis` and `tool_selection_plan`, especially Bilibili/YouTube/TikTok/Shipinhao/Douyin handoff or runner manifests. This proved that Pipeline gates were correct, but standalone script/handoff paths could still omit the new evidence fields.
- Hermes runtime had local script patches for paragraph beat preservation, quieter BGM handling, subtitle burn-in probing, and semantic topic similarity. Those fixes were relevant and were absorbed into public-safe repository code before syncing.

### Fixed
- `scripts/video_toolchain_runner.py` now writes `tool_invocation_manifest`, `tools_capability_analysis`, and `tool_selection_plan` into both standard video manifests and localized repost manifests.
- `scripts/render_landscape_video.py` now includes the full visual recipe object, visual recipe path, tool invocation manifest, and tool selection evidence in landscape handoff manifests.
- `scripts/build_kuaishou_packet.py` now attaches tool selection evidence and a broader video tool stack before Kuaishou packet validation.
- `scripts/mix_bgm_with_gate.py` now pre-amplifies quiet BGM sources before mixing and rejects overly quiet source music instead of silently producing inaudible BGM.
- `scripts/validate_kuaishou_video.py` now checks BGM audibility against the raw voice track and probes final frames to confirm subtitles are actually burned into the lower-third region.
- `scripts/check_platform_topic_independence.py` now includes semantic topic-domain normalization, so same-topic wording variants such as spreadsheet/Excel cleanup are treated as duplicates.
- Video beat extraction now prefers blank-line paragraphs before sentence splitting, preventing long script sections from being truncated into incomplete cards.

### Operational Rule
- Standalone scripts must emit the same evidence contract as Pipeline packages. A handoff package or runner manifest without tool selection evidence is incomplete, even when media rendering itself succeeded.
- Existing packages generated before this fix may still miss evidence fields. Treat them as legacy artifacts; regenerate packages if strict gate evidence is required for review or publication.

### Verification
- Local script/media regression: `python -m pytest tests/test_operational_scripts.py tests/test_video_toolchain_runner.py tests/test_media_quality.py tests/test_video_toolchain.py -q` => `95 passed`.
- Local full regression: `python -m pytest -q` => `548 passed, 2 subtests passed`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.
- Hermes script/media regression after sync: `95 passed`.
- Hermes full regression after sync: `548 passed, 2 subtests passed`.
- Hermes project audit after sync: `ok: true, issues: []`.

## 2026-08-08 - International Short Video Legacy Entry Hardening

### Finding
- `scripts/intl_short_video_pipeline.py` was a legacy standalone entrypoint for YouTube Shorts and TikTok. Its header and `publish_video()` path still described AiToEarn automatic publishing, which conflicted with the current policy: YouTube, TikTok, Threads, Bilibili, Douyin, Shipinhao, and Xiaohongshu must be manual-handoff unless a separately approved publisher policy exists.
- The same script wrote a daily manifest, but legacy rows did not include `tool_invocation_manifest`, `tools_capability_analysis`, or `tool_selection_plan`, so a standalone international handoff package could look complete while bypassing the newer evidence contract.

### Fixed
- The legacy international short-video script is now manual-handoff only for YouTube/YouTube Shorts, TikTok, and Threads. Its publish guard returns without calling AiToEarn for those platforms even when an AiToEarn key is present.
- Dry-run and generated rows now include `status=handoff_pending`, `publish_boundary=manual_handoff_only_no_aitoearn`, a forbidden-action list, `tool_invocation_manifest`, `tools_capability_analysis`, and `tool_selection_plan`.
- Regression tests verify both the handoff manifest evidence and the AiToEarn publish guard for YouTube, YouTube Shorts, TikTok, and Threads.

### Operational Rule
- Do not use international legacy scripts as live publishers. They may only prepare review/handoff packages unless the main Pipeline policy explicitly enables and validates a publisher.
- Any future standalone package writer must emit the same tool-selection evidence contract as Pipeline output; otherwise the package is incomplete and must be regenerated.

### Verification
- Local international short-video regression: `python -m pytest tests/test_video_toolchain_runner.py -q` => `26 passed`.
- Local script/media regression: `python -m pytest tests/test_video_toolchain_runner.py tests/test_media_quality.py tests/test_delivery_health.py tests/test_operational_scripts.py -q` => `99 passed, 2 subtests passed`.
- Local full regression: `python -m pytest -q` => `550 passed, 2 subtests passed`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.

## 2026-08-08 - AiToEarn Disabled Platform Guard Completion

### Finding
- `build_publisher()` already blocked `aitoearn-flow` for YouTube, TikTok, Twitter/X, and Threads, and manual-only platforms were also protected by the earlier manual-handoff override.
- The adjacent `aitoearn-draft` / `aitoearn-intl` branch did not use the same disabled-platform guard. A mistaken publisher config could therefore route a disabled platform into an AiToEarn draft publisher instead of failing closed to handoff.

### Fixed
- `aitoearn-draft`, `aitoearn-intl`, and `aitoearn-flow` now share the same disabled-platform guard for YouTube, TikTok, Twitter/X, and Threads.
- A regression test verifies all three AiToEarn publisher types resolve to `ManualHandoffPublisher` for the disabled platforms.

### Operational Rule
- YouTube, TikTok, Twitter/X, and Threads must not be routed through AiToEarn by any publisher type. Use the approved cookie/manual route for X where configured; otherwise produce a handoff package.

### Verification
- Local disabled-platform probe: YouTube/TikTok/Threads/Twitter/X with `aitoearn-draft`, `aitoearn-intl`, and `aitoearn-flow` all resolved to `ManualHandoffPublisher`.
- Local publisher/health regression: `python -m pytest tests/test_publishers_v2.py tests/test_delivery_health.py tests/test_auth_registry.py -q` => `42 passed, 12 subtests passed`.
- Local boundary regression: `python -m pytest tests/test_publishers_v2.py tests/test_delivery_health.py tests/test_health_refresh.py tests/test_platform_boundary_and_growth_policy.py tests/test_video_toolchain_runner.py -q` => `81 passed, 12 subtests passed`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.

## 2026-08-08 - Douyin Account Alias Boundary Completion

### Finding
- The rulebook correctly defined `douyin_pet` and `douyin_ai` as isolated Douyin operating accounts, but shared policy helpers only recognized the base platform name `douyin`.
- If a runner mistakenly passed `douyin_pet` or `douyin_ai` as the platform key, the route was safe by default but semantically weak: region, short-video classification, Douyin detection, and manual-handoff policy were not all guaranteed to resolve as Douyin.
- `delivery_health_decision()` also relied on refreshed health-state data or the manual-only platform set; explicit AiToEarn configs for disabled platforms were not checked at the top of the live health gate.

### Fixed
- `content_policy` now treats `douyin_pet` and `douyin_ai` as domestic Douyin short-video manual-handoff aliases.
- Publisher tier/region helpers now normalize `douyin_pet` and `douyin_ai` to the base Douyin platform.
- Delivery health now recognizes `aitoearn-draft`, `aitoearn-intl`, and `aitoearn-flow` configs for disabled platforms and returns `manual_handoff_only` before any live publishing route can be considered.
- Regression tests cover Douyin account aliases, manual-handoff health, and AiToEarn disabled-platform health semantics.

### Operational Rule
- Hermes may use `douyin_pet` and `douyin_ai` as account-scoped execution keys, but any publish, health, or media policy check must resolve them as Douyin manual-handoff channels.
- A disabled AiToEarn platform should remain `manual_handoff_only`, not `unknown` and not usable.

### Verification
- Local Douyin alias probe: `douyin_pet` and `douyin_ai` resolved as `domestic`, manual handoff, and `ManualHandoffPublisher`.
- Local boundary regression: `python -m pytest tests/test_platform_boundary_and_growth_policy.py tests/test_delivery_health.py tests/test_publishers_v2.py tests/test_douyin_account_variants.py tests/test_health_refresh.py -q` => `59 passed, 29 subtests passed`.

## 2026-08-09 - Markdown Source Matrix Gate Compatibility

### Finding
- Hermes generated `analysis_20260809.md` for the WeChat operation analysis with a complete source table, but `scripts/check_platform_topic_independence.py` only treated Markdown as a weak title fallback.
- The gate could therefore report `analysis_file_missing`, `attempted_sources_lt_5`, `successful_sources_lt_3`, and `platform_internal_verification_missing` even when the Markdown analysis contained enough source evidence.
- The script also contained mojibake topic-domain keywords that were fragile under Windows encoding rewrites.

### Fixed
- Markdown analysis files now parse selected topic, source tables, bullet source rows, platform-internal evidence, successful/attempted counts, and `shared_trend_only`.
- JSON remains the preferred and first-read format. Markdown is now a compatible fallback, not a bypass.
- Topic-domain normalization now uses ASCII-stable keywords to avoid broken string literals after local encoding operations.
- Markdown table rows now tolerate emoji-free or encoding-degraded success statuses. Non-failure status cells count as successful evidence, while explicit failure markers such as `login_required` remain failures.
- Markdown topic extraction now falls back to the first document heading when localized field labels are degraded in remote command transport.

### Operational Rule
- Hermes may continue by writing `platform_source_matrix_<date>.json` for strict evidence, or use `analysis_<date>.md` if it contains a clear topic plus a source/status table.
- A Markdown analysis must still prove at least 5 attempted sources, at least 3 successful sources, platform-internal evidence or failure reason, and `shared_trend_only=false`.

### Verification
- Local WeChat Markdown gate probe: `analysis_20260809.md` with 7 attempted sources, 6 successful sources, and platform-internal evidence passed.
- Local operational script regression: `python -m pytest tests/test_operational_scripts.py -q` => `9 passed`.
- Local focused regression: `python -m pytest tests/test_operational_scripts.py tests/test_media_quality.py tests/test_content.py tests/test_platform_boundary_and_growth_policy.py tests/test_delivery_health.py -q` => `91 passed, 19 subtests passed`.
- Local full regression: `python -m pytest -q` => `557 passed, 29 subtests passed`.

## 2026-08-09 - WeChat Image-Message Card Dual Track

### Finding
- Hermes had a working private `wechat_image_post_cards.py` script and a `newspic` draft publisher, but the capability was not represented in the public repo workflow or quality gates.
- The private card script contained a default Pexels API key and allowed a CSS-gradient fallback when real background retrieval failed.
- The private `publish_image_draft()` path created `article_type=newspic` drafts, but image-message batchget verification could warn and continue, which is not strong enough for production completion.

### Implemented
- Added `scripts/wechat_image_post_cards.py`, a publish-safe image-message card generator that reads provider credentials only through the existing image-provider secret lookup and does not upload to WeChat.
- Added `scripts/validate_wechat_image_post_packet.py` and `validate_wechat_image_post_packet()` to gate image-message cards independently from long-form articles.
- Added `wechat_image_post_plan` to the WeChat professional draft toolchain so every WeChat long article can carry the required companion image-message plan.
- Updated the channel rulebook so WeChat requires the image-message card generator, image-message validator, newspic draft API, real-scene backgrounds, layout diversity, readability, and batchget postcheck.
- Added public-script privacy coverage for the new scripts.

### Design Rules
- Image-message cards use a 3:4 `1080x1440` format with 3-20 cards.
- Card 1 must be a hook/cover card; the final card must be a CTA card.
- Each card must carry one idea, one payoff, and a save/comment reason.
- Batch-level layouts and palettes must rotate; fixed-template repetition is rejected.
- Real or licensed scene backgrounds are required; CSS gradients, pure colors, procedural backgrounds, and placeholders cannot pass production validation.
- Production success requires `newspic` batchget confirmation with title present and image count matched.

### External Research Inputs
- WeChat cover and article guidance: covers materially affect open rate; cover/title are the first visible decision point.
- Carousel guidance: one idea per slide, clear visual flow, readable typography, strong hook, and one clear CTA improve swipe/read/save behavior.
- These findings were translated into hard gates rather than stored only as copywriting advice.

### Verification
- Local focused regression: `python -m pytest tests/test_media_quality.py tests/test_wechat_toolchain.py tests/test_operational_scripts.py tests/test_platform_quality_gate_runtime.py tests/test_hermes_wechat_adapter_script.py -q` => `72 passed`.
- Local script probe: placeholder background packets are generated but blocked by `real_scene_backgrounds` and `draft_postcheck`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.
- Local full regression: `python -m pytest -q` => `558 passed, 29 subtests passed`.

## 2026-08-09 - Unified Image-Text Card Recipe

### Finding
- The WeChat image-message lane had strong concrete checks, but the reusable planning layer was still split across article recipes, knowledge-card recipes, and script-local card plans.
- That made it easy for Hermes to generate attractive-looking screenshots without proving why the layout, background, image source, text rhythm, and CTA fit the topic and platform.
- External carousel/card practices were useful, but they needed to become a code contract rather than an operator reminder.

### Implemented
- Added `image_text_card_recipe_v1` in `content_platform.content_recipe` with builder, validator, core fingerprint, instance fingerprint, style matrix, layout matrix, card-to-asset binding, source policy, and engagement contract.
- Added `config/image_text_card_modules.json` as the free-first capability registry for image-text cards across WeChat, Xiaohongshu, Zhihu, Juejin, Bilibili, Douyin, Shipinhao, YouTube, and TikTok handoff packages.
- Added `scripts/validate_image_text_card_recipe.py` so Hermes can validate the recipe from either a standalone recipe JSON or a full content packet.
- WeChat image-message packets now must include `image_text_card_recipe`; `validate_wechat_image_post_packet()` rejects missing or weak recipes.
- `DraftGenerator`, the WeChat professional toolchain, `wechat_image_post_cards.py`, and MCP `build_content_recipe` now emit the unified recipe.
- Tool selection now analyzes `image_text_card_recipe` as a first-class article/image-card tool group.

### Operational Rule
- For any article, carousel, image-message, Xiaohongshu note, or image-card video source pack, Hermes should first build or load `image_text_card_recipe`.
- The recipe must prove: cover hook, one idea per card, final single CTA, at least 3 layout/palette/text-arrangement variants, foreground and background effects separated, topic-matched real or generated images, source/license tracking, and 7-day fatigue checking.
- Optional external MCPs such as paper design, PostNitro, and ContentDrips may be considered as design inspiration or future connectors, but they are not mandatory production dependencies.
- Production card backgrounds cannot be CSS gradients, pure-color placeholders, or random stock photos.

### Verification
- Local focused regression: `python -m pytest tests/test_media_quality.py tests/test_content.py tests/test_mcp_server.py tests/test_wechat_toolchain.py tests/test_operational_scripts.py -q` => `75 passed`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.

## 2026-08-09 - Kuaishou Runtime Patch Formalization

### Finding
- Hermes had four local runtime patches in Kuaishou/video scripts that were not in GitHub.
- Three changes were valid production hardening: thumbnail forwarding to SAU, a more reliable CN proxy IP probe, and excluding `_bg`/`_text` helper layers from full-card visual gates.
- The Kuaishou layered-render patch had the right direction, but its text-layer motion branches were effectively identical, so the comments promised separate text motion without real visible variation.

### Implemented
- `kuaishou_publish_with_postcheck.py` now extracts thumbnails through `_thumbnail_path()`, including nested `cover.path` / `cover.local_path`, and forwards an existing file to SAU `--thumbnail`.
- `validate_kuaishou_video.py` now reads `CN_PROXY` from the environment and converts `socks5`, `socks5h`, or HTTP proxy values into curl arguments; the IP probe uses `myip.ipip.net` instead of the unstable `httpbin.org` endpoint.
- `video_toolchain_runner.py` now excludes `_bg.png` and `_text.png` auxiliary layers before running the cinema visual gate.
- `kuaishou_render.py` now renders complete card frames plus separate background and transparent text layers, then uses layered ffmpeg composition when both layers exist.
- Text-layer motion is now generated by `_text_layer_filter()` with distinct fade, slight zoom, left drift, and right drift paths; `_layered_segment_filter()` composes background and text filters into a single verified graph.

### Operational Rule
- Kuaishou packets should include `cover_path` or `thumbnail_path` when a platform-ready cover exists.
- Kuaishou resource probes must honor the injected `CN_PROXY`; do not hard-code a proxy port in new code.
- `_bg.png` and `_text.png` files are auxiliary render layers and must not be treated as completed card screenshots.
- If layered rendering is enabled, foreground text motion and background motion must be separately represented in code, not just in comments.

### Verification
- Local focused regression: `python -m pytest tests/test_kuaishou_publish_guards.py tests/test_operational_scripts.py tests/test_video_toolchain_runner.py -q` => `43 passed`.
- Local expanded regression: `python -m pytest tests/test_media_quality.py tests/test_video_toolchain_runner.py tests/test_kuaishou_publish_guards.py tests/test_operational_scripts.py tests/test_video_toolchain.py -q` => `112 passed`.
- Local rulebook validation: `channel rulebook ok: 19 channels`.
- Local project audit: `ok: true, issues: []`.
- Local full regression: `python -m pytest -q` => `564 passed, 29 subtests passed`.
# 2026-08-12 - WeChat Growth Constraint Alignment

## Finding
- Hermes server strategy v5 capped WeChat at three weekly articles and required direction-level dedupe, but local executable policy still carried the older two-article recovery contract.
- The existing direction register blocked repeated directions in cross-platform topic gates, but the final WeChat publish-license gate only checked delivered count, publish hour, title similarity, and title fatigue terms.
- This left a bypass where two different titles could still represent the same WeChat direction at the draft-upload boundary.

## Implemented
- `scripts/gzh_publish_license.py` now accepts `--direction` and blocks recent same-direction conflicts from the run manifest.
- `scripts/hermes_wechat_adapter.py` forwards `content_direction`, `topic_direction`, `direction`, or `content_line` from the packet into the WeChat publish-license gate.
- `content_platform.growth_policy`, `content_platform.media_quality`, and `scripts/validate_channel_rulebook.py` now align with the server v5 contract: WeChat three articles per week, direction-level dedupe required, and weekly manual backend export required when APIs are unavailable.
- `docs/CONTENT_OPERATIONS_QUALITY_DIRECTIVE.md` now records the operating rule: title-only dedupe is insufficient, WeChat must pass direction dedupe, backend metrics require weekly manual import when automated APIs fail, and Video Channels stays manual-handoff/screencast-first rather than automatic article mirroring.

## Verification
- Added regression coverage for WeChat same-direction blocking and adapter direction forwarding.
- Focused red/green verification: new tests failed before implementation and passed after implementation.

# 2026-08-12 - Strategy Evidence Isolation And Account Readiness

## Finding
- Live collection can obtain useful account snapshots from public pages and creator dashboards, but those totals cannot attribute performance to a title, work, or account variant.
- Historical `performance_cycle` rows without explicit content evidence could still influence strategy because older records lacked an eligibility flag.
- The two Douyin accounts were correctly modeled as distinct operating lanes, but a missing account-specific history could fall back to the shared platform history.

## Implemented
- Added a strict `strategy_eligible` contract. Public pages, generic Hermes scraper fallback, creator-dashboard totals, and metric files without a content identifier are stored as audit-only snapshots.
- A JSON metrics export is eligible only when at least one row identifies a work by `job_id`, title, or a stable content ID. CSV imports already use `job_id` or title.
- Old `performance_cycle` rows without an explicit eligible flag are excluded from both feedback summaries and historical ranking context. Data remains in the database for audit.
- Douyin account strategies now read only their own account history. They cannot borrow a shared `douyin` baseline.
- Added `metrics-readiness`, which reports missing account-specific content sources without printing private runtime configuration.

## Operational Rule
- Treat `content_metrics_configured` as configuration readiness, not proof that a source successfully collected data. Use the next cycle report to confirm content evidence was actually recorded.
- Do not create or copy account cookies automatically. Separate authenticated exports or approved APIs are required for `douyin_pet` and `douyin_ai`.

## Verification
- Added red/green regression coverage for snapshot isolation, legacy-cycle filtering, account history isolation, source readiness, TikTok empty-content responses, and Hermes scraper fallback.
- Readiness validation also opens configured JSON exports and requires a content identifier; a path alone is not treated as usable evidence.

# 2026-08-12 - Scheduled Operations And Hermes Progress Recovery

## Finding
- The midnight worker was enabled but systemd did not define `HOME`, so the entrypoint could fail before producing a batch result.
- The growth cycle had no progress message wrapper. The WeChat refresh reported an expected creator-login expiry as a failed systemd service.
- Workflow events were locally durable, but no private Hermes notification target or overnight observer had been configured.

## Implemented
- Systemd templates now set `HOME`, load an optional untracked `secrets/notifications.env`, and execute notification-aware wrappers.
- The wrappers emit bounded start/progress/completed/blocked/failed events through Hermes only when `AI_SELF_MEDIA_HERMES_TARGET` is configured. Delivery failure never interrupts the worker.
- The midnight wrapper reports error exits, preserves atomic checkpoints, and still exits cleanly for no-slot or missed-window cases.
- The WeChat wrapper treats an expired creator login as an actionable blocked data-source condition, writes its report, sends a notification, and lets the timer remain healthy for the next recovery attempt.
- `create_hermes_overnight_monitor.py` remains the read-only three-minute progress observer; its target is server-private and not committed.

## 2026-08-14 - Overnight State And Acceptance Integrity

### Finding
- The overnight batch could leave `state.json` inconsistent with durable
  jobs/deliveries, and an acceptance result was printed without becoming a
  release-blocking record.
- A server-only helper wrote generic placeholder trend matrices. That made an
  evidence-shaped artifact look like platform-specific research even when no
  such evidence existed.
- Kuaishou management pages show valid submissions as `under_review`; this
  must be distinct from both failed verification and publication.

### Implemented
- Added persisted `jobs.acceptance_json`, `workflow_acceptance_v1`, and an
  `overnight-sync-state` command. The batch writes `acceptance_summary.json`
  and reconciles actual job/delivery state after every run.
- Publishing fails closed when configured unified acceptance has not passed.
  Failed acceptance changes the task to `blocked`; wrapper success cannot
  create a draft or publish claim.
- Strict planning requires a real platform-specific source outcome. A fresh
  strategy snapshot remains context, not proof that a topic appeared on that
  platform. Placeholder evidence generation is removed.
- Kuaishou postcheck accepts `under_review` only with matching title and
  description and records that state as `under_review`, never `published`.
- A recovered `running` row becomes an explicit blocked recovery task and
  `review_required` is terminal. The timer has a bounded configurable 60-minute
  admission window instead of a 15-minute-only window.
- Added conservative runtime-artifact archival tooling. It moves only old,
  rebuildable intermediates during disk pressure; final media, covers,
  manifests, reports, and recent files remain untouched.

### Verification
- TDD red/green coverage covers generic-evidence rejection, durable state
  reconciliation, failed acceptance blocking, Kuaishou review state, recovery
  safety, timer admission, CLI sync, and bounded cleanup.

## 2026-08-13 - Quality Orchestration Hardening

### Finding
- Independent platform source collection, direction registration, visual recipes, BGM fingerprints, and checkpoints already existed, but their contracts did not fully express the operating rules.
- Direction registration treated every same-direction topic as a conflict. That incorrectly rejected legitimate cross-platform resonance even when each platform had independent evidence and a distinct execution angle.
- Video planning had `visual_recipe` and `segment_motion_evidence`, but no explicit per-scene narration/subtitle/asset/motion binding. Content depth was also not exposed as a reusable gate, so a thin draft could promise a future installment without proving a real series plan.

### Implemented
- `record_topic()` and `check_platform_topic_independence.py` now allow same-direction overlap only when every package has a distinct source-matrix identity, at least eight attempted and five successful sources, platform-internal verification, a platform signal, and a platform-specific adaptation reason. Documented follow-ups continue to work; unexplained reuse remains blocked.
- Added `content_depth_plan_v1` and `scripts/content_quality_gate.py --check-depth`. The contract requires three knowledge points, a case or demo, executable steps, a counterexample, a takeaway, an interaction prompt, and a `series_plan` whenever the copy promises a next episode or follow-up.
- `DraftGenerator` emits a depth plan for generated article packets so the new validation is available to downstream gates without changing publishers.
- `visual_recipe` now owns `scene_manifest_v1`. It expands existing `scene_asset_match` into at least six narration/subtitle/asset/evidence records with separate background, subject, text, and transition motion, and `video_toolchain_runner.py` writes `scene_manifest.json` before the pre-render gate.
- The pre-render gate can require the scene manifest. The normal video toolchain uses that requirement, so a render cannot proceed with only a generic recipe.
- Added a metadata-only BGM candidate catalog. It preserves source, license, fingerprint, and mood to avoid repeated remote discovery; it deliberately strips local audio paths and never serves reusable audio. Existing fingerprint gates remain authoritative.
- Video ResourceGuard now defaults to 1200MB available memory, warns at 84% disk use, and remains fail-closed at 88%. Existing video lock and render checkpoints remain the concurrency/caching mechanism.

### Operating Rules
- Do not introduce a hard no-overlap topic rule. Natural overlap is valid only with independent evidence, a platform-specific signal, and a documented adaptation reason.
- A BGM catalog is discovery metadata, not a music library. Every render still downloads a fresh licensed real-instrument track and must pass the existing fingerprint gate.
- `scene_manifest.json` is derived from `visual_recipe`; do not maintain a second scene plan.
- Edge-TTS receives a deterministic per-segment delivery plan (hook, explanation, proof, CTA) with bounded rate, pitch, and pause controls. Offline TTS/VQA experiments belong to bounded night-time A/B work, never a permanent worker on the constrained Hermes host.

### Verification
- TDD red/green checks covered independent natural-overlap approval, unexplained duplicate rejection, continuation-promise rejection, depth CLI validation, scene-manifest enforcement, metadata-only BGM catalog behavior, and higher video headroom.
- Focused regression: `python -m pytest tests/test_content.py tests/test_ops_run.py tests/test_content_depth.py tests/test_bgm_catalog.py tests/test_pre_render_gate.py tests/test_resource.py tests/test_video_toolchain.py tests/test_video_toolchain_runner.py -q`.

## 2026-08-14 - Canonical Scene Contract And Runtime Closure

### Finding
- The new `scene_manifest_v1` and the legacy pre-render gate described the
  same artifact with incompatible fields. A valid manifest could therefore be
  rejected before rendering.
- A generation-stage platform gate attempted to require evidence that exists
  only after a video render. Motion evidence also sampled too few frames for
  the operating quality contract.
- Runtime-artifact cleanup worked from the project directory but failed when a
  scheduler invoked the script by absolute path; no cleanup timer was enabled.

### Implemented
- The pre-render gate now delegates to the canonical scene-manifest validator.
  `scene_manifest` remains the single source of truth; visual recipe output is
  compatibility data, not a parallel timeline.
- TTS keeps display text and compiled speech text separate, preserves measured
  segment timing, supports Qwen with Edge fallback, and retains bounded
  per-segment expression controls. Legacy Edge adapters without rate/pitch
  kwargs fall back safely.
- Video-only evidence is explicitly deferred until the renderer can produce
  it; post-render validation remains fail-closed. Motion probes now sample five
  positions across the final artifact.
- Added a portable cleanup entrypoint and
  `hermes-content-platform-runtime-cleanup.timer`. It archives only old
  reconstructable intermediates and never final media, covers, manifests,
  reports, or handoff evidence.

### Verification
- Local full suite: `732 passed, 29 subtests passed`.
- Hermes full suite after deployment: `743 passed, 29 subtests passed`.
- Hermes overnight and cleanup timers are `enabled` and `active`; cleanup dry
  run completed outside the project working directory.

## 2026-08-14 - Overnight Recovery And Live Progress Closure

- A dead renderer PID recorded in `data/locks/video.lock` is now reclaimed;
  a live owner remains exclusive. This prevents a killed render from failing a
  later serial overnight task.
- Batch reconciliation preserves a blocked handoff with its evidence failure
  instead of upgrading it to `handoff_ready` from queue metadata.
- The append-only overnight journal now records job creation, generation
  outcome (status and artifact kinds only), acceptance/blocking, and staging.
  The observer remains read-only and can report those real stage changes every
  three minutes without exposing content bodies or credentials.
- Historic state reconciliation also repairs legacy `handoff_ready` rows when
  their retained reason proves the handoff media was missing. Old work is not
  replayed or published during this repair.

## 2026-08-16 - Overnight Execution And Video Evidence Closure

### Fixed
- Registered `overnight-acceptance` in the production CLI. The systemd wrapper
  now executes the same checked-out command it invokes at the end of a batch,
  rather than failing after work has finished because the parser lacks a bridge.
- Video platforms defer video-only checks during text generation, then run a
  separate fail-closed rendered-media gate. This covers `article_explainer_video`
  as well as short-video labels, preventing Kuaishou from being rejected before
  the renderer has had a chance to create its required artifacts.
- The rendered gate consumes manifest, motion, audio, subtitle, background and
  licensed-BGM evidence written by the renderer. A playable MP4 alone is not a
  delivery success.
- Kuaishou receives concrete trend samples copied from successful collection
  evidence. Planned sources are never converted into fabricated samples.
- A bounded one-time retry handles only transient timeouts, connection resets,
  rate limits, locks and resource-busy failures. It never retries authentication,
  policy, content-quality, publish, or manual-review failures.

### Portability And Safety
- Host-agent integrations now resolve through `AGENT_HOME` or
  `CONTENT_PLATFORM_AGENT_SCRIPTS_DIR`; public source no longer embeds a private
  host path. The legacy cinema adapter is treated as an unverified preview until
  it writes the standard renderer manifest and packet, then safely falls back to
  the verified toolchain.
- Runtime backups and local operation outputs are ignored by Git. They remain on
  the host but cannot enter a public release.

### Verification
- TDD red/green coverage added for CLI acceptance, Kuaishou video deferral,
  rendered evidence, portable adapters, retry classification, and concrete
  Kuaishou trend evidence.
- `project-audit` reports no private paths or credentials in the release tree.

## 2026-08-16 - Runtime Consistency Layer

### Finding
- The overnight workflow had valid generation and rendering gates, but manual
  publication, scheduled planning, delivery verification, and monitoring did
  not share a durable cross-job state model. This allowed a manually published
  topic to be selected again by a new scheduled job.
- `review_required` represented unrelated lifecycle meanings, while a stale
  delivery-health snapshot was detected only at the final publish boundary.
- The existing monitor was intentionally read-only, so a stalled batch had no
  independent heartbeat observer or durable reconciliation path.

### Implemented
- Added a global seven-day topic ledger used by `auto` and `overnight-prepare`.
  `record-manual-publication` creates a normal job, delivery receipt, and topic
  reservation from a platform/topic/fingerprint instead of relying on an
  unrelated future job ID.
- Added real-platform trend evidence rollout modes. `shadow` records a failed
  evidence gate without changing current production admission; `enforce`
  blocks candidates that lack a timestamped successful platform source and a
  matching candidate sample. Strategy snapshots are context only.
- Added explicit `awaiting_review` and `published_pending_verification` batch
  states, with legacy `review_required` migration. Acceptance summaries now
  list action-required platform rows instead of implying publication.
- The timer refreshes delivery health before planning and reports `partial` as
  a follow-up condition. A separate five-minute systemd supervisor reads the
  heartbeat, recovers only stale leases, reconciles durable facts, and never
  starts a new batch or republishes content.

### Rollout
- Keep `real_platform_trend_evidence_mode=shadow` for one observed batch. Read
  every `trend_evidence_gate` result, repair unavailable collection lanes, then
  switch the private runtime config to `enforce` only when every due platform
  has real collection evidence.
- Every manual publication must be recorded immediately with
  `record-manual-publication`; direct database delivery inserts are unsupported
  because they cannot reserve the topic safely.

## 2026-08-16 - Secure Operations And Terminal-State Closure

### Finding
- Review-action tokens were previously added to workflow notifications. That
  made a private log or message a bearer-credential store instead of an
  operational report.
- The supervisor reconciled only stale running batches. A terminal batch that
  predated a state-vocabulary change could continue showing `review_required`
  without an actionable acceptance summary.
- A shell failure before `result.json` existed sent an alert but did not leave
  a consistent machine-readable failure artifact for the next observer.

### Implemented
- Review tokens are now issued only by the authenticated review command. The
  notifier never stores or transmits them; review notifications direct an
  operator to the secure console. `notification-redact` removes legacy
  `review_actions` fields from an existing notification log.
- The five-minute supervisor always runs `overnight-sync-state` before health
  inspection. This migrates terminal state vocabulary and updates
  `acceptance_summary.json` without replaying work or publishing content.
- The overnight entrypoint writes a redacted `failed` result and synchronizes
  durable state before reporting any unexpected shell error.

### Production Rule
- Enable the workflow notifier only through `AI_SELF_MEDIA_HERMES_TARGET` and
  keep `network_enabled` private runtime configuration. Never place targets,
  review tokens, cookies, keys, or full generated bodies in Git-tracked config
  or progress logs.

## 2026-08-16 - Native Trend Candidate Preference

- If a verified platform-native source is available, overnight ranking now
  prefers its eligible candidates over generic cross-platform headlines.
- The strict evidence contract is unchanged: a missing native source remains
  a block in `enforce` mode rather than being replaced with strategy text.
- Added real web-search collection lanes for Xiaohongshu, YouTube, and TikTok.
  They are opt-in in runtime configuration and retain their true source labels.
- Source transport suffixes such as `douyin:web_search` are now correctly
  associated with the verified `douyin` collection lane; this does not broaden
  collection provenance beyond the named platform source.
- WeWrite hotspot rows preserve both the `wewrite_hotspots` transport and an
  optional upstream source, so public-account evidence stays traceable.
- The public-account lane also has a dedicated `wechat` real-search source;
  a broad cross-platform item cannot substitute for it in enforce mode.
- Runtime enforcement must report a missing or off-topic native collection as
  an explicit `blocked` reason. It must not fall back to a generic trend just
  to keep a scheduled slot producing output.

## 2026-08-16 - High-Quality Film Renderer Contract

- The production default is now `FILM_QUALITY_PROFILE=high` plus
  `FILM_MOTION_MODE=cinematic`. All platforms use bounded Playwright CSS
  recording or element-level frame rendering; static screenshot motion is not
  an automatic fallback.
- A safe renderer requires the explicit, exceptional pair
  `FILM_QUALITY_PROFILE=degraded`, `FILM_MOTION_MODE=safe`, and
  `FILM_ALLOW_DEGRADED=1`. Its output is marked degraded and is not eligible
  for normal automatic delivery.
- `render_contract.json` fingerprints renderer version, quality mode, script,
  scene manifest, backgrounds, dimensions, and transition settings. A changed
  or missing contract with derived outputs invalidates only reproducible
  renderer assets (`shots`, WebM, frame cache, groups, audio mix, and final).
- Final delivery now records shot provenance, fallback use, audio quality,
  A/V timing, and full-timeline measured motion. A cinematic fallback, failed
  script gate, missing scene manifest, audio other than 44.1 kHz stereo, or
  insufficient real frame motion blocks the artifact.
- Timeline alignment uses the exact transition duration for every real
  boundary, including zero-duration group concatenations, rather than a fixed
  global transition estimate.
- Element-level high-resolution frame sequences have an independently bounded
  timeout of at least 90 seconds, scaled by scene duration. This prevents a
  valid long 1080p animated scene from being cut off by the short CSS-recording
  deadline; a real timeout still fails closed rather than switching to a still.
- Element motion is recorded directly by Chromium while an in-page
  `requestAnimationFrame` loop drives `renderFrame`. The prior per-frame PNG
  capture path was too costly for a long 1080p scene on the production host;
  the new path preserves the same dynamic scene state without a static-image
  fallback or a screenshot bottleneck.
- A/B shot allocation now explicitly reserves the internal long crossfade plus
  a 150 ms narration margin. The subsequent probe remains authoritative, but
  a nominally matching script duration can no longer lose roughly 450 ms at
  every A-to-B transition before that probe runs.
- Full-timeline motion remains a measured high-quality gate. Main shot
  templates use continuous six-second linear background camera movement rather
  than an eleven-second ease-in/out cycle, increasing persistent visual change
  without relaxing the active-motion threshold or introducing visual jitter.
- Motion verification distinguishes sustained smooth camera movement from a
  frozen frame: it requires mean change `>=0.015`, at least 85% of samples
  above a low continuous-motion floor, at least 20% above the stronger motion
  floor, and two real motion peaks. This is stricter than a metadata check and
  still rejects static or single-transition-only output.
- The motion-evidence policy version is part of `render_contract.json`. A
  scoring-policy change therefore cannot leave an old failed or passed quality
  report beside a new runtime; the next render refreshes its evidence through
  the same contract mechanism as renderer and asset changes.

## 2026-08-16 - Real Trend Evidence Transport Compatibility

- A real source may record its transport as a suffix, for example
  `douyin:web_search`, while the source-health row remains `douyin`. The
  platform matrix now recognizes that relationship without treating unrelated
  shared trends as native evidence.
- ASCII lane keywords now match valid CJK-adjacent abbreviations, while retaining Latin-only boundaries that reject incidental
  matches such as the `ai` inside `paid`.
- This repairs the false `platform-specific real trend collection missing`
  block for the Douyin AI lane when its real direct collection succeeded.

## 2026-08-16 - Native Trend Evidence and Growth Signal Repair

- The Douyin lane now reads the native hot-board endpoint directly and records
  its observed heat, rank, and `douyin.com` search URL. Generic web-search
  results are no longer the default Douyin source.
- A `*:web_search` candidate satisfies a platform-native matrix only when its
  result URL belongs to the requested platform. For example, a Zhihu URL
  discovered through a query labelled `douyin:web_search` remains external
  reference material and cannot unlock Douyin generation or publishing.
- Auto-routing now derives G7 growth signals from observed candidate facts
  (engagement, freshness, and source provenance). This prevents a valid
  candidate from being blocked solely because the old route persisted only one
  synthetic signal.
- If the native hot board contains no topic matching the account lane, or an
  authenticated native search is challenged, the platform must report
  `blocked` with the collection reason. It must not substitute unrelated
  general-news trends, cached hypotheses, or external search results merely to
  fill the daily slot.
- The automatic status distinguishes `platform-specific real trend collection
  missing` from `no eligible native topic candidate for configured lane`; the
  latter means collection succeeded but no source item matched the account
  niche. This keeps real-time reports actionable without weakening the gate.

## 2026-08-16 - Bounded Default Video TTS

### Finding
- The default card-video renderer retried Edge TTS failures, but an individual
  asynchronous `edge_tts` request had no deadline. A provider connection that
  neither succeeded nor raised could hold the whole overnight task in
  `generate_audio` indefinitely, leaving only a stale platform-level heartbeat.

### Implemented
- `kuaishou_render.gen_tts` now applies a bounded timeout to every provider
  attempt (`KUAISHOU_TTS_ATTEMPT_TIMEOUT_SECONDS`, default 45 seconds), keeps
  the existing bounded retry count, removes partial audio between attempts,
  and raises a redacted timeout failure after the final attempt.
- The failure text includes `timeout`, allowing the existing bounded
  overnight transient-retry policy to make one recoverable retry and then
  finish in an explicit failed/blocked state rather than hanging silently.
- Regression coverage simulates a permanently waiting async provider and
  verifies fail-closed termination; the normal retry/evidence test remains in
  place.

### Operational Rule
- Do not treat a running process as production success. A video task is
  healthy only when the batch state advances, its append-only events advance,
  and the final handoff artifacts pass acceptance. A provider timeout is a
  reportable terminal condition, never a reason to bypass media gates.

## 2026-08-16 - Bounded Online BGM Downloads

### Finding
- The online BGM resolver had a global selection budget, but a selected
  response was read in one unbounded `response.read()` call. A slow transfer
  could therefore outlive the resolver budget and hold the video renderer
  after visual and voice rendering had already finished.

### Implemented
- BGM downloads now fail before opening a connection when the budget is
  exhausted, stream in 64 KiB chunks, and re-check the deadline between
  chunks. Partial files are deleted on every transfer failure.
- The existing resolver then either chooses another licensed real-instrument
  source inside its budget or returns an explicit blocked result. It never
  substitutes synthetic or unlicensed music to make a handoff appear ready.

## 2026-08-16 - Short-Video Fact Gate Contract

### Finding
- The generic GEO gate is calibrated for sourced long-form articles: it
  expects multiple numerical claims, references, and article structure. A
  bounded 8-beat short-video script can be truthful, source-evidenced, and
  suitable for rendering while correctly scoring below the long-form threshold.
- This made the enforced workflow block a Douyin AI task before the media
  pipeline, despite its verified trend matrix and separate growth-recipe gate.

### Implemented
- G2 now uses an explicit short-video contract for short-video content forms
  and platforms: the script must directly answer the user need and be composed
  of short readable beats. It records this decision as `contract=short_video`.
- G7 remains mandatory and unchanged: platform-native trend evidence and
  source provenance cannot be replaced by the short-video GEO result.
- Long-form content retains the original `score >= 40` GEO requirement and is
  recorded as `contract=long_form`.
- G3 keeps all anti-generic checks for short video. Its long-form burstiness
  threshold is ignored only when `burstiness` is the sole failing dimension;
  hook, authenticity, clarity, and platform-fit failures remain blocking.

## 2026-08-18 - Deterministic Low-Capability Automation

- Added a hashed per-platform run contract with fixed rule precedence,
  publish boundaries, required Skills, stage field allowlists, and provider
  input/output bounds. New preflight manifests fail when rulebook contents
  drift after planning.
- Topic planning now supports three bounded lane-specific re-search attempts.
  A scheduled platform is not dropped merely because its first candidate is
  irrelevant. Editorial fallback requires strategy, calendar, date, and
  dedupe evidence and remains explicitly labeled.
- Added platform content blueprints, factual claim ledgers, and content-depth
  plans. Unsupported numbers, invented operational history, malformed code,
  shallow content, and empty continuation promises fail before media work.
- Added a persistent asset ledger with exact and perceptual duplicate checks,
  license/source evidence, and semantic-fit evidence. Added a topic-specific
  viral cover contract and content-hash media staging.
- Compiled runs always require unified acceptance before publishing. Manual
  channels retain handoff-only states.
- The independent supervisor now checks every three minutes and may safely
  recover an interrupted uncompleted stage twice after durable reconciliation.
  Terminal work is never recreated.
- Production config and installer no longer pin a Hermes provider/model or
  silently switch providers. Edge remains the default TTS; Qwen auto-selection
  requires explicit A/B quality approval.
- Added bounded weekly cleanup of reconstructable intermediates only. Final
  works, covers, state databases, cookies, and operator handoff roots are not
  eligible.
- Architecture and acceptance details are documented in
  `docs/LOW_CAPABILITY_AUTOMATION_ARCHITECTURE.md`.

## 2026-08-18 - Production Deployment And Active-Model Canary

- Production and local full suites passed after the final active-model,
  factual-sanitization, and short-form fixes. The production suite includes
  additional server-origin regression coverage retained during reconciliation.
- A compiled isolated canary used the active Hermes model without provider or
  model flags. The first attempts exposed and fixed fenced smoke JSON,
  unsupported generated statistics, numeric titles, and a short-post/long-form
  contract mismatch. The final canary completed and created only a file draft.
- The overnight supervisor and bounded runtime-cleanup timers are active. The
  first cleanup removed only superseded render/review caches; protected final
  media and business state remained intact.
- Server runtime changes were snapshotted before reconciliation. Public main,
  local main, and production main were then aligned without discarding the
  prior local or server snapshots.
- Full deployment evidence and the remaining three-run stability boundary are
  recorded in `docs/DETERMINISTIC_AUTOMATION_DEPLOYMENT_REPORT_20260818.md`.
