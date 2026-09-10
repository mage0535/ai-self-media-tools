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
- Runtime read timing is an acceptance criterion: recovering old gateway must read the old config at startup. File restoration after startup does not satisfy rollback correctness.

## D29: Every Signed Release Has A Durable Private Config Snapshot

- Copy the validated candidate config into `$SHARED_DATA/release-configs/<release>.json` with exclusive creation and mode 0600 before signing metadata. Handle partial OS writes and fsync before use.
- Metadata signs the durable snapshot path and hash. Staging candidate paths are never long-term rollback dependencies.
- Forward activation promotes the release snapshot to stable private config. Rollback verifies metadata/attestation and promotes the target release snapshot before gateway startup.
- Snapshot files remain outside Git and immutable code releases. Failed transactions remove only snapshots whose inode ownership belongs to that transaction.
- Older prepared releases whose metadata references staging configs are retained as historical evidence but are not final production rollback targets.

## D30: Failed Release Transactions Are Durable And Self-Cleaning

- Persist release failure type/message privately under shared data before returning the original exception. Never rely on an SSH stream as the only failure evidence.
- Remove attestation and config snapshot only when the transaction recorded ownership and the attestation hash or snapshot inode remains unchanged.
- Preserve JUnit, project audit, journal and pre-activation snapshots after failure. Failed release code directories may be removed when transaction ownership is proven.
- A successful rollback of current/config/services does not make the failed deployment successful; diagnose and fix the recorded cause before a new named attempt.

## D31: Remove Only Runtime-Conflicting Service Drop-Ins

- Project unit files are authoritative for runtime roots, WorkingDirectory and ExecStart; existing drop-ins overriding those fields are transactional conflicts.
- Preserve drop-ins that only define resource limits, provider env files, admission windows, writer fallback or other non-runtime settings.
- Snapshot each conflicting file before removal and restore exact bytes/mode/symlink on activation failure before restoring old service states.
- Never delete an entire service drop-in directory merely because one file is stale.

## D32: Signed Releases Must Remain Byte-Stable At Runtime

- Set `PYTHONDONTWRITEBYTECODE=1` in every project systemd service and the Hermes gateway project drop-in; validate it from effective systemd environment.
- Root permissions can bypass read-only mode bits, so mode 0555/0444 alone does not prove runtime immutability.
- Any untracked `__pycache__` or `.pyc` invalidates release verification. Do not clean and reuse a release built without this policy as final production; build a new signed release.
- Preserve contaminated releases as evidence until their status is documented. Never weaken the tracked-only attestation check to allow runtime caches.

## D33: Hermes MCP Child Environment Is Part Of The Release Transaction

- The `content-platform` stdio MCP entry explicitly supplies its child environment, so a correct gateway environment does not prove the MCP child has correct runtime roots.
- Real systemd deploy and rollback automatically target the private Hermes config; offline/no-systemd release construction does not. Operators may override the path, but cannot silently omit it during a CLI systemd switch.
- Replace only `mcp_servers.content-platform.env` with the eight project-managed production assignments. Preserve all other MCP servers, model settings, startup mode, timeout and enabled state byte-for-byte outside that block.
- Require a regular non-symlink private config and exactly one top-level MCP mapping, one content-platform entry and one env block. Ambiguity fails closed.
- Snapshot original bytes and mode before mutation. On activation failure, restore Hermes config together with runtime config before restarting the old gateway.
- Do not add a deployment dependency on the Hermes CLI or an undeclared YAML package. Validate the surgical transformation and the spawned process environment independently.

## D34: Platform Trend Evidence Has Explicit Recovery Levels

