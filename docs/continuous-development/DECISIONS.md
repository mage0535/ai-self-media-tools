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

## D9: Platform artifact requirements do not depend on mutable media flags

- Short-video platforms require a real non-empty video and cover before production review or approval.
- Article/carousel platforms require real non-empty inline image and cover artifacts.
- Platforms that explicitly permit text-only delivery are not forced to invent media.
- Expired generation leases are recovered through a targeted store transaction and normal Pipeline claim, never by deleting locks with ad hoc SQL.

## D10: Pre-generation gates consume only facts available before generation

- Source identity, blueprint, compiled rule/capability context, required media runtime, and publisher route are validated before invoking the model.
- Generated prose fields are not invented or required by the pre-generation gate.
- Native evidence from another platform is a hard mismatch; a bounded editorial-calendar fallback must carry its own strategy, date, and dedupe evidence.
- A pre-generation failure records an explicit workflow gate and model invocation count remains zero.

## D11: Evidence levels are proven, not inferred from execution stage

- `executed` proves an adapter ran; `output_verified` proves its output contract and hash.
- `artifact_verified` additionally requires a real artifact path, readable bytes, and matching SHA-256 evidence.
- `effect_verified` additionally requires an artifact-level probe showing the intended rule, motion, subtitle, audio, or quality effect in the final output.
- An assets/render/gate stage name alone never upgrades evidence level.

## D12: Verification level is part of the executable capability contract

- Every executable capability has exactly one declared minimum verification level in the checked-in registry.
- The registry validator rejects missing, invalid, or orphan verification declarations.
- Routers pass the declaration to the DAG; adapters cannot self-promote by returning a status string.
- `output_verified` remains valid for analyzers, plans, MCP results, and receipts that do not directly create a file.
- File-producing capabilities may declare `artifact_verified` only when their adapter emits path and SHA-256 evidence; effect claims require a separate artifact-bound probe.

## D13: Inventory is a governed state, not implied execution

- Every inventory-only capability has one machine-readable disposition and a non-empty reason.
- Unverified-license capabilities are excluded from production routing even if their files exist on the server.
- Public/internal methodologies consumed through compiled skill rules are recorded as compiled references, not separate tool executions.
- A future adapter is named as planned work and remains unavailable until its real adapter, contract, probe, and tests land.
- Parent-executed capabilities remain valid only with parent availability and a child telemetry contract.

## D14: Generation SLOs are signed workflow policy

- Production generation limits are carried in the run contract, not chosen by the active model or long-lived Hermes chat.
- The current production bounds are 90 seconds soft deadline, 180 seconds hard deadline, 15 seconds heartbeat, and at most two attempts.
- A heartbeat is emitted from the first interval; soft-deadline status is a later state, not the start of observability.
- Every job writes attempts and atomic checkpoints in its own directory and records a pipeline execution correlation ID.
- The Hermes CLI process is isolated as a process group and must exit before retry; a failed termination is terminal and cannot spawn a second attempt.

## D15: Image recovery is per asset and configuration-bound

- Every accepted image is checkpointed atomically with prompt/role signature, provider configuration, checksum, and perceptual hash.
- Resume reuses only a readable file whose signature and SHA-256 still match; provider/model/quality/method changes invalidate the checkpoint.
- An automated image task always enables bounded quality recovery even if an operator omitted the optional flag.
- Provider exceptions record the attempted provider before rotating, so generated fallback can be proven rather than inferred.
- Completed images are not regenerated after a later asset timeout; missing or invalid assets resume independently.

## D16: Video rendering fails locally and proves final effects

- Shots render serially with a bounded local retry budget; an exhausted shot stops the renderer before any later shot starts.
- A valid cached shot must meet file-size and measured-duration requirements; invalid partial output is deleted before retry.
- Shot progress and attempt counts are written atomically after each successful shot and on terminal shot failure.
- Scene execution evidence binds every plan field, source-asset SHA, renderer mode, transition mapping, and measured motion probe to the final MP4 SHA.
- A final MP4 path alone is not renderer execution proof; the capability reaches `effect_verified` only with artifact-bound passing scene evidence.

## D17: Publication identity requires independent verification

