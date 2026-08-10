# Content Operations Quality Directive

This directive is mandatory for every image-text article, short video, long video, channel workflow, and Local Ops Lab run.

## Core Standard

Generated content is for real users, not for AI, crawlers, or machine-only scoring. A packet is publishable only when a real user would have a reason to click, continue reading or watching, understand the value, and see a clear match between title, cover, body, narration, subtitles, and visuals.

Do not publish content only because it was generated, formatted correctly, keyword-complete, or long enough. Low-value, repetitive, template-only, unrelated, or mechanically padded content must be rejected and regenerated.

## Required Pre-Generation Strategy

Before generating each channel item, record:

- Target user and user pain.
- Channel lane, account positioning, and current topic basis.
- Click reason and viewer or reader payoff.
- Best content form for this platform and topic.
- How title, cover, body, images, video scenes, subtitles, and narration work together.
- Recent trend, search, account-history, or competitor evidence used for the topic.
- Same-day differentiation from other items.
- Account lane fit. Technical, GitHub, AI-efficiency, pet, entertainment, and lifestyle lanes must not be mixed just because a channel has a working uploader.

Batch generation without this strategy record is not allowed.

## Operations Evidence Gate

Each operating date must begin with `python scripts/ops_run.py <YYYYMMDD> --init`. Before generation, record each platform choice with `--platform`, `--topic`, and a stable `--direction`.

- A direction cannot be reused inside the configured lookback window, even when the title text differs.
- A follow-up is allowed only when `--follow-up-to`, `--difference-angle`, and `--recap-reason` are all recorded.
- The existing `check_platform_topic_independence.py` gate also reads the date-scoped direction register and rejects an invalid or manually duplicated register.
- Before a publisher handoff, run `python scripts/verify_video_artifact.py <final.mp4> --manifest <render_manifest.json> --platform <platform>`. The result must be retained in the render manifest.
- `python scripts/validate_channel_rulebook.py` now checks the executable operations-policy facts against the public operations policy contract. A mismatch is a release blocker.

## Promotion Content Rules

- Project promotion must be a small share of channel output by default. Unless a current strategy says otherwise, keep direct GitHub/project promotion at or below 25 percent of a channel's planned content and avoid repeating it within seven days on the same platform.
- A promotion item must be adapted to the platform, not copied across platforms. Juejin should emphasize engineering implementation and code/architecture implications. Zhihu should emphasize reasoning, tradeoffs, and decision criteria. WeChat should use a complete article structure and real illustrative assets. Short-video pet lanes should not receive technical project promotion.
- Promotion content must include a real reader hook, a concrete use case or conflict, the project value, realistic objections or limitations, and a clear next action. A repo name plus generic benefits is not sufficient.
- Draft creation is not public success. When a domestic channel is draft-first, report the draft id or backend link as draft evidence and wait for explicit approval or platform audit before claiming publication.
- Every drafted or published promotion item must write a feedback row with hook, value promise, objections list, and 1h/24h follow-up fields so the next topic can use actual audience response.

## Image-Text Rules

- Articles must use a structure chosen for the topic, not one fixed template. Valid structures include problem-cause-solution, case-breakdown-method, checklist-steps-cautions, myth-correction-action, story-conflict-turning point-insight, and trend-background-impact-response.
- Same-day articles on one channel must differ in at least three dimensions: angle, title form, opening style, structure, voice, emotional tone, visual style, layout, length, or reading scenario.
- Covers must have a clear visual subject, mobile readability, content alignment, visual hierarchy, and a template family chosen for the article type. A cover is not just the title pasted on a background.
- Inline images must map to specific sections and explain, prove, or emotionally reinforce the adjacent text. Gallery-only images or bottom-stacked images are not acceptable when inline images are required.
- Articles must avoid filler, repeated claims, empty slogans, and title promises that the body cannot deliver.

## Knowledge Card Design Rules

These rules apply to covers, inline knowledge cards, carousel cards, image-text notes, and knowledge-card videos on every channel.

