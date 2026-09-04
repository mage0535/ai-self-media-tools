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

## P7 local image recovery evidence

- Fault injection generated and checkpointed a cover, timed out the following section image, then resumed the same job.
- The resumed run did not call the cover provider again and generated only the missing section; the checkpoint contained one accepted record after the failed first run.
- A stock timeout rotated to SenseNova. Recovery evidence retained the failed stock provider, timeout error, and successful generated fallback identity.
- Accepted checkpoints now persist and reload perceptual hashes so resumed jobs still reject near-duplicate visuals.
- Checkpoint signatures include provider, model, quality, and method; changing provider from stock to SenseNova invalidated and regenerated the asset in test.
- Automated workflows enable bounded image quality recovery by default, with the existing maximum-attempt cap retained.
- Focused media/image/provider regression: 69 passed. Full regression: 1559 passed plus 37 subtests.
- No paid or live server provider was invoked by these tests; production image Canary remains a deployment gate and timers remain disabled.

## P8 local renderer recovery and effect evidence

- Fault injection rendered shot 1, failed shot 2 twice, and proved shot 3 was never invoked.
- A second test failed shot 2 once, retried only shot 2, then continued to shot 3 after success.
- The renderer writes `shot_render_checkpoint.json` atomically with completed records, attempt counts, or the terminal failed shot.
- Scene execution evidence v2 recomputes final MP4 SHA and validates each scene's purpose, source-asset SHA, camera, subject/text motion, transition, rhythm, interaction prompt, two renderer records, and motion probe.
- High-quality mode rejects scene fallback, missing motion, transition mismatch, asset-hash mismatch, or incomplete renderer records.
- Runtime adapter and registry now require `video_toolchain_runner` effect verification; file existence without scene evidence fails.
- Focused renderer/effect/runner/Pipeline/Canary regression: 222 passed. Full regression: 1567 passed plus 37 subtests.
- No live FFmpeg/Playwright server render was run in this phase; production video Canary remains required and timers remain disabled.

## P9 local publication identity and metric retry evidence

- Added source-to-verification-level mapping for management page, platform postcheck/API/browser, and canonical URL probes.
- Fault injection with complete URL/ID/time fields but `source=manual` was rejected and created zero identities and zero windows.
- A management-page manual receipt produced `management_page_verified` rather than the previous blanket `manual_verified` state.
- Metric collector unavailability now records and releases an attempt lease, keeps the window pending, and delays the next eligible attempt.
- Tests ran three unavailable attempts at eligible times: attempts one and two remained retry-pending; attempt three wrote `insufficient` without synthetic zero metrics.
- Focused ledger/store/CLI/Pipeline regression: 111 passed. Full regression: 1569 passed plus 37 subtests.
- P9 is not complete: publisher-specific postchecks still need unified capability execution evidence. No live platform publication or metric API was invoked; timers remain disabled.

## P9 local postcheck capability evidence

- Converted `postcheck` from inventory-only/planned adapter to an allowlisted executable runtime capability.
- Registry verification now covers 27 executable capabilities and 18 governed inventory-only entries.
- Adapter tests proved: verified published identity executes; drafted delivery skips with `non_publication_status`; published task/external ID without identity fails.
- Output contract distinguishes executed, skipped, and failed evidence without promoting drafts or schedules to publication.
- Focused registry/adapter/ledger regression: 71 passed. Full regression: 1572 passed plus 37 subtests.
- Pipeline delivery trace persistence is still pending, so P9 remains in progress. No live publisher was called and timers remain disabled.

## 2026-09-02 P9 Delivery Trace Integration (Local Only)

- Resumed the uncommitted trace wiring from `ea8cf57`; re-read all four coordination documents before editing.
- Added SQLite-backed delivery integration tests across published/drafted/scheduled/handoff outcomes, using replacement publishers (no platform network calls).
- Confirmed eight initial failures for absent/invalid evidence, mismatched identity, and missing attempt-level evidence; repaired each and reran focused tests.
- Additional fault tests exposed cross-platform success masking, tampered output acceptance, and missing automated pre-delivery trace bypass; all now fail closed.
- Wrong account/content/platform is rejected before inserting any identity or metric window.
- Metadata projection failure leaves the finished attempt, postcheck evidence, and released lease durable in SQLite.
- Focused suite: `python -m pytest tests/test_postcheck_capability_v8.py tests/test_execution_trace_task3.py tests/test_task7_delivery_ledger.py tests/test_pipeline.py tests/test_capability_registry_task3.py -q --junitxml=artifacts/test-reports/p9-trace-focused.xml` => 146 passed before the final identity/hash additions.
- Final full suite: `python -m pytest -q --junitxml=artifacts/test-reports/p9-trace-closure.xml` => 1593 passed plus 37 subtests; JUnit 1630 tests, 0 failures, 0 errors, 290.565 seconds.
- Final project/privacy audit: 574 scanned files, zero issues. License audit: 65 capabilities, zero issues. Diff check passed.
- Production services, symlinks, database, and timer configuration were not modified or re-probed this turn. Server-state claims above remain dated 2026-08-31 observations.

