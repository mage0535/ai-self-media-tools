# Deterministic Automation Architecture

This project does not depend on one model remembering every rule. The model fills bounded stage schemas; code owns rule precedence, state transitions, evidence, gates, retries, publishing boundaries, and receipts.

## Execution Order

1. Compile `run_contract_v1` from the current rulebook.
2. Collect real platform and cross-platform evidence.
3. Reject an irrelevant candidate and repeat lane-specific search up to three times.
4. Use an editorial-calendar fallback only when strategy source, calendar column, date, and dedupe evidence are complete.
5. Build and validate `content_blueprint_v1` before generation.
6. Send only the bounded `generate` payload to the active Hermes model.
7. Validate the factual claim ledger and content-depth plan before creating media.
8. Persist source, license, semantic fit, content hash, and perceptual hash for every visual.
9. Render from `scene_manifest.json`, then inspect the encoded artifact.
10. Validate the topic-specific cover, unified acceptance, delivery health, and platform boundary.
11. Publish or hand off through one adapter and persist a truthful receipt.
12. Report each stage; the independent supervisor reconciles stale state and performs at most two safe recoveries.

## Rule Precedence

1. Global hard gates.
2. Platform publish/manual-handoff boundary.
3. Current approval and run state.
4. Validated channel rulebook policy.
5. Validated runtime configuration.
6. Legacy compatibility defaults.

No environment variable, CLI switch, Skill, template, or model response can override a higher level. Unsupported channels remain pre-onboarding and cannot publish.

## Evidence Contracts

- `run_contract`: rulebook version/hash, platform rules, skills, stage fields, input bounds, publish boundary.
- `platform_source_matrix`: collected sources, timestamps, candidate sample, native-source proof.
- `content_blueprint`: platform, audience, pain, goal, format, style, evidence and functional mascot roles.
- `claim_ledger`: claim text, source URL, evidence path and verification state.
- `content_depth_plan`: three knowledge points, case/evidence, steps, counterexample, takeaway, interaction and optional series plan.
- `asset_provenance`: actual file, source/generation evidence, license, semantic score/reason/tags.
- `scene_manifest`: the only narration, subtitle, asset, timing and motion timeline.
- `cover_quality_evidence`: narrative hook, conflict/payoff, focal subjects, content match, layout and safe zone.
- acceptance and publish receipts: actual artifact and platform evidence, never inferred success.

## Recovery Semantics

- Policy/content failures do not retry automatically.
- Bounded infrastructure failures retry once in the batch.
- A stale interrupted stage is reconciled against database and delivery receipts before recovery.
- The supervisor may recover an uncompleted stage twice. A third interruption is terminal and action-required.
- Terminal or published/handoff-ready work is never recreated.

## Provider Policy

- Generator provider/model values are empty by default, so the active Hermes model is used.
- Silent provider fallback is disabled in production configuration.
- Edge TTS remains the production default. Qwen TTS can be selected by `auto` only after an explicit A/B quality approval.

## Release Acceptance

- Full tests and project/privacy audit pass.
- The runtime Git revision matches the audited deployed revision.
- Supervisor and cleanup timers are enabled.
- One isolated compiled canary completes with all evidence files and no publish action.
- Three consecutive scheduled runs finish without code edits or manual recovery before the workflow is called stable.
