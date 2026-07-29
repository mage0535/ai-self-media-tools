# Channel Content Operations Playbook

This playbook summarizes the channel rules confirmed on 2026-07-18. It applies to Codex Local Ops Lab work, Hermes promo work, and future channel development.

## Mandatory Sequence

Every channel job must run this sequence. Skipping a step means the job is incomplete.

1. Load `config/channel_content_rulebook.json`.
2. Load the current Hermes operating strategy, such as `hermes://promo/today_promo.json` or the channel-specific ops report.
3. Collect current channel evidence: account lane, recent content, current health, cookie status, proxy status, and recent publish outcomes.
4. Analyze at least 10 same-lane hot items when platform access allows it. If access is blocked, record the blocker and use the best available same-lane evidence.
5. Check account lane fit before generation. A working uploader is not permission to publish off-lane content.
6. Run cross-channel and same-channel dedupe. Default same-platform project-promotion repeat interval is seven days.
7. Generate a channel-specific strategy brief before content generation.
8. Generate content using the channel's required Hermes tools and content-generation skills.
9. Run quality review: hook, value, completeness, visual match, template diversity, voice/subtitle quality, platform fields, and compliance.
10. Run delivery health and auth checks immediately before platform submission.
11. Draft, schedule, or publish according to the channel policy.
12. Postcheck the platform state using a management page or API. Uploader return code alone is not enough.
13. Write metrics feedback: `account, post_id, url, t_1h, t_24h, hook, value, objections[], next_action`.
14. Save evidence and update continuous-development notes when a rule, route, or status meaning changes.

## Global Rules

- Communicate with the user in Chinese. Code and paths may remain English.
- Do not print, commit, or document cookie/API/key plaintext.
- Zero-cost tools are preferred. Do not change `model.provider` or `model.default`.
- Hermes domestic-channel traffic must use `socks5h://127.0.0.1:1080`.
- Paused ai-self-media cron jobs remain paused unless the user explicitly asks to restore them.
- `today_promo.json`, outbox files, generated text, and post-processing logs are strategy or draft evidence only. They are not publishing evidence.
- Domestic article/community channels default to draft or review state. Public publication requires explicit current approval plus postcheck.
- `published` requires a public URL or trusted API state proving public visibility.
- `drafted` requires a platform draft id plus draft-list or draft-detail postcheck.

## Channel Content Map

| Channel | Lane | Content Types | Default Delivery | Hard Gates |
|---|---|---|---|---|
| Douyin | Pet healing | Edited pet short video, cat knowledge, knowledge image video | One selected work only when health allows | No GitHub/tech promotion; real cat/animal behavior visuals; lower-third subtitles |
| Kuaishou | Mixed AI-efficiency and selected pet | Edited short video, microcase video | Scheduled/drafted when supported | No single static template batch; audible voice; readable subtitles; no empty template area; exact schedule must be management-page postchecked |
| Video Channels | AI-efficiency/open-source | Edited short video, microcase video | Draft/schedule with upload-page health | Do not reauth if publish-entry probe reaches `post/create` with `file_inputs=1`; must use an independent WeChat-ecosystem strategy and cannot reuse Kuaishou topics/templates without explicit strategy proof |
| WeChat Official Account | AI-efficiency/open-source | Long-form article, image-text article | Draft box first | 1200-3000 words when article; at least 3 inline relevant images; CSS inline |
| Baijiahao | AI-efficiency/open-source | Image-text article, article, occasional video | Scheduled/drafted with backend postcheck | Inline images mapped to sections; no bottom-stacked gallery-only images |
| Xiaohongshu | AI-efficiency/open-source | Social note, image-text note | Blocked during account recovery | No pure-color text cards; no obvious AI-generated main visual; oral copy |
| Juejin | AI-efficiency/open-source | Technical longform, architecture case | Draft first | Engineering angle; draft create/update plus draft-list postcheck |
| Zhihu | AI-efficiency/open-source | Reasoned longform, tradeoff analysis | Draft first | Use `/api/articles/{id}/draft` for draft proof; public 404 for draft is not failure |
| CSDN | AI-efficiency/open-source | Tutorial, step-by-step technical article | Blocked until route verified | Commands, prerequisites, failure handling |
| Bilibili | AI-efficiency/open-source | Tutorial video, edited short video | Draft/schedule after health | Subtitles, voiceover, scene-to-script match |
| Weibo | AI-efficiency/open-source | Micro post | Blocked until cookie reauth | Concise hook; no long article dump |
| SegmentFault | AI-efficiency/open-source | Technical article | Blocked until cookie/uploader exists | Technical depth; not duplicate of Juejin/Zhihu |
| TikTok | International AI-efficiency | Edited short video | AiToEarn Intl or verified uploader | Localized English hook; no Chinese copy repost |
| YouTube | International AI-efficiency | Shorts, short tutorial | AiToEarn Intl or verified route | Searchable title, captions, public URL/API state |