- User/manual confirmation alone cannot create a publication identity or performance windows.
- Accepted identity levels are URL probe, platform postcheck, or management-page verification, derived from explicit evidence source.
- Draft IDs, handoff paths, scheduled task IDs, uploader return values, and unverified external IDs remain delivery receipts only.
- A verified identity creates idempotent 1h/24h/72h windows from the real `published_at` timestamp.

## D18: Metric unavailability retries before becoming insufficient

- A due window is leased for each collection attempt and the lease is always released.
- Unavailable/empty collection remains pending with a delayed retry for a bounded maximum of three attempts.
- Only exhausted retries write an `insufficient` observation; missing data is never written as zero.
- Retry eligibility is checked before invoking a collector, preventing hot-loop retries.

## D19: Postcheck is a capability with publication-aware semantics

- `postcheck` is an allowlisted executable delivery-stage capability, not an inventory placeholder.
- A verified published identity produces executed/output-verified evidence.
- Drafted, scheduled, handoff, and review states produce an explicit skipped record because they are valid delivery boundaries but not publications.
- A publisher claiming `published` without an independently verified identity fails the postcheck adapter.
- Adapter success alone is not enough; its execution must be persisted into the canonical delivery trace.

## D20: Delivery Evidence Is Durable And Scoped

- A published trace always includes a required postcheck node, even when no evidence was supplied.
- Only contract-valid executed output with matching adapter-output hash and current content identity satisfies this node.
- Platform-scoped planned nodes require evidence from that platform. Rechecking a platform replaces its previous terminal nodes instead of retaining stale success.
- Save postcheck output with the delivery attempt before draft metadata projection; projection failure must not leave a known external outcome recorded only as in-flight.
- Validate callback account, content ID/URL, and platform against the delivery intent before creating publication metrics windows.
- Non-publication postcheck skips only the online-publication identity check; it does not waive draft readback, scheduling verification, or handoff quality gates.
- No source label or unit-test boolean alone proves a live independent postcheck. Record local integration evidence separately from platform/browser evidence.

## D21: P10 Activation Is A Transaction

- Build and attest one immutable release from the clean development commit; never run from the dirty server checkout.
- Snapshot symlink, systemd units/environment, private config, and database inode/count evidence before switching.
- Correct private config and gateway runtime roots as part of the same bounded activation; a code-only symlink switch is invalid.
- Keep every timer disabled through Linux tests, MCP shared-database verification, rollback rehearsal, and serial Canaries.
- Roll back symlink and runtime environment together if any mandatory verification fails. Mutable shared data is never rolled back or copied into a release.
- Do not sanitize or sign an already drifted legacy release. Build a clean tracked-only bootstrap rollback from its intended Git source and leave current untouched until activation.
- A bootstrap prepare runs full evidence generation, config validation, signing, and freeze but deliberately performs no symlink or systemd operation.
- An automated job without its pre-delivery trace persists a failed canonical trace and stops; delivery completion cannot silently return without execution evidence.
- Postcheck evidence participates in the delivery manifest hash, and its adapter output hash is recomputed before accepting executed state.

## D22: Release Preparation Owns Only Its Transaction Outputs

- Validate release names and every raw path boundary before normalization, lock creation, key generation, evidence output, or release-directory creation.
- An explicitly requested signing key must already exist; bootstrap preparation may create only the stable default key when no explicit key was requested.
- Reserve the final candidate directory exclusively after evidence generation and before publishing files. Never replace an existing directory, even if empty.
- Failure cleanup removes a release directory or attestation only when the current transaction proves ownership. Concurrent or pre-existing files are never cleanup targets.
- Systemd scope is an explicit production input. A user-scoped deployment command must not be used against system-scoped production units, or vice versa.

## D23: Scope Propagation Is Not Activation Acceptance

- Deploy, rollback, timer-state queries, and deployment acceptance pass the same explicit `user` or `system` scope; CLI default unit directories follow that scope.
- Preserve existing user-scope defaults for compatibility; production must explicitly select the observed system scope.
- Unit templates and effective runtime paths are distinct: effective-path verification must handle systemd expansion and validate the configured runtime identity, not merely compare template strings.
- No successful fake-systemd test authorizes activation; Linux root convergence, rollback, and live Canaries remain separate gates.
- For the current home-based installation, effective paths must equal the invoking deployment user's expanded home paths. Cross-user deployment requires a separately validated runtime identity and is not inferred from observed output.
- Parse environment assignments before comparison; prefix matches are insufficient for code/config/data/secrets/PYTHONPATH or production mode.
- Check release script paths only for ExecStart templates that invoke release scripts; an external scraper in an environment variable does not turn module-based ExecStart into a script invocation.
- Record staging commit and scope of Linux tests separately from production identity. A focused Linux regression does not substitute for full candidate evidence or live activation verification.