- Load and follow Hermes skill `hermes_skill:content/knowledge-card-designer` whenever a knowledge card, cover card, image-text card, infographic, poster, or card-based video is generated.
- Before card generation, classify the card as cover, knowledge-summary, carousel, viewpoint, step tutorial, emotional companion, commercial information, or science explainer. The selected type must match the current channel strategy and topic.
- Use at most three colors: primary, secondary, and accent. All remaining surfaces and text must use black, white, or gray. Accent color is only for title keywords, core numbers, CTA, sequence markers, or icons.
- Maintain a clear 4:2:1 typography hierarchy. Default title size is 48-72px, body size is 18-24px, and labels are 9-12px unless a platform-specific renderer requires equivalent scaling.
- Four-side padding must be at least 30px, preferably 40px for card images. Line height should be 1.6-1.8 times the font size.
- Text composition must be designed, not dumped. Allowed structures include horizontal, vertical, diagonal, rotated, staggered, split-screen, timeline, card-stack, magazine-cover, and visual-anchor layouts.
- Use the reference pattern from the Douyin design note analyzed on 2026-07-18: hook cover, one micro-knowledge point per page, strong visual hierarchy, changing text groups, and page-by-page progression.
- Every card must have a useful visual subject: topic-matched photo, platform screenshot, icon, chart, behavior frame, geometric signal, or process diagram. Decoration without information value must be deleted.
- If a topic needs more than one idea, split it into a carousel or card-video sequence. Do not make a single crowded card.
- Each generated card must pass a self-check for readability, attraction, information density, share/save value, visual match, and mobile-safe text boundaries.

## Video Rules

- Douyin, Kuaishou, Shipinhao, TikTok, and YouTube Shorts handoffs must be no more than 60 seconds. A longer video belongs to a separately declared long-form plan, not a short-video exception.
- Every video needs a planning table with theme, target audience, user pain, first-three-second hook, core message, storyboard, voiceover, subtitle plan, music or sound design, ending CTA, duration, and scene-to-content mapping.
- The first three seconds must establish a clear viewing reason: problem, conflict, result, evidence, or strong curiosity.
- Every scene must have a purpose and must correspond to the current narration or subtitle. Random scenery, unrelated people, abstract backgrounds, or one image recolored repeatedly are hard failures.
- Same-batch videos must differ in topic angle, structure, opening, pace, visual type, motion, subtitle style, music, color, or expression. Changing only text, color, title, or background is not enough.
- Voiceover must have human pacing, pauses, emotion cues, and natural breath intervals. Robotic single-take narration is a quality failure.
- Subtitles must be readable, within frame, and placed so they do not block the main subject. Lower-third subtitles are the default unless a readable-card video strategy explicitly replaces subtitles.
- Vertical short-video renders and their subtitle specification must both be 1080x1920. Card titles must be meaningful content, never `Scene N`; final output must include measurable frame movement, not only an animation claim in source code.

## Douyin Rules

- Weekly Douyin mix defaults to two knowledge/original or deeply structured items and five compliant rewrites of current same-lane popular TikTok videos, unless the current ops report changes the ratio.
- When fewer than seven Douyin candidates are requested, do not collapse the plan into one line. Include both cat-knowledge/original and TikTok-hot localized rewrite/repost candidates, then let the user select the single best item when daily limit applies.
- TikTok-derived content must be rewritten, re-edited, localized for Douyin users, supplemented with useful context, and source/compliance checked. Downloading, changing music, changing aspect ratio, adding simple subtitles, removing a watermark, or adding filters is not enough.
- Animal or cat knowledge videos must use real or verified behavior visuals that match the narrated behavior.

## Kuaishou Rules

- Kuaishou videos must not reuse one static template across a batch.
- Kuaishou upload packets must respect platform topic limits. Do not put hashtags in the description when the uploader appends topic tags; keep appended tags within the verified platform limit.
- Prefer the platform's verified high-activity one-click scheduling when available, and always preserve postcheck evidence from the management page.

## Quality Review

Every item needs both pre-generation and post-generation review evidence:

- Strategy review: channel fit, user value, trend or search basis, dedupe, visual plan, compliance and copyright risk.
- Content review: title promise, hook, information density, structure, concrete value, lack of filler, and same-day differentiation.
- Visual review: title-cover-body or narration-scene-subtitle consistency, mobile readability, no unrelated visuals, no repeated low-value template.
- Platform review: declarations, cover, schedule, tags, required fields, and management-page/API postcheck.
- Network review: Hermes-side domestic channel access must use `CN_PROXY`; Hermes-side international channel access must use `US_PROXY`. Login or upload from the wrong egress class is a hard operational failure because it can invalidate cookies, trigger platform risk controls, or poison account health signals.

Any hard failure must include a concrete rejection reason and requires regeneration, not minor recoloring, title swapping, or replacing one unrelated image.
