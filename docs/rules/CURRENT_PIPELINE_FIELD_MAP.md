# Current Pipeline Field Map

This map records how the rule system attaches to the existing workflow without
creating a bypass publisher.

## Existing Flow

```text
Store.create_job
-> Pipeline.run
-> DraftGenerator.generate
-> risk/compliance/geo/quality gate
-> Store.save_draft
-> optional local/remote staging
-> approval
-> Pipeline.publish
-> delivery_queue
-> delivery_health_decision
-> publisher Adapter
-> Store.save_delivery
```

## Rule-System Attach Points

| Stage | Existing Field | New Field |
|---|---|---|
| job create | `jobs.id`, `topic`, `platforms`, `brief_json` | `content_packages.content_package_id` |
| strategy | `draft_meta.strategy`, `draft_meta.viral_score` | `account_stage`, `strategy_data_status`, `topic_score`, `production_decision` |
| generation | `title`, `body`, `draft_meta` | `body_or_script`, `visual_strategy`, `storyboard` |
| assets | `artifacts`, `draft_meta.source_assets` | `assets`, `asset_licenses` |
| quality | `draft_meta.quality_gate` | `gate_results`, `quality_check` |
| delivery | `deliveries.status`, `external_id` | `publish_receipts.status`, `verification_level`, `evidence_ref` |
| review | `performance`, `events` | `review_tasks`, `feedback_memory` |

## Compatibility

Old `job` and `packet` dictionaries remain valid. When `content_package_v1` is
enabled, new content is wrapped in a `ContentPackage` and the legacy fields are
kept for existing formatters and publishers.

No production publisher should be called outside the existing Pipeline and
delivery health gate.
