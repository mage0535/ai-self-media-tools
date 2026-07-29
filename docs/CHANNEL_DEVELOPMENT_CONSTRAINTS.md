# Channel Development Constraints

This document is mandatory for every new channel, channel repair, uploader change, or Local Ops Lab workflow update.

Every channel workflow must also follow `docs/CONTENT_OPERATIONS_QUALITY_DIRECTIVE.md`. That directive is the cross-channel human-experience quality baseline for operations, topic selection, content generation, media creation, review, and reporting.

Every channel content or promotion job must also load `docs/CHANNEL_CONTENT_OPERATIONS_PLAYBOOK.md` and the machine-readable `config/channel_content_rulebook.json` before strategy, generation, draft, publish, or review work. These files define channel lane fit, content types, Hermes tool requirements, delivery semantics, and feedback-loop obligations.

Every new content package must also follow the unified rule documents in `docs/rules/` and the machine-readable rule configs in `config/`. P0 rule failures for new content are enforced for security, account health, delivery health, proxy correctness, asset license status, and publish-receipt truthfulness. P1/P2 strategy, quality, and deterministic dedup gates may run in shadow mode until current channel evidence supports enforcement.

## Non-Negotiable Rules

- Do not call `build_publisher(...).deliver(...)` from a new production path unless `delivery_health_decision(platform, config, "publish")` has passed in the same path.
- Prefer `Pipeline.create -> Pipeline.run -> Pipeline.stage_drafts/publish -> process_delivery_queue` for channel work. The pipeline is the canonical health-gated path.
- New production content must carry a `ContentPackage` record when `content_package_v1` is enabled. Old `job` / `packet` dictionaries remain compatible, but regenerated, redistributed, or newly published content must be wrapped and audited through the content package.
- P0 gates must return structured failure records with rule reference, severity, message, and remediation. Do not treat a generic "validation failed" string as sufficient evidence.
- Unknown or rejected asset license status blocks automatic public publishing. `pending_review` assets may remain draft/manual-review only; they must not enter unattended public publishing.
- A delivery result without `publish_receipt` evidence must not be marked `published` or `completed`. Upload submission, local stage, draft creation, scheduled state, and handoff-pending state are distinct from published.
- Treat `stage` as local draft preparation by default. Local stage status is `staged`; it must never count as publish success.
- Do not enable remote staging unless `delivery.allow_remote_stage=true` and the platform is explicitly listed in `delivery.remote_stage_platforms`.
- Domestic channels must fail closed when current health evidence is absent, malformed, stale, or blocking. A configured publisher route is not health evidence.
- Hermes must never access a channel through the wrong egress class. Domestic channel login, cookie refresh, upload, draft, schedule, postcheck, analytics, trend scraping, and crawler probes must use `CN_PROXY`; international channel access must use `US_PROXY`. If the required proxy is missing, unreachable, or the observed egress region does not match the channel class, block before login or upload.
- Douyin auth refresh must prefer the CN-host noVNC real-Chrome profile path when normal Hermes QR login is unstable. Headless QR generation, static QR screenshots, or local multi-hop proxy Chrome sessions are not sufficient success evidence by themselves; the workflow must export storage state from the logged-in CN-host profile and keep `<social-auto-upload-home>/cookies/douyin_uploader/main.json` as the canonical account file.
- `delivery_health.allow_unknown_health` is only for explicit dry-run or local-only exception work. Do not use it for live or scheduled domestic publishing.
- `usable_with_postcheck_required` is not complete. It must remain `handoff_pending` / job `partial` until a management-page or API postcheck proves the scheduled/drafted item exists.
- For platforms with daily limits, use the platform/account timezone, not UTC date slicing. Douyin defaults to `Asia/Shanghai`.
- Promotion rotation is not publishing. Files such as `today_promo.json`, generated outbox JSON, and post-processing logs only prove strategy or draft preparation; they must never be reported as platform delivery.
- Domestic article/community API routes default to remote draft or review submission. Public publish calls require an explicit current approval, a channel health pass, and a post-publish URL/state verification.
- A public URL is the only success evidence for `published`. A draft id, audit id, platform draft state, or management-page draft row must be reported as `drafted` or `handoff_pending`, not `published`.
- Promotion content must match the account lane. Technical/GitHub promotion is blocked on pet/entertainment accounts such as Douyin cat-healing lanes, even when the uploader is healthy.
- Keep screenshots, cookies, browser profiles, health reports, and platform evidence in ignored runtime paths only. Do not place media evidence in the repository root.
- Never commit, print, or document cookie/API/key plaintext.

## Required Workflow For Each Channel

1. Strategy: run channel-specific audience, account direction, niche, trend, and topic analysis before generation.
   The runner must record which Hermes strategy source and content tools were loaded. If required tools are unavailable, the channel must be marked blocked or handoff-pending with the missing tool.
2. Dedup: check cross-channel and same-channel recent topics/copy before generating content.
3. Content: generate channel-specific copy and media according to that channel's strategy and template selection.
4. Quality: verify content completeness, visual/content consistency, subtitle placement, voice quality, cover, required declarations, and required page fields.
5. Network: verify the required channel proxy before any Hermes-side login, cookie refresh, uploader call, trend crawl, analytics probe, or postcheck. Domestic channels require `CN_PROXY`; international channels require `US_PROXY`.
   For Douyin, if Hermes browser access through `CN_PROXY` or a local multi-hop proxy shows login loops, system-busy errors, or QR sessions that do not bind, switch to the CN-host noVNC real-Chrome recovery path and preserve the resulting storage-state JSON without printing secrets.