- Prefer current same-platform works with canonical content URLs, visible engagement, captured time, collector identity and source artifacts. An HTTP 200 with zero parsed works is `no_verified_results`, never `ok`.
- First-party creator keywords and activities are a separate `official_keyword`/`official_activity` layer. They may improve topic scoring but never masquerade as a native associated-hotspot identity or a same-lane work.
- Resolve valid private cookie state and platform-specific default queries deterministically. Try direct first; use CN/US proxy only after a classified platform/network failure and retain every route attempt.
- A successful logged search may create a mode-600 private cache bound to platform, query, canonical URLs, visible metrics, capture time and source artifact SHA-256. Cache fallback is allowed only for transient platform errors within six hours; login failure, ordinary zero results, tampering, identity mismatch and expiry fail closed.
- Platform-specific parsers are required when the content title and metrics live in a card context rather than link text. Never weaken canonical URL or positive engagement requirements to make a parser pass.
- Automatic task admission remains blocked when no current lane-matched evidence exists. Retrying the platform, using a valid official reference, or eventually applying an explicitly allowed evergreen fallback is acceptable; cross-platform hotspot identity reuse is not.

## D35: Final Copy Must Survive Every Model Rewrite

- Humanization is a second model generation step, not a harmless formatter. Its candidate title/body must pass deterministic Markdown normalization, generated-text hygiene and the verified claim ledger before replacing the already accepted draft.
- A failed post-humanizer check keeps the previous accepted copy and records `humanize_rejected` with claim and hygiene failures. It does not silently accept the rewrite or discard the valid original.
- Unsupported named-tool recommendations and install commands require matching verified claim evidence. Structural advice without external factual attribution remains allowed.
- Article image requirements do not imply an independent narration artifact. Audio generation is limited to explicit audio/podcast content forms; video narration remains owned by the video renderer.
- Optional providers may remain planned or unavailable without failing an artifact probe. Every required artifact-relevant capability must still reach `artifact_verified`.

## D36: Aggregate Quality Scores Never Replace Final Text Inspection

- A passing platform score, content-depth score or artifact probe does not prove the final title/body is publishable. Automated work must pass deterministic final-text hygiene after all factual sanitization and bounded repairs, before media generation.
- Source-page code/navigation contamination still blocks immediately. Other prose defects are evaluated after factual repair so a repeated unsupported claim can be removed or repaired before the final hygiene decision.
- Known model formatting damage may be repaired deterministically without changing prose meaning: fenced-block line boundaries, comma-only YAML corruption, split hidden-directory identifiers and the observed `packageon` corruption.
- Repository endorsements and Agent Skills loading/trigger mechanisms are factual claims. They require verified ledger evidence; otherwise they are sanitized or the task is blocked.
- Dotted technical identifiers are content, not sentence boundaries. Claim patterns must handle `SKILL.md` and `.agent/skills` without stopping at the embedded period.

## D37: A Final Retry Uses A Minimal Verified Contract

- The normal generation attempt keeps full platform, hook, style and compiled-skill context. Quality is not globally reduced to improve latency.
- After a bounded hard timeout, the one final retry includes only the JSON output contract, language, factual boundary, content length, a compact platform-rule summary, one hook reference and a 3,072-byte verified generation context.
- The retry must retain the selected topic and claim ledger and must not repeat the full methodology/style corpus. Both attempts remain bound by heartbeats, process-group termination and recorded prompt hashes/lengths.
- A second hard timeout is a real terminal failure. Do not add unbounded retries or silently use fallback copy.

## D38: Trend Evidence And Factual Evidence Are Separate Contracts

- A platform search card proves that a topic or work was observed with a URL and visible engagement. It does not prove the technical claims inside a new article.
- Production automated Juejin technical articles require at least three verified facts with claim text, source URL, evidence path and provenance hash before the model call.
- Task9 source claims are accepted only when their evidence file remains inside `_inputs`, its SHA-256 matches, and the declared source excerpt occurs in that file. The translated or editorial claim remains separate from the source excerpt.
- A popular article may inform hook, structure and display style; technical facts should prefer primary/official documentation. Do not treat popularity as authority.
- Automated long-form copy requires at least three substantive H2 sections before article media. Missing structure blocks; media code must not manufacture headings to make an invalid draft pass.

## D39: Real Canary Means Production Admission Is Active

