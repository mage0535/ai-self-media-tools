# Production Runtime V8 Server Evidence

Observed read-only on 2026-08-31.

## Runtime drift

- Current release: `$RELEASES/unified-capability-v7-149362f`
- GitHub feature branch: `149362f`
- GitHub main: `b059d07`
- Local checkout at audit time: `f625eeb`
- Server dirty checkout: `6f4c88a` plus modified and untracked files
- Private config `data_dir`: `$RELEASES/aebd7a9/data` (invalid production coupling)
- Current release contains no `config.json`.
- MCP fallback database: current release `data/state.db`.
- Shared production database: `$SHARED_DATA/state.db`.

## Hermes execution evidence

- Telegram session history: 544 messages, approximately 400k input tokens, 206 tool turns.
- Hermes created a private `clear_workflow_lock.py` helper and directly deleted `workflow_locks`.
- gbrain MCP repeatedly failed because no brain was configured.
- Content-platform MCP exposed 26 tools; the unified content registry formally routed three content MCP capabilities.

## 2026-08-31 task evidence

- WeChat job `d32cc05d25e24cf7`: 402s generation + 133s WeWrite, then blocked by missing pre-generation operations evidence; zero artifacts.
- Xiaohongshu job `24c149f47f1843d7`: approved with zero artifacts; image generation skipped as disabled.
- Bilibili job `5201df7960a24973`: review_required with zero artifacts.
- Douyin job `e2029f41ec5b43be`: review_required with zero artifacts.
- Kuaishou job `ffd4f37d4e5a4c4f`: orphaned in generating with expired lease and no process.
- Kuaishou job `8d3636bdc0914c93`: old job without run contract, 335s generation + 358s images + 242s video, then failed on `shot_04A`; no final MP4.
- Film renderer generated later shots after `shot_04A` failed and returned code 3 only after all shot work.

## Incomplete acceptance

- Latest 12-platform reports observed: `passed=false`.
- Xiaohongshu capability Canary remains failed; four image checkpoints existed at audit time.
- Shared Publication Ledger counts: identities=0, windows=0, observations=0, attempts=0.

## P1 local implementation evidence

- Added a single runtime-path resolver for immutable code and private mutable config/data/secrets.
- MCP config and database resolution now use the shared runtime contract.
- All project-owned systemd services declare the same five production roots/mode, and release deployment verifies their effective environment.
- Overnight batch and supervisor now reject missing private config/data/secrets instead of falling back into the release.
- Focused regression: 85 passed. Full regression: 1532 passed plus 37 subtests.
- Video visual-asset regression found and fixed a checkpoint-key collision that reduced four requested scene images to two unique assets.
- Server deployment, gateway drop-in, symlink switch, and shared-database inode verification have not run yet; timers remain disabled.

## P2 local implementation evidence

- Added deterministic automated-task admission before mutable job creation and before legacy job execution.
- Production automated tasks without a valid run contract fail with an explicit admission reason and leave no new database row.
- Hermes MCP accepts one platform per task, replaces untrusted model contract fields with a rulebook-compiled contract, and marks the job automated.
- Legacy automated tasks lacking a contract remain in their original state and cannot enter generation.
- Focused admission/pipeline/overnight regression: 102 passed. Full regression: 1537 passed plus 37 subtests.

## P3 local implementation evidence

- Added a platform artifact contract independent of mutable media-enabled settings.
- Production review/approval rejects zero, missing, empty, or unreadable required video/cover/image files.
- Text-only X/Twitter delivery remains valid without invented media requirements.
- Added targeted stale generation lease recovery; it clears only the expired job lease, records `stale_job_recovered`, and resumes through normal workflow locking/claiming.
- Focused completion/store/pipeline regression: 89 passed. Full regression: 1543 passed plus 37 subtests.

## P4 local implementation evidence

- Added a production pre-generation gate after deterministic strategy/capability compilation and before any provider/model call.
- The gate validates same-platform source identity or explicit editorial fallback, content blueprint, profile, capability plan, compiled skill rules, bounded model input, required media runtime, and publisher route.
- Fault injection with missing platform source evidence ended in `blocked` and asserted that `generator.generate` was never called.
- Cross-platform native identity is rejected rather than relabeled.
- Focused pre-generation/pipeline/overnight regression: 100 passed. Full regression: 1546 passed plus 37 subtests.

## P5 gap scan

- Registry count: 65 capabilities; 26 executable, 20 parent-executed with parent telemetry contracts, and 19 inventory-only.
- The current DAG promotes any contract-valid `assets` or `render` execution to `artifact_verified` based only on stage.
- Several adapters return plans or structured evidence rather than files, so stage-based promotion can overstate final-artifact impact.
- P5 must add explicit verification-level contracts and artifact/effect probes before expanding remaining adapters.

## P5 evidence-level implementation evidence

- Added an explicit verification-level map covering all 26 executable registry capabilities; registry validation rejects omissions and orphan entries.
- Router candidates carry the declared level into the execution DAG.
- Contract-valid adapter output is recorded as `output_verified`; stage names no longer imply artifact or effect proof.
- Artifact proof now checks a real non-empty file and recomputes SHA-256. Effect proof additionally checks a named passing probe whose artifact hash matches the verified file.
- Failure injection confirmed that an assets-stage adapter with no file evidence fails a required artifact contract, and an unbound effect hash fails effect verification.
- Focused capability/router/DAG/MCP/Pipeline/Canary regression: 150 passed. Full regression: 1550 passed plus 37 subtests.
- This is local implementation evidence only. Server capability runs and real media artifacts have not yet been revalidated against this branch; timers remain disabled.

## P5 inventory governance evidence

- All 19 inventory-only capabilities now have an explicit disposition and reason in the checked-in registry.
- Twelve unverified-license entries are `license_excluded` and cannot enter consulted, selected, or executed states.
- Six public/internal methodology entries are `compiled_reference`; their rules are consumed through deterministic compiled-skill context rather than false standalone calls.
- Publisher-specific `postcheck` remains `planned_adapter` for P9 and cannot be claimed as executed before that implementation.
- Router tests prove inventory-only entries do not appear in consulted or executable candidates and always expose disposition plus reason.
- Focused registry/router/evidence regression: 60 passed. Full regression: 1551 passed plus 37 subtests.
- No live server capability smoke was run in this phase; production release and timers remain unchanged.

## P6 local generation SLO evidence

- Added signed run-contract bounds: 90-second soft deadline, 180-second hard deadline, 15-second heartbeat, and maximum two attempts.
- Generator reads the contract before looser local defaults and normalizes invalid non-production SLO relationships without breaking zero-second fault injection.
- Heartbeats now begin at the first heartbeat interval; tests prove a running checkpoint is written before the soft deadline.
- Pipeline assigns each job a distinct execution correlation ID and already isolates checkpoint and attempt files by job ID.
- Existing process-group termination, output byte limit, reduced-context retry, non-transient no-retry, and atomic checkpoint tests remain green.
- Focused generator/run-contract/pipeline regression: 89 passed. Full regression: 1555 passed plus 37 subtests.
- Server Hermes execution has not been exercised with these limits yet; production release and timers remain unchanged.
