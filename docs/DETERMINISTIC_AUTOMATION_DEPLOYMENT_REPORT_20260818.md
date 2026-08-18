# Deterministic Automation Deployment Report - 2026-08-18

## Outcome

The production runtime now compiles per-platform rules and constrains the active Hermes model to bounded stage inputs. Rules, evidence, state, media quality, publishing boundaries, recovery, and receipts are enforced by code rather than model memory.

## Deployed Capabilities

- Hashed `run_contract_v1` with fixed precedence and drift detection.
- Three bounded lane-specific topic re-search rounds plus labeled editorial fallback.
- Platform/topic/audience `content_blueprint_v1`, including functional cat/dog roles for AI knowledge lanes.
- Deterministic removal of unsupported generated claims followed by a second fact check.
- Content-depth enforcement before media generation.
- Persistent exact/perceptual asset reuse ledger with source, license, and semantic evidence.
- Topic-specific viral cover evidence and fail-closed delivery gate.
- Content-hash media staging, unified acceptance, and truthful publish/handoff receipts.
- Three-minute independent supervisor with at most two safe interrupted-stage recoveries.
- Weekly deletion of rebuildable aged intermediates only.
- Active Hermes model inheritance; no pinned provider/model and no silent provider fallback.
- Edge TTS default; Qwen `auto` selection requires explicit A/B quality approval.

## Verification

- Local full suite: `866 passed, 33 subtests passed`.
- Production full suite: `894 passed, 33 subtests passed`.
- Project audit and channel rulebook validation passed.
- Active-model provider smoke passed with fenced JSON normalization.
- Isolated compiled canary completed and staged to a file publisher without accessing a live platform.
- Canary evidence: hashed run contract, bounded model input, unsupported-claim sanitization, content-depth pass, all workflow steps succeeded, idempotent drafted receipt.
- Supervisor and runtime-cleanup timers are enabled and active.
- Superseded render/review caches were removed without deleting final works, covers, source assets, state databases, cookies, or handoff evidence.
- Public repository, local main, and production main were synchronized to the same audited revision before this report-only follow-up.

## Stability Boundary

One successful canary proves the compiled path and recovery contracts, not every external platform. Production stability is declared only after three consecutive scheduled runs complete without code edits or manual recovery. External authentication, provider, network, and platform-review failures remain possible; they must now become explicit, recoverable, and non-publishing failures rather than silent success.