- A Pipeline Canary must set `CONTENT_PLATFORM_RUNTIME_MODE=production` for create, run, media, gate and safe delivery-boundary execution. Loading a production config alone is insufficient because pre-generation admission reads the runtime mode.
- The Canary restores the caller's prior runtime-mode environment on every success or failure path.
- Historical Canary artifacts generated while the production admission gate was skipped may prove individual providers, media contracts or artifact probes. They do not prove production admission and cannot satisfy the 12-platform release gate.

## D40: A Blocked Draft Is Recovery Evidence

- Final text-hygiene and article-structure failures persist the complete candidate title/body, draft metadata and gate detail before changing the job to blocked. Compact workflow excerpts are not sufficient for automated diagnosis or repair.
- Deterministic normalization may remove one unmatched straight quote from prose while preserving complete fenced code blocks and balanced quote pairs. Raw validation continues to detect malformed quotes; normalization is the repair step.
- Persisting a blocked draft is not approval, review completion or delivery evidence. Media and publishers remain uncalled.

## D41: Article Images Bind To Final Copy

- Article section-image mapping parses headings from the final normalized and fact-checked body first. Generator-time section metadata is stale after sanitization, repair or humanization and may only fill missing headings.
- A valid final heading is a semantic input to image intent, provider selection and image quality evidence. Opening prose fragments must not displace final section headings.
- Failed candidates retain file hashes and semantic evidence. Three mismatches still fail closed; changing section identity is not permission to weaken semantic thresholds.

## D42: Verified Sources Are Rendered, Not Merely Stored

- Article claim-ledger evidence must appear in the final copy as a compact Markdown source list before GEO and media generation. Hidden metadata alone does not help readers verify claims.
- Only verified HTTP(S) URLs are eligible. URLs are deduplicated, labels are sanitized, file/private paths are excluded and an existing references section is not duplicated.
- Do not manufacture numeric claims, authority quotations or FAQ text to satisfy GEO. A real source appendix legitimately satisfies source and structured-list dimensions.

## D43: Natural Chinese Ellipsis Is Not Automatically A Fragment

- Chinese sentences ending with a classifier may be complete when parallel verbs supply the omitted noun, for example `跑顺一个，再做下一个。`.
- Continue blocking conjunction endings and explicit incomplete predicates such as `这只是一个。`. Do not remove English dangling-article checks.

## D44: Deterministic Fallback Must Preserve Semantic Diversity

- A deterministic fallback is not permission to reuse one visual. Final article headings and subtitles select semantic layouts such as workflow, document anatomy and resource stack.
- Each completed article asset atomically claims its checksum. A duplicate produced by another concurrent asset is a retryable per-asset failure with preserved candidate evidence, not a package-level surprise after all work finishes.
- Stable identical input remains reproducible, while different semantic sections must produce different output hashes. Color-only randomization is not accepted as semantic diversity.
- Technical filename normalization uses ASCII identifier boundaries so `SKILL.\nmd` is repaired even when adjacent to Chinese text.

## D45: Content Headings Are Not Transition Prose

- Final Markdown H2 headings remain distinct media sections regardless of their length or question punctuation. Transition-sentence merging applies only to fallback metadata/prose fragments.
- References/source appendix headings are reader evidence, not illustration subjects, and are excluded from article image mapping.
- When at least three final content headings exist, media mapping must not supplement or replace them with stale generator metadata.

## D46: Machine Green Does Not Override Final Artifact Review

- Canary probe success is necessary but not sufficient while uncovered defect classes remain. Manual review findings must become deterministic regression tests before any live draft upload.
- Weak-model Markdown normalization may repair Unicode YAML frontmatter delimiters and numbered-list line breaks without changing prose meaning.
- Assertions about how an Agent discovers, routes, loads or invokes resources are technical mechanism claims and require verified evidence.
- Article section images are normalized atomically to their requested platform dimensions before semantic analysis and checksum evidence, so gates measure the actual delivered crop.

## D47: Reader-Facing Evidence Must Not Leak Internal Labels

- Verified source appendices use stable reader-facing labels for known source types. Internal enum values are implementation evidence, not article copy.
- Weak-model H2 lines may be split from an attached opening sentence only for explicit sentence openers and only outside fenced code. Ambiguous headings remain unchanged for a gate or manual review.
- A machine-green candidate is not rerun automatically when deterministic post-processing can be applied and independently revalidated; avoid unnecessary provider cost and variance.