## D24: Configuration Preflight Precedes Expensive Release Evidence

- Validate the real config against clean source and explicit runtime roots before generating evidence or creating release directories; restore caller environment on both success and failure.
- Retain post-build config validation: early preflight is an optimization, not a replacement for final candidate verification.
- External Hermes bridges are real dependencies, not release-owned scripts. They remain blocked until their trust boundary, version/hash, input/output contract, and runtime availability verification are governed explicitly.
- Do not disable configured tools, copy unreviewed external scripts into public releases, or allow all external script paths simply to pass deployment gates.

## D25: External Dependency Identity Is Not Execution Evidence

- External Hermes scripts may pass release validation only through a private `external_runtime_dependencies_v1` contract bound to dependency ID, kind, config key, exact path and SHA-256.
- External bridge paths must remain under the current Hermes home, be regular non-symlink files and match their digest. Every attestation record must bind to a configured script; unused records fail.
- A trusted dependency remains only identity-verified. Capability availability, adapter execution, output contract, artifact/effect verification and quality impact require their own runtime evidence.
- Public repository files do not contain server bridge paths or private manifests. Candidate private config stays outside immutable releases and is promoted only within the activation transaction.
- Stable current-release aliases are recognized before symlink resolution and rebound only to an explicit candidate code root. Canary and deployment code must supply that root; ambient project-home inference is not acceptable for candidate verification.

## D26: Rollback Must Be Test-Green, Not Merely Historically Active

- A currently active historical release is not a trusted rollback when its clean source fails the release evidence suite. Preserve the failure report and do not patch history or reduce test thresholds.
- Prepare a clean, signed, inactive runtime commit that passes full Linux evidence as the bootstrap rollback for the later forward activation.
- Forward activation still requires a distinct transaction and rollback rehearsal; a prepared bootstrap does not prove current production or live platforms.
- Gateway environment convergence is part of that transaction because Hermes-hosted MCP children inherit gateway roots. A code symlink switch without gateway root verification is invalid.

## D27: Gateway Root Convergence Owns One Reversible Drop-In

- The project installs only `ai-self-media-runtime.conf` for `hermes-gateway.service`; existing proxy, resource, Telegram, memory and other Hermes drop-ins are never replaced or removed.
- Snapshot the managed drop-in and gateway enabled/active state before mutation. If installation, daemon reload, restart or effective environment verification fails, restore the drop-in, current link, project units and gateway state.
- Restart an active gateway after current-link activation so MCP children inherit the new code/config/data/secrets/runtime-mode roots. Verify all seven assignments exactly from systemd effective state.
- A passing fake-systemd transaction remains local evidence. Linux system-scope fault tests, forward activation, MCP shared-database proof and rollback rehearsal are separate gates.

## D28: Candidate Private Config Is Promoted Inside Activation

- Deployment may use an isolated candidate config for evidence and a separate stable active config path for runtime. Metadata binds the stable path to the candidate hash.
- Promote the candidate atomically with mode 0600 after release signing/freezing and before current-dependent gateway restart.
- Snapshot the previous stable config bytes, type and mode. Any later activation failure restores that snapshot; a missing prior file is removed on rollback.
- When candidate and active paths are identical, retain legacy behavior and do not rewrite the file. Private config remains outside immutable releases and Git.
- Windows tests verify bytes and ordering; POSIX permission semantics require Linux evidence before activation.
- Rollback must restore configuration before restarting old content services or gateway, not merely before the deploy function returns.
- Preserve installed feature-specific timers unless retirement is explicitly established. Checking in an existing schedule does not enable it.
- During failed activation, stop affected units/gateway, restore unit files/current/config, and only then restore service states. If configuration restoration fails, do not start or enable services and surface rollback failure.
