# Domestic Content Quality Rebuild

## Goal

Replace the 2026-07-17 batch's static-card outputs with channel-specific, human-readable articles and narrated short videos. Old remote drafts or scheduled items are removed only after an exact management-page match; replacement uploads must be health-gated and postchecked.

## Channel Design

- WeChat and Baijiahao articles use a topic-specific visual family selected from case-study, process walkthrough, decision framework, or checklist. Every article opens with a concrete tension, expands the argument with examples and counterexamples, and places platform-hosted inline images immediately after the matching section.
- Kuaishou uses an evidence-first, practical microcase. The vertical video is full-bleed, has a visual/verbal/text hook in its first second, has narration and lower-third burned-in captions, and changes visual treatment every two to four seconds.
- Douyin cat knowledge uses only verified, rights-cleared real footage that matches the narrated cat behavior. It is prepared for review only while account health does not allow publish.

## Hard Gates

- No video passes if ffprobe cannot find an audio stream, a non-empty SRT, a burned-caption evidence frame, and a full-frame visual composition.
- No article passes if text length meets the channel threshold, its opening contains a hook, it has a selected template with history evidence, and its inline-image plan maps images to body sections.
- A selected template must include ranked alternatives and repetition penalties from `choose_visual_template()`.
- Upload remains behind `delivery_health_decision()` and completion requires the channel's management-page or API postcheck.

## Deletion and Recovery

The 2026-07-17 Kuaishou queued items are located by their displayed descriptions, not their manifest titles. WeChat and Baijiahao are removed only when their exact draft/article identifiers are retrieved from their current status evidence and the respective platform route confirms removal.