## D48: Claim Detection Covers Units, Modifiers And Reverse Attribution

- Numeric claims include token counts and approximate classifiers such as `20 多个`; exact values require evidence.
- Product/client support attribution is factual whether the action appears after the product or before a list of products.
- Chinese no-fee/no-registration/no-specific-plugin promises are promotional claims and require evidence.
- Verified domains may be recovered from a verified row's source URL as well as its claim text. Do not use unverified URLs for repair.

## D49: Technical Assertions Require Anchor Coverage

- Production technical content does not rely solely on an expanding blacklist of phrases. Declarative sentences with at least two technical anchors must align with at least two anchors in one verified claim and cover at least half of the sentence anchors.
- Questions and explicit advice/hypothetical instructions are not asserted external facts. Existing numeric, promotional, attribution and install-command gates still apply to them independently.
- Operational imperatives such as run, inspect, verify and save remain allowed. Claims that a product, Skill or Agent automatically performs or improves something require evidence.
- Pattern matching is a deterministic safety layer, not proof that all prose is correct. Fresh real artifacts and final review remain release gates.

## D50: Unsafe Technical Drafts Rebuild From Primary Claims

- When an automated Juejin technical draft contains unsupported technical assertions and at least three verified primary-source claims exist, rebuild the article deterministically instead of deleting isolated sentences or invoking an unbounded model repair.
- The rebuild uses only primary claims as facts. Platform hot-work titles may select the topic and hook but do not enter factual body copy.
- Advice is explicitly framed as advice, and the final copy still passes claim, hygiene, structure, GEO, cover and media gates. Insufficient primary claims remain a hard block.
- This is a safety fallback for low-capability model variance, not the preferred creative path. Its use is recorded in `grounded_technical_rebuild`.
- Rebuild templates must also pass the same repeated-paragraph/sentence gate. Evidence-boundary language appears once, not as section boilerplate.

## D51: Model Authentication Failure Is Not Content Recovery

- A live provider authentication failure occurs before content exists and must not trigger grounded copy rebuilding, media generation or a silent model substitution.
- Record the discovered provider/model and stop the Canary. Model selection continues to follow Hermes live configuration unless an operator explicitly changes that configuration.
- Deterministic recovery and media behavior may still be validated with a recorded negative draft and verified fact pack while live model availability is blocked.

## D52: Grounded Recovery Must Meet The Real Platform Depth Gate

- Do not lower Juejin's 1,200-character article minimum to make a conservative fallback pass.
- A grounded technical rebuild may quote only verified primary claims as facts. Additional depth must be explicit advice, review procedure, evidence boundary or reader action; it must not invent mechanisms, commands, compatibility, performance or outcome claims.
- The builder regression calls the same `validate_article_packet` body-length gate used by production, in addition to claim and generated-text hygiene validation.
- Passing length is not delivery approval. A fresh Linux recovery package still requires media generation, semantic image probes, complete capability evidence and manual final-copy review before a real draft publisher is allowed.

## D53: Semantic Evidence Scores Visible Concepts, Not Prompt Wording

- Keep the image semantic threshold at 0.6. Do not lower it to admit a visually relevant candidate.
- Normalize narrow, observable visual equivalents such as node, card and rectangle before scoring workflow-node concepts. Do not map generic robots, desks or offices to workflow evidence.
- Every added synonym requires a positive artifact-derived example and a nearby negative control. One broad synonym must not satisfy multiple independent expected concepts by itself.
- Preserve all failed candidates and their hash-bound vision captions so future changes can be evaluated against real false positives and false negatives.

## D54: Article Headings Must Compile To Observable Visual Subjects

- Do not append an abstract reader-facing H2 such as `核心定义` to semantic expectations when it cannot be observed in pixels.
- Deterministic fallback headings should name concrete objects or transformations while remaining readable: directory and SKILL.md, scripts/references/assets structure, and on-demand loading.
- Section routing converts those headings into a small set of visible concepts. It must not fall back to the same topic-level AI-agent concept for every section when a section-specific concept exists.
- Acceptance still requires independent image hashes and artifact-bound captions. Concrete headings improve generation and verification; they do not waive semantic evidence.