6. Health: load current delivery health state before any upload or scheduled submission.
7. Stage: write local review/draft packets first unless the platform has an explicitly verified safe remote-stage route.
8. Publish: only submit when health allows publish and the channel-specific required fields are set.
9. Postcheck: verify the platform management page/API shows the expected title, type, schedule time, and status. Do not accept uploader return code alone.
10. Feedback: when a platform item is submitted or drafted, create/update a metrics row with account, post or draft id, URL if public, 1h and 24h follow-up slots, hook, value, objections, and next action.
11. Evidence: save manifest, status JSON, logs, screenshots, and failure reasons under ignored runtime paths.
12. Handoff: update `docs/CONTINUOUS_DEVELOPMENT.md` when channel behavior, gates, status semantics, or validation evidence changes.

## Promotion And API Publishing Rules

- Daily project rotation must stop at strategy unless a verified publisher path executes. A log line such as `Published: 0` means no platform delivery happened.
- For domestic API channels such as Juejin and Zhihu, separate `draft` and `publish` functions. Do not let a draft workflow call a public publish endpoint as a side effect.
- Juejin draft success requires both draft create/update success and a draft-list or draft-detail API postcheck. A later public publish may still be audit-pending; report that state honestly.
- Zhihu draft success uses the draft detail endpoint, not the public article endpoint. A public article endpoint returning 404 for a draft is not proof of failure.
- Weibo, SegmentFault, Xiaohongshu, Douyin, Bilibili, and other channels must be reported as blocked when cookies, uploader routes, account health, lane fit, or current postcheck evidence are missing.
- Douyin, Video Channels (`shipinhao`), and Xiaohongshu/Rednote are currently semi-automatic manual-handoff platforms. The pipeline must generate a complete local review package for user publishing and must not call a live uploader or claim platform draft/publish success for these platforms.
- Existing paused cron jobs for this project remain paused unless the user explicitly asks to restore them. Fixing rules or adding manual scripts is not permission to reactivate cron.

## Human Quality Gates

- Article/image-text packets must contain a concrete opening hook, a real case or conflict, at least five developed sections, a reader payoff, an actionable checklist, and section-level inline-image mapping. WeChat articles should be long-form; Toutiao/Zhihu/Juejin onboarding articles must be fully developed, not short video copy reused as image-text.
- Article/image-text packets must include a pre-generation strategy brief that records target user, channel lane, topic basis, click reason, reader payoff, chosen structure, content form, and same-day differentiation.
- Article covers and inline illustrations must be selected per topic. Do not reuse one visual template or one cover style across a same-day channel batch unless the ops report records why it remains the best fit after recent-template penalties.
- Article covers must record visual subject, topic alignment, mobile readability, visual hierarchy, and template family. Inline images must map to adjacent sections; bottom-stacked or gallery-only images do not satisfy inline mapping.
- Video packets must be at least 40 seconds unless a channel-specific current ops report explicitly sets a different minimum and explains why. A short-video upload must have audible narration, burned-in lower-third subtitles, readable font size, no overflow, and no center-screen captions blocking the subject.
- Video packets must include a planning table: theme, target audience, user pain, first-three-second hook, core message, storyboard, voiceover, subtitle plan, music plan, ending CTA, duration, and scene-to-content mapping.
- Video visuals must change with the script. A valid video packet needs scene-by-scene script-to-visual alignment, at least eight distinct scenes, at least four unique source assets, and evidence that each asset matches the narrated beat. Repeating one clip or one static template with changed subtitles is a quality failure.
- Video Channels packets must include a same-day Kuaishou dedupe check. A valid Video Channels strategy brief must explain its WeChat-ecosystem context, target share/save reason, retention problem addressed, and template-family choice. Reusing Kuaishou topics, scripts, template families, or broad-feed pacing without an explicit current strategy reason is a quality failure.
- Same-day or same-batch content must differ in at least three meaningful dimensions. Changing only title, text color, palette, background, or one decorative image is not meaningful differentiation.
- Platform adaptation must be checked before submission. For Kuaishou, descriptions must not duplicate hashtag topics when uploader tags are appended, and the verified topic limit must be respected.
- Cat/animal knowledge videos must use real or verified animal behavior visuals that match the narrated behavior. Generated art or unrelated stock footage is allowed only as a supplemental card, not as the main evidence.
- Any packet that fails `content_platform.media_quality` must remain local-only. Do not upload, draft, schedule, or mark complete when the quality gate fails, even if the platform uploader itself is healthy.

## Acceptance Criteria For A New Or Repaired Channel

- A regression test proves the health gate blocks an unhealthy state before any uploader subprocess/API is invoked.
- A regression test proves `stage` cannot be mistaken for `publish` success.
- A regression test proves postcheck-required channels are not marked complete before postcheck.
- `python -m pytest -q` passes.
- `python -m content_platform project-audit` returns `ok: true`.
- The channel has a documented validation target: draft list, scheduled list, content-management page, API status, or equivalent.
- The channel has documented failure states and recovery steps without exposing secrets.

## Known Safe Status Semantics

- `staged`: local draft/review packet only; not uploaded and not publish success.
- `drafted`: remote draft or scheduled item accepted by a publisher route that does not require extra postcheck.
- `handoff_pending`: submitted or routed, but postcheck/user handoff is still required; not final success.
- `published`: publish confirmed by a trusted API or verified platform state.
- `blocked`: health, policy, certification, route, or account state prevents delivery.

## Bypass Review Checklist

Before adding a new script, CLI command, admin action, MCP tool, scheduler, or worker:

- Does it call a publisher directly?
- Does it process `stage` and `publish` as distinct actions?
- Does it read `CONTENT_PLATFORM_DELIVERY_HEALTH_FILE` or configured health state before upload?
- Does it fail closed for domestic channels without current evidence?
- Does it preserve ignored runtime boundaries for evidence and credentials?
- Does it leave a machine-checkable test for the above?