## 2026-09-02 P10 Read-Only Server Refresh

- Current symlink resolves to `$RELEASES/unified-capability-v7-149362f`; the immutable directory has no Git metadata and no `release-metadata.json`.
- Dirty mutable checkout remains at `6f4c88a`.
- System `hermes-gateway.service` is enabled/active. All listed ai-self-media timers are disabled; overnight and supervisor timers are inactive.
- MCP processes are in the gateway cgroup. Effective MCP environment contains only `$CURRENT_RELEASE` as `CONTENT_PLATFORM_HOME`/`PYTHONPATH`; config/data/secrets/production-mode variables are absent.
- Private config media flags are enabled, but its data root still points to `$RELEASES/aebd7a9/data`.
- `$SHARED_DATA/state.db`: 63,143,936 bytes, inode 1642977, 433 jobs. Release-local `data/state.db`: 196,608 bytes, inode 3411510, 0 jobs.
- Root filesystem is 84% used with roughly 14 GB free.
- No changes, restarts, symlink switches, database writes, or timer enables were performed during this refresh.

## 2026-09-02 P10 Staging And Bootstrap Preparation

- GitHub branch `codex/production-runtime-v8@e1d6068` cloned to isolated server staging; Python 3.12.3.
- Linux focused P1-P9 suite: 70 passed in 12.11 seconds.
- Linux full JUnit: 1630 tests, 0 failures, 0 errors, 370.276 seconds. Project audit: 573 files, zero issues. License audit: 65 capabilities, zero issues.
- Legacy current release compared with clean Git `149362f`: 557 tracked paths, 10 hash mismatches, 130 extra files. Extras include `data/state.db`, compiled caches, and runtime hook cache.
- Because the legacy release cannot satisfy tracked-only attestation, no files were removed and it was not signed.
- Added and tested `prepare_bootstrap_release`: creates a signed/frozen tracked-only release from clean Git while leaving current symlink and systemd untouched.
- Deployment-focused local suite: 116 passed. Full local suite after this change: 1594 passed plus 37 subtests, 291.11 seconds.
- No production activation, restart, private-config rewrite, shared-database mutation, publisher call, or timer enable occurred in this step.

## 2026-09-04 P10 Bootstrap Safety Hardening (Local Only)

- Re-read the four coordination documents after interruption and confirmed the worktree contained only the registered bootstrap work; the interrupted full-test process was no longer running.
- Fault injection reproduced twelve unsafe or incomplete paths in the first bootstrap implementation: validation after path normalization, acceptance of dot/dot-dot release names, unintended default-key creation for a missing explicit key, concurrent target replacement/cleanup, and orphan attestation cleanup.
- The corrected implementation validates names and raw paths before side effects, fails closed for missing explicit keys, reserves the inactive target exclusively, and tracks ownership before cleanup.
- Negative tests prove that traversal and symlink inputs are rejected, invalid names create no files, foreign/concurrent targets survive, and metadata/freeze failures remove only the transaction's release and attestation while retaining prior rollback evidence.
- Bootstrap subset: `python -m pytest tests/test_deploy_release.py -k bootstrap -q --tb=short` => 16 passed, 23 deselected.
- Deployment/release focused suite: `python -m pytest tests/test_deploy_release.py tests/test_release_systemd.py tests/test_runtime_release_audit.py tests/test_operational_scripts.py -q --junitxml=artifacts/test-reports/p10-bootstrap-hardening-focused.xml` => 129 passed.
- Full suite: `python -m pytest -q --junitxml=artifacts/test-reports/p10-bootstrap-hardening-full.xml` => 1607 passed plus 37 subtests. JUnit records 1644 tests, zero failures, zero errors, zero skipped, 278.965 seconds.
- Project/privacy audit: 574 scanned files, zero issues. License audit: 65 capabilities, zero issues. `git diff --check` passed.
- Code inspection confirmed the deploy helper still fixes all `systemctl` calls to user scope, while the 2026-09-02 server refresh observed system-scoped production services. This is a separate activation blocker and is not waived by the bootstrap test result.
- No server file, release, symlink, service, timer, private config, shared database, publisher, or media provider was modified or invoked during this local milestone.

## 2026-09-04 Read-Only Resume Refresh And Scope Work