## D55: Section Renderers Consume Section Copy And Compiled Concepts

- A section fallback must not reuse cover headline/subtitle fields. It renders the final mapped H2 and its section purpose so layout selection and visible labels remain content-specific.
- Deterministic layout dispatch accepts the same compiled concept IDs emitted by image routing; renderer and analyzer cannot maintain unrelated vocabularies.
- SCRIPTS, REFERENCES and ASSETS are observable directory-resource labels. They may ground the directory concept, but generic cards or boxes without those labels do not.
- Keep cover and section output evidence separate. One completed cover cannot satisfy any section capability or semantic gate.

## D56: Machine-Green Media Still Requires Semantic Negation And Copy Review

- A process concept such as selective loading requires an observable action anchor. A caption containing `no papers` or another static/negated document noun cannot satisfy it.
- Low-model grounded fallback titles are derived from verified-primary claim subjects, not from unverified hot-title modifiers. Trend wording may guide topic selection but cannot re-enter factual copy through the title.
- The fallback provides its own fact-relevant question hook. Generic hook repair must not create a repeated `为什么{标题}` opening when the grounded body already has a valid hook.
- Task9 `review_required` plus artifact-probe success remains insufficient without manual copy and image review. A manual false positive becomes a permanent regression fixture.

## D57: Accepted Recovery Canary Is Not Live Publication Proof

- A deterministic recovery Canary may be accepted when production admission, all copy/platform/media gates, capability evidence, artifact probes and manual review pass in a fresh isolated directory.
- The evidence must state that the model call was replaced with a recorded rejected draft and that the real publisher was not invoked. It proves bounded recovery, not current provider health or platform delivery.
- Preserve a private manual-review record with title/body review, image roles, dimensions, SHA-256 uniqueness, audio inventory and publisher status.
- Continue with current-model generation and separate platform/publisher Canaries. Do not use one accepted article package to restore timers or claim 12-platform completion.

## D58: Hermes Generation Is Direct-First With Region-Only Proxy Recovery

- Do not force domestic or international generation through a proxy by default. The first Hermes model attempt inherits the worker's normal environment.
- If and only if Hermes output contains an explicit country/region availability failure, retry the same active model and same prompt once using private `US_PROXY` for `HTTPS_PROXY` and `ALL_PROXY`.
- Generic authentication failures do not use proxy recovery. Model/provider selectors remain absent unless an independently verified Canary selector was explicitly configured.
- Hermes CLI may print HTTP failures with exit code zero, so response-content classification is mandatory. Checkpoints record only `provider_region_failed`, never proxy credentials or endpoints.

## D59: Deterministic Media Fallbacks Preserve Section Identity

- Distinct semantic sections must not converge on one deterministic image. Duplicate-SHA rejection remains fail-closed and must not be weakened.
- Document anatomy, resource categories and selective loading use separate layouts with visibly different structures and labels.
- Layout precedence considers the final section heading as well as compiled concepts: a SKILL.md heading uses document anatomy even when it also carries a directory concept.
- Concurrency may decide which duplicate claims a checksum first; correctness cannot depend on completion order. Deterministic inputs must produce distinct outputs before checksum claiming.

## D60: Specific Visual Concepts Supersede Generic Topic Concepts

- When a section compiles to a concrete directory, loading, module-comparison or other specialized concept, do not require a second generic playbook/AI concept merely because the topic contains those words.
- Semantic acceptance evaluates the visible purpose of that section, not every term in the article title.
- SKILL.md, YAML frontmatter and Markdown instructions are observable document-anatomy evidence for a structured skill directory. Plain office documents without structural labels remain insufficient.
- Keep content-specific negative controls and the global threshold; this decision narrows expectations rather than lowering quality.

## D61: Real-Model Canary Requires Network Recovery And Manual Artifact Proof

