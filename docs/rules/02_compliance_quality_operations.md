# Compliance, Quality, And Operations Rules

This document defines P0 delivery safety, quality gates, postcheck semantics,
feedback, and rollback behavior for all channels.

## C1 Asset Source And License

Asset verification status:

- `verified`: can be used for automated publishing.
- `pending_review`: can be staged or drafted, but cannot be automatically
  published.
- `unknown`: cannot be automatically published.
- `rejected`: cannot be drafted, scheduled, or published.

Whitelisted sources still require per-asset records. A domain whitelist is not
proof that a specific image, video, or music track is cleared for this use.

## C2 High-Risk Content

Medical, financial, legal, political, public-safety, and other high-risk content
requires manual review unless a current project rule explicitly classifies the
item as safe educational or operational commentary.

## SEC1 Secrets And Sensitive Information

Generated text, subtitles, publishing payloads, logs, attachments, and evidence
must not contain:

- API keys
- access or refresh tokens
- cookies
- session IDs
- private keys
- database passwords
- private file paths
- private backend URLs
- unredacted account or personal data

The `security_gate` must block P0 leaks and return only redacted diagnostics.

## A1 Account Health, Proxy, And Channel Availability

Domestic channel access from Hermes must use the configured domestic proxy.
International channel access must use the configured international proxy.

Account health, login state, cookie freshness, delivery health, and postcheck
evidence are channel-specific. A configured publisher is not health evidence.

## Q1 Quality Gates

Quality gates must return structured results with:

- rule reference
- failure code
- severity
- message
- remediation

Initial enhanced quality gates may run in shadow mode, but P0 safety gates are
enforced for new content.

## D1 Basic Deduplication

The first-pass deduplication gate is deterministic and checks:

- exact title duplicates
- URL duplicates
- asset hash duplicates
- cover hash duplicates
- content package duplicates
- same-account recent topic duplicates
- same-day template duplicates

Semantic, visual, and shot-level similarity checks are future enhancements and
are not P0 gates in this release.

## P1 Draft, Publish, And Postcheck State Machine

Allowed publish receipt statuses:

- `created`
- `draft_created`
- `upload_submitted`
- `platform_processing`
- `pending_review`
- `scheduled`
- `published`
- `manual_confirmation_required`
- `verification_failed`
- `publish_failed`
- `cancelled`

Rules:

- `upload_submitted` is not `published`.
- `scheduled` is not `published`.
- `draft_created` is not `published`.
- No `publish_receipt` means the item cannot be marked completed.

All production delivery must continue through the existing Pipeline,
`delivery_health_decision()`, channel Adapter, and postcheck.

## F1 Feedback And Review Memory

Published content should register review tasks at:

- 1 hour
- 24 hours
- 72 hours
- 7 days

If platform data is unavailable, record `unavailable` and the reason. Do not
invent analytics.

Strategy updater behavior is observe/suggest only. It must not automatically
change account lane, posting frequency, topic weights, or publish schedule.

## E1 Override, Audit, And Rollback

Manual overrides must include:

- reason
- operator
- approval time
- affected rule

Every Feature Flag must be independently reversible. Disabling a new P1/P2 gate
must restore old behavior without bypassing P0 safety, health, or postcheck
truthfulness.
