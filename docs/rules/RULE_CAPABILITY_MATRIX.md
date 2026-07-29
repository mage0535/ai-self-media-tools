# Rule Capability Matrix

| Rule | Capability | Status | Implementation |
|---|---|---|---|
| S1 | Account stage and data status | Implemented | `content_platform.niche_scorer.AccountProfiler` |
| S3 | Topic scoring and production decision | Implemented | `content_platform.niche_scorer.TopicScorer`, `config/topic_scoring_model.json` |
| C1 | Asset source and license gate | Implemented | `content_platform.asset_license.validate_asset_licenses` |
| SEC1 | Secret and sensitive payload gate | Implemented | `content_platform.security_gate` |
| Q1 | Article/video structure gates | Implemented | `content_platform.media_quality` |
| D1 | Basic deterministic dedup | Implemented | `content_platform.duplication.check_exact_duplicates` |
| P1 | Publish receipt state machine | Implemented | `content_platform.models.PublishReceipt`, `Store.save_publish_receipt` |
| F1 | Review task registration | Implemented | `content_platform.performance_collector.register_review_tasks` |
| F1 | Feedback memory | Implemented | `Store.save_feedback_memory`, `content_platform.feedback_memory` |
| E1 | Strategy suggestions only | Implemented | `content_platform.strategy_updater` |

## Current Activation

P0 gates are designed for enforce mode on new content:

- `security_gate`
- `asset_license_gate`
- delivery health
- proxy policy
- publish receipt truthfulness

P1/P2 gates start in shadow/observe mode:

- topic scoring
- enhanced quality checks
- deterministic dedup
- strategy updater

## Non-Goals In This Release

- LLM semantic consistency hard gates.
- Multimodal image-section or video-narration hard gates.
- Semantic, visual, or shot-level similarity dedup.
- Automatic lane, frequency, or strategy-weight mutation.
