# Production Runtime V8 Decisions

## D1: Immutable code, mutable private state

- Code is loaded only from the immutable `$CURRENT_RELEASE` symlink.
- Config is loaded only from `$PRIVATE_RUNTIME/config.json` in production.
- Data and SQLite state live only under `$SHARED_DATA`.
- Release directories must never own production databases, cookies, credentials, or mutable job data.

## D2: Hermes is a content worker, not the safety controller

- Hermes may fill bounded content fields using its current active model.
- Deterministic code owns tool selection, state transitions, retries, gates, and delivery policy.
- Hermes may not clear locks with SQL, rewrite production state, or run dirty-checkout modules.

## D3: All capabilities are discoverable; only applicable capabilities execute

- Capability inventory includes tools, Skills, MCP, scripts, providers, templates, renderers, gates, and publishers.
- Control-plane capabilities do not execute inside content DAGs.
- Selected required capabilities must reach verified execution states.
- Skipped capabilities must record a reason.

## D4: Platform completion means verified deliverable completion

- Text completion is not platform completion.
- `review_required` requires the complete platform artifact contract.
- `approved` requires complete artifacts plus explicit approval.
- `drafted`, `scheduled`, and `published` require platform postcheck evidence.

## D5: Fail early and resume locally

- Account, source, evidence, provider, and delivery checks occur before model generation.
- Images, TTS, BGM, shots, and final media use independent signed checkpoints.
- A failed shot is retried immediately and stops the platform before unrelated expensive work continues.

## D6: Quality proof and performance proof are separate

- Artifact quality can be proven before publishing.
- Account performance improvement requires real publication identity plus 1h/24h/72h metrics.
- Missing metrics are `insufficient`, never zero.

## D7: Production runtime roots are explicit and fail closed

- Every production service declares code, config, data, secrets, and production mode explicitly.
- MCP and CLI resolve the same shared database and private config; production never falls back to release-local state.
- Missing production config is a startup error, not a default-media-disabled runtime.
- Coordination documents use logical path aliases and never publish server-private absolute paths.

## D8: Automated admission is deterministic and single-platform

- Production automated jobs require exactly one platform and a validated current run contract before database creation.
- MCP creates the run contract from the checked-in rulebook; model-provided contracts are not trusted.
- Existing automated jobs are revalidated before execution, so legacy no-contract rows cannot be force-run.
- Manual/non-production creation remains available for bounded tests and operator drafting, but cannot acquire automated production semantics implicitly.