- A current-model Canary is accepted only when model identity is discovered dynamically, any permitted region retry is evidenced, generation and all downstream gates complete, and final artifacts pass manual review.
- Deterministic factual rebuild after a weak-model draft is an accepted recovery path when its trigger and primary-claim count are recorded. It does not hide the model's original quality failure.
- A safe Task9 delivery boundary proves generation and media, not a live draft. Live publisher/readback remains a separate Canary.
- After one platform passes, continue the fixed serial matrix. Do not generate the next platform when its own source pack says it is not ready.

## D62: Aggregate Hot Boards Are Not WeChat Official Signals

- WeWrite `hotspots` may return cross-platform aggregate boards. A transport named WeWrite does not establish WeChat provenance.
- WeChat official keyword/activity contracts require an HTTP(S) URL on a WeChat first-party host, valid capture time, rank or heat, and a hash-bound raw snapshot. Sogou and other platform hosts are rejected.
- Cross-platform trends may inform background analysis but cannot satisfy WeChat same-platform hot-work or official-signal admission.
- Expired creator-backend login remains an external source blocker. Do not generate or relabel evidence merely to keep the platform count moving.

## D63: WeChat Evergreen Is A Bounded Strategy Fallback

- Platform official signals and metric-bearing same-lane works remain first priority. Strategy evergreen is considered only after the configured same-platform requery rounds all complete empty.
- Evergreen topics live in the versioned WeChat recovery playbook, use advice/Q&A framing without factual performance claims, and rotate through 14-day topic fingerprints.
- The selected candidate is `editorial_calendar`, not native, official or associated-hotspot content. It records strategy source, calendar column, planned date and dedupe result.
- Missing requery capability, missing strategy status, or an exhausted topic pool blocks the platform. Do not silently invent a new topic with the model.

## D64: WeChat Quality Gates Follow Content Mode

- GitHub project evidence and dual GitHub channels are required only for a GitHub-directed article. A fully evidenced Q&A/editorial fallback is not blocked by irrelevant GitHub fields.
- Editorial fallback still requires account positioning, selected-topic rationale, article plan, workflow inputs, growth playbook, one-item batch contract, strategy evidence and three completed empty recaptures.
- The professional writer gate accepts successful WeWrite or successful explicit Hermes writer evidence while retaining their identities. It never relabels fallback output as WeWrite.

## D65: Platform Intelligence Uses One Registry And Two Evidence Pools

- The registry must cover every canonical publishing target before adding reference sources. Current scope is 12 targets plus domestic and international reference platforms.
- Target-native/official/same-lane evidence and cross-platform reference evidence are stored separately. Reference evidence cannot satisfy target readiness, native identity or associated-hotspot gates.
- Comprehensive ranking exposes identity, heat, freshness, lane fit, content value, saturation penalty and source quality. High heat on another platform cannot outweigh a qualified target-platform sample.
- A registered source without a working adapter reports unavailable. Registry presence is not execution evidence.

## D66: Synthetic Search Fallback Is Not Reference Evidence

- A generated operating hypothesis with no real URL is `unavailable`, even when a collector returns several rows. It must not be counted as an `ok` source or enter cross-platform references.
- Observing a reference platform never adds it to the publishing-target parameter-pack keys. The default pack remains exactly the registry's canonical publishing targets.
- Live smoke reports use the same `ok/degraded/failed` classification as `TrendCollector`, not ad hoc non-empty checks.

## D67: WeChat Writer Transient Recovery Is Bounded

- Preserve primary WeWrite failure and explicit Hermes writer identity. A transient 429/5xx/timeout in Hermes writer may retry once after a bounded delay on the same selected route.
- Region recovery selects the route; transient recovery does not switch models, providers or routes. A second failure stops the platform.
- Recapture evidence must travel from task row to generation brief and final packet. Keeping it only in scheduler state cannot activate content-mode gates.
- Deterministic no-AI-slop repair handles observed wording, then the external checker still validates the final body.

## D68: External Slop Findings Become Exact Rewrite Fixtures

