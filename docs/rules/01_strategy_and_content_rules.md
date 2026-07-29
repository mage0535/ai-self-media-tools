# Strategy And Content Rules

This document is the human-readable strategy and content layer for all channels.
Machine-readable thresholds live under `config/`; executable gates live in
`content_platform/`.

## S1 Account Stage And Data Status

Every new content package must record an account stage and a strategy data
status before generation or delivery.

Allowed account stages:

- `bootstrap`: no reliable history; use channel baseline and low-frequency tests.
- `cold_start`: early account with limited data.
- `exploration`: validating lane, format, hook, and audience.
- `growth`: scaling proven lane and format signals.
- `mature`: stable lane and audience.
- `recovery`: performance or account health has declined.
- `restricted`: account has active risk; automated publishing is blocked.

Allowed data statuses:

- `sufficient`
- `partial`
- `bootstrap`
- `unavailable`

Missing analytics data is not a reason to fabricate evidence. Use `bootstrap`,
`partial`, or `unavailable`, and lower automation confidence.

## S2 Lane, Sub-Lane, And Audience

Every new content package should record:

- `primary_track`
- `sub_track`
- `target_audience`
- `user_problem`
- platform fit reason

Hot topics are not enough. The topic must fit the account lane, platform
audience, and current account stage.

## S3 Topic Scoring And Production Decision

Topic scoring is a P1 strategy gate. It informs automated production, but does
not override P0 safety, compliance, health, or postcheck rules.

The default scoring model is in `config/topic_scoring_model.json`.

Default decisions:

- `>= 70`: `auto_produce`
- `60-69`: `manual_review`
- `< 60`: `reject`

Low-score topics must not be silently auto-produced. They may only proceed with
a recorded override containing reason, operator, and approval time.

## S4 Platform Form And Publishing Cadence

Platform-specific content form, publishing count, and schedule windows must come
from the channel rulebook and current strategy evidence.

When data is incomplete, use channel baselines and record the degraded mode.
Do not invent historical performance.

## T1 Image-Text Content

Article and image-text packets must include:

- title
- summary when the platform needs one
- body
- cover plan
- visual strategy
- section image map
- SEO keywords
- GEO fields when channel-required
- tags when channel-required

Inline images must map to adjacent sections. Bottom-stacked galleries do not
satisfy this rule when inline mapping is required.

Same-day article batches on one account must differ meaningfully in at least
three dimensions: angle, title form, opening, structure, voice, visual style,
layout, length, or reading scenario.

## V1 Video Content

Video packets must include:

- title
- script
- storyboard
- scene-to-asset mapping
- cover plan
- narration or audio metadata
- subtitle metadata unless a readable card-video exception is recorded
- description and tags when channel-required

Video visuals must change with the script. One repeated background, unrelated
footage, or generic static card loops are quality failures.

Cat or animal knowledge videos must use real or verified behavior visuals that
match the narrated behavior. Cards can explain; unrelated footage cannot be the
main evidence.

## R1 Cross-Platform Reuse

Reuse is allowed only when the package records the relationship:

- `parent_content_package_id`
- `follow_up_to`
- `difference_angle`
- `recap_reason`

Cross-channel and same-channel recent dedup checks are required before
generation.