- SSH observation at 12:33 BJT: current remains `$RELEASES/unified-capability-v7-149362f`; mutable repository HEAD remains `6f4c88a`. Its tracked diff covers 17 files, 459 insertions and 36 deletions, with additional untracked files. No server checkout cleanup or overwrite was attempted.
- Image provider timestamp: August 30; film renderer: August 28; private config: August 30. Top-level `content_platform`/`scripts` scan found no files newer than September 2. These timestamps do not prove nested/private assets or file contents unchanged across all prior runs.
- Image provider SHA-256: `b86fc8f5b8f5eabd8053323cb5127bb3d6d9d39f5d3db5486bfeff50f6107940`; film renderer SHA-256: `ba850a4dc85d55c697ce4f20c3102018afa0345429f993e736ac1fc4f8582a31`.
- Gateway active; all 11 listed project timers disabled. Root filesystem 74% used, about 23 GB available. Staging remains `e1d6068`.
- System manager reports system-level unit fragments and expanded WorkingDirectory for the content service. The local verifier's literal `%h` comparison therefore remains a real activation blocker, not just a hypothetical test concern.
- Scope implementation routes deploy/rollback/query/acceptance to the requested manager and selects the matching CLI default unit directory. It does not yet resolve expanded runtime-path verification or gateway/private-config convergence.
- An earlier focused command named a nonexistent test file and ran zero tests; it is not accepted as evidence. The corrected suite used `tests/test_task9_canary.py` and passed 168 tests before two later tests; the systemd-only final subset passed 10 tests.
- No production service restart, symlink switch, config write, database mutation, publishing, or timer enable was performed during this refresh.
- Final scope regression: `python -m pytest -q --junitxml=artifacts/test-reports/p10-systemd-scope-full.xml` => 1612 passed plus 37 subtests, 285.26 seconds, exit 0. All five new scope tests are included in this full run.
- Project/privacy audit after documentation updates: 574 files, zero issues. License audit: 65 capabilities, zero issues. Diff whitespace check passed.

## 2026-09-04 Expanded Effective-Path Follow-Up

- Read-only SSH at 12:40 BJT confirmed unchanged current release, mutable HEAD, 17-file diff summary, and the two provider/renderer hashes above. Gateway active; all 11 listed timers disabled. Existing dirty work was left intact.
- Git porcelain status-list SHA-256: `3b996bb639e59f75c3e66b6a741311cf76d59af3e93b45266b047b6c6ab83427`. This hashes status/path listings, not file contents.
- Filtered systemd Environment output confirms expanded HOME/PYTHONPATH/data/secrets/config roots, but no explicit CONTENT_PLATFORM_CODE_ROOT or CONTENT_PLATFORM_RUNTIME_MODE for the content service. This does not inspect or disclose other environment values.
- Five failing tests reproduced rejection of valid expanded paths and inability to diagnose incorrect individual runtime roots. The fix uses exact parsed environment values and expanded deployment-home paths.
- A real checked-in module-based service template exposed a second bug: scraper environment paths triggered the ExecStart script check. Validation is now scoped to release-script ExecStart lines only.
- Focused command: `python -m pytest tests/test_release_systemd.py tests/test_deploy_release.py tests/test_runtime_release_audit.py tests/test_task9_canary.py -q --junitxml=artifacts/test-reports/p10-effective-paths-focused.xml` => 133 passed in 56.89 seconds.
- No production activation, mutable file overwrite, restart, database write, publishing, or timer enable occurred.
- Full local command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-effective-paths-full.xml` => 1617 passed plus 37 subtests, 283.41 seconds, exit 0. Privacy audit 574 files clean; license audit 65 capabilities clean.
- After checking staging had no dirty files, fetched the development branch and detached staging at `de506e2`. The private mutable checkout and current symlink were not altered.
- Linux command: `python3 -m pytest tests/test_release_systemd.py tests/test_deploy_release.py tests/test_runtime_release_audit.py -q --junitxml=$SHARED_DATA/release-evidence/p10-effective-paths-de506e2-linux.xml` => 97 passed in 5.55 seconds, exit 0.
- Linux project/privacy audit: 574 files, zero issues; license audit: 65 capabilities, zero issues. Staging Git status clean. Post-test current remains the v7 release and gateway is active.
- The new server writes were confined to isolated staging and the named test evidence output (plus ordinary test caches); no business DB, production config, current link, or service activation changed. Full Linux suite on this commit and real Canaries have not run.

## 2026-09-04 Real Config Preflight Blocker

- SSH refresh at 12:52 BJT: release and mutable HEAD unchanged; porcelain listing digest and two previously recorded script digests unchanged; gateway active. Local worktree initially clean at `cd9ca36`.
- Ran staging `_validate_runtime_config` read-only with explicit source/data/secrets roots; first failure: configured Agent-Reach bridge is outside release.
- Enumerated only script-valued configuration fields: Agent-Reach, Lux, and knowledge-card designer bridges are external Hermes paths and exist. Project video/image scripts use current release; legacy publisher script paths are subject to existing loader rewriting. Relative paths were not declared missing solely because they do not resolve from the SSH login directory.
- Read Agent-Reach bridge entrypoint: it delegates to agent-reach, mcporter/Exa, Jina/curl and gh. This is an external dependency boundary, not justification to bypass release-only validation.
- Added two red tests proving bootstrap and deploy previously ran expensive evidence commands before rejecting invalid config; implementation now preflights first and restores environment. The signed rollback fixture remains immutable in the tests.
- Focused command: `python -m pytest tests/test_deploy_release.py tests/test_release_systemd.py tests/test_runtime_release_audit.py -q --tb=short` => 99 passed in 54.30 seconds.
- No candidate build/signing, production config edit, tool removal, service restart, publish operation, or timer activation occurred. External bridge governance remains unresolved.
- Full local command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-config-preflight-full.xml` => 1619 passed plus 37 subtests, 273.90 seconds, exit 0. Project/privacy audit 574 files clean; license audit 65 capabilities clean.