- Do not disable or bypass the external no-AI-slop checker after all structural gates pass.
- Convert each observed false-profound/binary phrase into a narrow deterministic rewrite with a regression test; leave unrelated prose unchanged.
- A clean writer status does not imply clean copy. Media remains closed until the final post-writer body passes.

## D69: Binary-Contrast Repair Covers Short Subjects Without Awkward Duplication

- A one-character Chinese contrast subject is valid input to the slop repair; minimum-length assumptions must not let it bypass the external checker.
- Consume optional emphasis such as `根本` as part of the matched construction so deterministic output does not create doubled emphasis.
- Keep the rewrite local to the matched sentence and rerun the unchanged external checker.

## D70: Explicit Article Visual Plans Override Generic Heading Semantics

- When a final article contains an explicit visual-plan line adjacent to an H2, bind that plan to the section image before provider routing. Do not discard it and replace it with a generic adjacent-point purpose.
- Semantic expectations must describe observable visual objects or layouts, not full marketing titles or abstract H2 prose. Tool overload, input/output boundaries and checklist decisions use separate concrete concepts.
- A more specific plan-derived concept supersedes a generic topic concept so one section image is not required to depict several conflicting ideas.
- Preserve the global semantic threshold, provider retries and duplicate checks. This corrects intent compilation; it does not relax acceptance.

## D71: Article Visual Plans Survive Reader-Facing Cleanup

- Extract explicit per-section visual plans in the professional writer toolchain and persist them in `section_image_map` before body cleanup.
- Media generation first consumes the persisted mapping, then allows body-local plans to override it. A cleaned article must not lose its visual intent.
- Generic adjacent-point purposes are fallback only; they cannot replace an available concrete plan.

## D72: Embedded Provider Branding Fails Every Final Image Role

- A provider known to embed a logo or attribution mark declares that property in fresh and cached result contracts.
- Covers and inline images follow the same rule: embedded provider branding fails the candidate and rotates to the next provider or project-owned renderer.
- Do not crop or conceal a provider mark. Preserve the rejected candidate and reason in quality-recovery evidence.

## D73: Deterministic Visual Semantics Require Two Hash-Bound Sources

- Third-party generated images pass only on independent vision evidence. They cannot use renderer metadata to repair a failed score.
- Project-owned deterministic visuals may combine independent vision structure evidence with renderer-declared concepts and visible labels only when the renderer output SHA equals the inspected artifact SHA.
- Each supported deterministic layout has its own observable geometry contract. Missing structure, missing labels, wrong provider or hash mismatch fails closed.

## D74: Three-Layer Topic Decisions Have One Auditable Identity Boundary

- Same-platform same-lane works, same-platform official activities/keywords and cross-platform references remain separate evidence classes. A cross-platform reference never receives target-platform or native-hotspot identity.
- Same-platform viral works require a real URL, capture time, collector and at least one non-zero platform metric. Official activities may lack public interaction metrics, but remain `native_verified=false` unless a separately verified native hotspot identity exists.
- Official support boosts a work only when at least two configured lane terms overlap; one generic term such as `AI` is insufficient unless it is the account's only configured term.
- The first rollout is compatibility observation in overnight preparation. It records the unified decision and coverage before generation without silently changing legacy ranking. CLI, MCP and Pipeline become authoritative only after their collectors satisfy the same contract and shadow differences are accepted.

## D75: Pipeline Owns Topic-Decision Compilation For Every Creation Entry

- `Pipeline.create` idempotently preserves an existing `topic_decision_v1`, compiles one from supplied candidate evidence, or records `missing_evidence`; it never manufactures a platform candidate from a title alone.
- MCP inherits this behavior by calling Pipeline. CLI auto passes its selected candidate, target identity, collection time and collector into the same contract. Overnight keeps the richer task-level decision and provider brief fields.
- The run contract explicitly admits `topic_decision` in generation input and treats it as bounded advisory evidence. Unknown fields remain fail-closed; adding topic evidence does not loosen the contract.
- Four-entry consistency means the same contract reaches model input. It does not mean legacy ranking is removed or that weak collector evidence becomes sufficient. Authoritative cutover waits for B2 contracts and accepted shadow differences.
