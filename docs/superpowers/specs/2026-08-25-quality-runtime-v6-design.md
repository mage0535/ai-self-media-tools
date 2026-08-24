# Quality Runtime V6 Design

## Goal

Deliver a single-source, model-agnostic `ai-self-media-tools` runtime that Hermes can operate with its current active model, including lower-capability models, while deterministic code owns evidence, routing, retries, media contracts, publishing boundaries, reporting, and acceptance.

## Development Roles

- Sol controller: architecture, task packets, integration, server deployment, rollback, and final acceptance.
- Luna builder: bounded TDD changes in explicitly owned files. It cannot deploy or edit production state.
- Terra reviewer: read-only specification and quality review. It cannot modify production.

These model names are development-only and must not appear in runtime configuration. Production generation always follows Hermes' active model.

## Runtime Architecture

The runtime executes one platform at a time:

`schedule -> platform evidence -> topic selection -> content blueprint -> compact platform context -> capability DAG -> generation -> assets/render -> artifact gates -> delivery -> postcheck -> publication ledger -> metrics`

Every stage writes a checkpoint and a structured event. A required-stage failure stops the batch. Transient infrastructure failures retry the current stage at most twice; content, evidence, and policy failures do not retry without new inputs.

## Context Compilation

The provider receives only the current platform, format, stage, selected rule IDs, selected capabilities, evidence summaries, claim ledger, and output contract. Full Skill files, unrelated platform rules, full capability inventories, private paths, and repeated examples are excluded. Provider input is bounded and hashed. Hermes model/provider flags remain empty unless an operator explicitly configures them outside automated workflow mode.

## Capability Contract

One registry replaces the old split between tool groups and capability routing. Every executable capability defines `id`, `tool_group`, `kind`, `stage`, `probe`, `adapter`, `input_contract`, `output_contract`, `quality_gate`, `fallback_chain`, `required_policy`, and `license_policy`.

Runtime evidence uses distinct states: `planned`, `consulted`, `executed`, `artifact_verified`, and `skipped`. Inventory-only entries are never presented as executed tools. Methodology is consulted only and records exact rule IDs and affected outputs.

## Platform Intelligence

Platform-native official topics, activities, keywords, and same-lane works are preferred. An irrelevant candidate triggers bounded same-platform recapture instead of dropping the platform. Cross-platform evidence is contextual only and never inherits native identity. Strategy-allowed evergreen fallback remains explicitly labeled.

## Media Contracts

Article and video contracts are evaluated before generation and again against actual artifacts. Juejin requires a public cover plus three public inline images mapped to sections. Video uses `scene_manifest.json` as the only timeline and verifies actual encoded motion, subtitles, audio, BGM, scene assets, and final media probes. Commercial production BGM rejects NC/ND licenses.

## Delivery And Feedback

Delivery health is refreshed before queue admission. Draft, scheduled, review, handoff, and published remain distinct. Xiaohongshu is permanently manual-handoff-only. Verified publication identities create idempotent 1h/24h/72h metric windows; insufficient data is never written as zero.

## Observability

A Chinese reporter consumes structured events and reports the platform, stage, evidence, candidate decisions, selected/executed capabilities, error, repair, gate results, and receipt. The reporter is independent from the worker and never mutates content state.

## Release Boundary

No timer is enabled until full tests, privacy/license audits, 12 serial platform canaries, active-model and weak-model runs, rollback rehearsal, and source/release SHA consistency pass. Two consecutive shadow batches must complete without code edits or manual recovery before production activation.