## Content Generation Standards

### Article And Image-Text

- Text version should normally be 1200-3000 Chinese characters/words equivalent for domestic article channels, adjusted by platform and strategy.
- Use at least three content-relevant images when an article/image-text format requires visuals.
- Images must be placed near the section they support; bottom-stacked galleries do not satisfy image-text matching.
- Do not reuse one template or cover style across a same-day channel batch unless the ops report explicitly justifies it.
- Each article needs a hook, concrete case or conflict, developed sections, reader payoff, checklist or action path, and objections/limitations when relevant.

### Knowledge Cards And Visual Text

- Any cover, inline image, carousel card, poster, infographic, or card-based video must load Hermes skill `hermes_skill:content/knowledge-card-designer` before generation.
- Card design starts with type selection: cover, knowledge-summary, carousel, viewpoint, step tutorial, emotional companion, commercial information, or science explainer.
- Use the combined rule set from the Hermes knowledge-card skill and the 2026-07-18 Douyin reference note: hook first, one micro-point per page, typography as visual structure, and page-by-page progression.
- Use no more than three colors plus black, white, and gray. Typography hierarchy must be at least 4:2:1, with title 48-72px, body 18-24px, and label 9-12px as the default scale.
- Text can be horizontal, vertical, diagonal, rotated, staggered, split-screen, timeline, card-stack, or magazine-cover style when the topic supports it. The layout must be selected by the current strategy and content type, not reused by habit.
- Every image or visual symbol must explain, prove, compare, locate, or emotionally reinforce the nearby content. Meaningless decoration is a hard failure.
- Four-side padding must be at least 30px, preferably 40px. Line height should be 1.6-1.8 times the font size, and text must stay mobile-readable and within frame.
- Each card batch must pass readability, attraction, information density, share/save value, visual match, and mobile-boundary checks before upload.

### Video

- Knowledge and short-video items should usually be 40-100 seconds unless current strategy gives a reason to change duration.
- Every video needs a planning table: theme, target audience, pain, first-three-second hook, message, storyboard, voiceover, subtitle plan, music plan, CTA, duration, and scene mapping.
- Voiceover must sound human: pauses, emotion changes, breath intervals, and natural pacing.
- Subtitles default to lower third, readable font, no overflow, and no main-subject blockage.
- Visuals must change with narration. Repeating one clip or one card with new subtitles is a quality failure.

### Kuaishou Scheduling

- For Kuaishou same-day multi-work batches, do not trust upload-page one-click scheduling for exact operations-selected times.
- Reliable flow: upload the work to pending, open it from `works management -> pending -> edit work`, type the exact strategy datetime into the visible date-time input with real keyboard events, save, and re-open the pending list.
- Completion requires the management page to show each expected work and exact scheduled time. Uploader return code, local manifest, or `submitted=true` is not enough.

### Douyin Weekly Mix

- Douyin pet-healing output must preserve the default weekly mix of 2 cat-knowledge/original works plus 5 TikTok-hot localized rewrite/repost works unless the current ops report explicitly overrides it.
- When a task requests fewer than seven Douyin candidates, the candidate pool must still include both lines and should prefer the line with the larger remaining weekly quota.
- TikTok-derived candidates must be localized, rewritten, re-edited, deduped, voice/subtitle adapted, and source/compliance checked. A raw download, simple subtitle change, crop, filter, or watermark removal is not enough.

## Hermes Tool Invocation Contract

Before content generation, the runner must record which Hermes tools were used or why they were unavailable:

- Strategy source: `today_promo.json`, channel ops report, account-history report, or niche strategy file.
- Hot evidence: platform search/API/Playwright/Scrapling/anti-crawl browser output, minimum 10 items when available.
- Content tools: channel-specific content generation skill, humanizer, SEO/GEO optimizer, image selector, video pipeline, TTS, subtitle renderer, uploader.
- Quality tools: `content_platform.media_quality`, channel-specific visual/content gate, and platform field checklist.
- Delivery tools: health probe, uploader/API route, postcheck route, evidence writer.
- Feedback tools: metrics review writer and unresolved-objections reader.

If any required tool is unavailable, the job must mark the channel `blocked` or `handoff_pending` with the missing tool and shortest next action.

## Post-Run Review

Every run must produce a channel table:

- Result: public, draft/review, blocked, or failed.
- Evidence: URL, draft id, API state, screenshot, management-page row, or error.
- Topic and hook used.
- Content type and template family.
- Tool chain used.
- 1h and 24h review slots.
- Objections or questions to feed into the next script.

Do not claim a channel is complete because content was generated locally. Completion depends on the platform state required by that channel's policy.
