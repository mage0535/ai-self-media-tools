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

## 2026-09-04 External Bridge Trust Contract (Local Only)

- Added `external_runtime_dependencies_v1` validation for configured Python/shell bridges outside the immutable release. Required binding is dependency ID, `hermes_bridge` kind, full config key, exact path and SHA-256.
- Validation restricts paths to Hermes home, rejects symlink boundaries and missing/non-regular files, checks digest, and rejects duplicate or unconsumed records. Existing release-owned scripts retain the original release boundary check.
- Tests first demonstrated that a correct attestation was still rejected while unregistered/hash/key/symlink faults failed. After implementation, all four scenarios pass with only the correct contract accepted.
- Focused command: `python -m pytest tests/test_deploy_release.py tests/test_release_systemd.py tests/test_runtime_release_audit.py tests/test_operational_scripts.py -q --junitxml=artifacts/test-reports/p10-external-bridge-focused.xml` => 145 passed in 54.45 seconds.
- Full command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-external-bridge-full.xml` => 1623 passed plus 37 subtests, 284.78 seconds, exit 0.
- No private config or server bridge was changed during local implementation. Passing deployment validation will not be reported as runtime adapter execution or final-artifact impact.
- Linux staging fetched `ef39e15`; bridge/config-preflight subset passed 6 tests in 0.62 seconds. Three bridge SHA-256 values were measured without modifying those files.
- Created a private mode-600 candidate config copy under isolated staging, adding only the three external dependency attestations. The production config was not rewritten.
- Candidate preflight failed in 3ms on `media.image.script`: `$CURRENT_RELEASE/scripts/image_gen.py` resolved through the active symlink into the old release before candidate rebasing. It was correctly not treated as an external bridge.
- Added a failing stable-alias test and expanded `_rewrite_runtime_paths` to cover current-release aliases. The first full suite then found one real Canary regression because `load_config` inferred a default code root before Canary rebasing.
- Added optional explicit `code_root` to `load_config`; Task9 Canary now supplies its candidate root directly. Targeted deploy/CLI/Canary regression: 103 passed in 53.61 seconds.
- Final full command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-current-alias-fixed-full.xml` => 1624 passed plus 37 subtests, 286.97 seconds, exit 0. The earlier 1-failure full run is retained as root-cause evidence, not counted as passing.

## 2026-09-04 Signed Bootstrap Rollback Preparation

- Linux staging at `7bfa13c` passed 7 focused alias/bridge/config tests. The mode-600 private candidate config then passed real preflight in 10ms without modifying production config.
- Attempted tracked-only bootstrap from clean historical `149362f`. Full evidence produced JUnit 1565 tests with one failure: original-video media bridge expected four visual assignments but produced two. Project audit passed, but release evidence failed; no release directory was retained and current remained unchanged.
- The failed historical evidence is preserved under the named shared evidence directory. It is not accepted as a rollback and was not repaired by editing the historical source.
- Prepared `bootstrap-runtime-v8-7bfa13c-20260904` from clean staging using the same private candidate config. Result: prepared true, activated false, commit `7bfa13c7c10250678d466e5d089fc3b3958dfa39`.
- Bootstrap metadata records JUnit 1661 tests, zero failures/errors/skips. Release and metadata modes are 0555/0444. No config, state database, or secrets directory exists inside the release.
- Shared database remains inode 1642977, 63,143,936 bytes, 433 jobs. Current still points to the old v7 release; zero project timers are enabled; gateway remains active.
- First postcheck script assumed a nonexistent metadata key and failed with KeyError. The corrected schema-aware check produced the evidence above; the failed command is not counted as verification.
- `systemctl cat` confirms Hermes gateway is independently owned and has several existing drop-ins. No checked-in project gateway root drop-in exists, and effective gateway environment lacks project CODE_ROOT/CONFIG/DATA/SECRETS/production mode. Forward activation remains blocked.

## 2026-09-04 Gateway Runtime-Root Transaction (Local Only)

- Added a checked-in gateway environment drop-in containing current code/home/PYTHONPATH, private config, shared data, stable secrets and production mode. The deployment transaction writes only its named managed drop-in.
- Fault tests prove unrelated gateway drop-ins survive; an active gateway is restarted and effective assignments verified; an injected bad gateway environment restores the prior managed drop-in and current symlink.
- The first expanded focused run found two fixture hash failures because the new tracked file had inconsistent Windows checkout line endings. A first attempted LF normalization still differed from the test Git checkout; byte comparison isolated only this file. Restoring platform-consistent fixture writing made the two signed-release tests pass. Production hash checks were not weakened.
- Final focused command: `python -m pytest tests/test_release_systemd.py tests/test_deploy_release.py tests/test_runtime_release_audit.py tests/test_operational_scripts.py -q --junitxml=artifacts/test-reports/p10-gateway-dropin-focused-final.xml` => 148 passed in 54.91 seconds.
- Full JUnit `p10-gateway-dropin-full.xml`: 1663 tests, zero failures/errors/skips, 286.505 seconds; no Python test process remained afterward.
- Project audit then found one test-only literal private path. Replaced it with runtime `Path.home()` construction; `tests/test_release_systemd.py` => 17 passed in 6.61 seconds and project/privacy audit => 575 files, zero issues. License audit remained 65 capabilities, zero issues; diff check passed.
- No production gateway file, current link, content unit, private config, shared database or timer was changed by this local implementation.

## 2026-09-04 Candidate Private-Config Transaction (Local Only)

- Added optional active-config path to forward deployment. Candidate config remains the evidence input; release metadata is rebound to the stable active path and candidate hash before signing.
- Deployment promotes the candidate atomically after release freeze and before gateway/systemd switch. An outer failure handler restores the prior active config independently of systemd/current rollback.
- Two red tests first failed because the API did not exist. After implementation, ordering and byte restoration worked; POSIX mode assertions were then limited to non-Windows because Windows chmod cannot prove 0600/0640 semantics.
- Focused command: `python -m pytest tests/test_release_systemd.py tests/test_deploy_release.py tests/test_runtime_release_audit.py -q --junitxml=artifacts/test-reports/p10-private-config-focused.xml` => 108 passed in 65.35 seconds.
- Full command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-private-config-full.xml` => 1628 passed plus 37 subtests. JUnit 1665 tests, zero failures/errors/skips, 287.140 seconds.
- Project/privacy audit: 575 files, zero issues. License audit: 65 capabilities, zero issues. Diff check passed.
- No server candidate config promotion, gateway restart, current switch, DB mutation, publisher call or timer enable occurred in this local phase.

## 2026-09-04 Release Inventory And Rollback Ordering Review

- Linux `03b4b66` gateway/deploy suite passed 65 tests in 4.78s. Inactive signed bootstrap `bootstrap-runtime-v8-cad932c-20260904` prepared successfully from clean `cad932c` source after its full evidence run; earlier bootstrap remains intact.
- Installed unit comparison identified `ai-self-media-wechat-metrics.timer` missing from release. Its 07:20 Asia/Shanghai schedule targets WeChat metrics collection, not the generic Prometheus export service. Added the same definition to prevent unintended removal; did not enable it.
- Red test failed on missing timer; focused operational/systemd suite passed 62 tests in 9.58s. Full timer regression: 1629 passed plus 37 subtests, 293.31s, exit 0, JUnit `p10-wechat-timer-full.xml`.
- At 19:00 BJT, current still v7, gateway active, all 11 project timers disabled; mutable HEAD and status-list hash unchanged. Project/privacy audit 576 files clean, license 65 capabilities clean.
- Code review found configuration restoration after old-service restart in the nested failure path. This remains a blocking defect despite passing final-state tests; add startup-time assertions and repair ordering before activation.
- Added an assertion capturing config bytes when the recovery runner starts old gateway. Red result captured candidate bytes, conclusively reproducing incorrect ordering.
- Added a config-restore callback before old service state restoration; after successful restoration the outer handler does not restore again. Config restore failure skips all service starts/enables and surfaces rollback failure.
- Systemd subset passed 20 tests in 9.23 seconds, including failed config restore with no subsequent start/enable commands. This is simulated systemd evidence, not live service recovery.
- Full rollback-order command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-rollback-order-full.xml` => 1630 passed plus 37 subtests in 288.58s, exit 0.
- Clean Linux staging advanced to `ec08d1c`. `python3 -m pytest tests/test_release_systemd.py tests/test_deploy_release.py tests/test_operational_scripts.py -q --junitxml=$SHARED_DATA/release-evidence/p10-rollback-order-ec08d1c-linux.xml` => 109 passed in 5.92s, exit 0. Includes POSIX permission assertions; systemd runner is simulated, not live service switching.
- Post-test current remained v7 and gateway active. Production config/data/services and disabled timers were not changed. Full Linux candidate suite and actual forward/rollback rehearsal remain pending.

## 2026-09-04 Durable Release Config Snapshot (Local Only)

- Postchecked `bootstrap-runtime-v8-ec08d1c-20260904`: JUnit 1667 with zero failures and WeChat timer present, but metadata config path pointed to staging private config. It is not accepted as the final durable rollback.
- Added red tests showing bootstrap metadata did not persist a private snapshot and rollback lacked an active-config promotion interface. Both pass after implementation.
- Added failure cleanup, one-megabyte payload and injected partial `os.write` tests. The partial-write test first produced truncated bytes; implementation now loops until complete and fsyncs.
- Deployment and bootstrap create exclusive shared release config snapshots; release metadata uses the snapshot. Rollback requires target snapshots under the durable snapshot root when promoting a stable active config.
- Focused command: `python -m pytest tests/test_deploy_release.py tests/test_release_systemd.py -q --tb=short` => 70 passed in 51.92 seconds.
- Full command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-durable-config-snapshot-full.xml` => 1634 passed plus 37 subtests, 299.30 seconds, exit 0.
- Project/privacy audit: 576 files, zero issues. License audit: 65 capabilities, zero issues. Diff check passed.
- No production config promotion, current switch, service restart, database mutation, publisher call or timer enable occurred in this local phase.

## 2026-09-04/05 Durable Rollback And Failed Forward Activation

- Durable bootstrap `bootstrap-runtime-v8-ec08d1c-durable-20260904` prepared inactive. Metadata config path is under shared `release-configs`, mode 0600; JUnit 1667 tests, zero failures; WeChat timer and gateway drop-in present; metadata verification passed.
- Before forward activation, created a private pre-activation snapshot containing current/config hash+backup/DB inode+size+job count/gateway state/mutable status digest. No secret content was emitted.
- Forward `9734dd4` ran full JUnit but failed during live systemd transaction. Automatic rollback restored the old current, exact config hash and mode, gateway active, zero enabled timers, and shared DB inode 1642977/63,143,936 bytes/433 jobs. Managed gateway drop-in was removed.
- Journal records gateway stop at 19:55:20 and restart at 19:55:38. No failed systemd units remained. The original exception was lost with the SSH stream; an orphan 170-byte attestation remained while release/config snapshot were removed.
- Added red failure test proving orphan attestation and absent failure report. Implementation records private `release_failure_v1`, deletes only transaction-owned unchanged attestation/config, and retains original failure semantics.
- Focused command: `python -m pytest tests/test_deploy_release.py tests/test_release_systemd.py tests/test_runtime_release_audit.py tests/test_operational_scripts.py -q --junitxml=artifacts/test-reports/p10-release-failure-focused.xml` => 156 passed in 60.47 seconds.
- Full command: `python -m pytest -q --junitxml=artifacts/test-reports/p10-release-failure-full.xml` => 1634 passed plus 37 subtests, 282.71 seconds. Privacy 576 files and license 65 capabilities clean; diff check passed.
- Production remains on old v7 after rollback. No timer was enabled. The orphan attestation remains preserved until Linux verification and explicit failure-evidence archival.

## 2026-09-05 Second Activation Failure And Drop-In Governance

- Linux failure cleanup passed. Archived the first orphan attestation privately with SHA-256 `ba9d3ed1c6c2248ae5a040f6e2fbee99595bae2d7ddc139a8b6be4d286cd313e` before removing the active orphan.
- Second activation completed full evidence and switched current briefly, then failed because overnight supervisor effective CONTENT_PLATFORM_CONFIG was overridden by stale drop-ins. `release_failure_v1` preserved the exact error.
- Rollback restored old v7 current, active gateway and zero enabled timers; failed release, attestation and config snapshot are absent.
- Stale runtime override drop-ins coexist with valid Qwen TTS env, MemoryMax, recovery window and writer fallback settings. New selection removes only overrides of seven managed env variables, WorkingDirectory or ExecStart and restores them on failure.
- Focused suite: 158 passed in 61.38s. Full suite: 1636 passed plus 37 subtests in 279.00s. Privacy 576 files and license 65 capabilities clean.
- Production remains old v7. Third activation has not started.

## 2026-09-05 Successful Activation, Rollback, And Runtime Cache Finding

- Third activation from `4643ed0` succeeded after selective stale drop-in removal. Effective gateway had all seven runtime roots; stale codex/luna runtime drop-ins absent while Qwen TTS, writer fallback, memory and recovery-window drop-ins remained.
- Stable config mode 0600 matched signed snapshot hash. Shared DB remained inode 1642977, 63,143,936 bytes, 433 jobs. Gateway active, zero failed units, zero enabled project timers; MCP processes restarted under gateway.
- Corrected runtime-path probe (first used wrong field names and made no mutation) confirmed Hermes venv and CLI resolve current code, private config, shared data and the same shared database with production true.
- Real rollback to `bootstrap-runtime-v8-ec08d1c-durable-20260904` succeeded with systemd verified, active gateway, zero failed units and zero enabled timers.
- Forward activation of the signed `4643ed0` release was rejected before mutation because 3 `__pycache__` directories containing only `.pyc` files had appeared after root-run imports. Current stayed on durable rollback.
- Added `PYTHONDONTWRITEBYTECODE=1` to all 12 project services and gateway drop-in; exact environment verification and stale-dropin conflict fields include it. Five fixture failures were repaired by updating the minimal release fixture, not weakening production validation.
- Targeted systemd/operational/deploy suite: 115 passed in 45.25s. Full JUnit `p10-no-bytecode-full.xml`: 1673 tests, zero failures/errors/skips, 275.052s. Privacy 576 files and license 65 capabilities clean.
- The contaminated `4643ed0` release remains historical evidence and is not the final forward target. Production currently runs the durable `ec08d1c` rollback; timers remain disabled.

## 2026-09-05 Hermes MCP Child Environment And Final Activation

- Fresh server inspection found production on signed `b16d796`, gateway active and release cache-free, but Hermes private MCP config still declared only two child fields. This remained a latent recurrence path despite correct systemd environment.
- Red tests first failed because deployment exposed no `hermes_config_path`. TDD added atomic target-block promotion, exact-byte rollback before old gateway startup, rollback-path coverage and automatic CLI selection for real systemd switches.
- The implementation does not parse/rewrite the full private document and adds no dependency. It validates exact structural boundaries, replaces only the target env block, writes mode 0600 via atomic replace and rejects symlinks or ambiguous structure.
- Local focused deployment/systemd/operational suite: 160 passed. Final deploy/systemd subset after CLI default: 75 passed. Full command `python -m pytest -q --junitxml=artifacts/test-reports/p10-hermes-mcp-final-full.xml`: 1639 passed plus 37 subtests; JUnit 1676 tests, zero failures/errors/skips in 327.583s.
- Local project/privacy audit: 576 files, zero issues. License audit: 65 capabilities, zero issues. `git diff --check` passed. Commit `d79128c` was pushed before server mutation.
- Linux staging fetched detached `d79128c`; 161 deployment/systemd/operational tests passed in 7.97s. A read-only transformation against the real Hermes YAML reported eight expected env fields and unchanged source SHA.
- Pre-activation baseline: current `b16d796`; rollback package `bootstrap-runtime-v8-b16d796-20260905`; config mode 0600; shared DB inode 1642977, size 63,143,936, 433 jobs; zero enabled project timers; zero relevant failed units.
- Deployment created signed `production-runtime-v8-d79128c-20260905` and returned systemd verified plus Hermes MCP config verified. No timer was restored.
- Real rollback to the signed b16 bootstrap and forward activation back to d791 both returned verified. Private evidence records operation times and final release; system journal was retained.
- Final gateway entered active state at 17:40:14 CST with MainPID 2074498. `zz-no-proxy-union.conf` and loopback NO_PROXY remained effective; zero failed units and zero enabled project timers were observed.
- Exact argv/process inspection found MCP watchdog PID 2075148 and server PID 2075161, both with all eight production fields. `hermes mcp test content-platform` connected in 1709ms and discovered 22 tools.
- Final release contained zero `.pyc` and zero `__pycache__` after MCP startup. Shared DB inode/size/jobs remained 1642977/63,143,936/433. Hermes config mode remained 0600; 21 unrelated MCP entries and target enabled/timeout fields remained present.
- This closes runtime/MCP root convergence and byte-stability deployment. It does not close real media quality, live publisher postcheck, 12-platform Canary or timer-authorization gates.

## 2026-09-05/06 Platform Trend Routing And Production Evidence

- Commits `5661719`/`3c4ae0d` added automatic private cookie discovery, Playwright state conversion and per-platform lane queries. `bd291a7`/`13572ba` added bounded SPA waiting and X article/status-card parsing. Production X then collected eight real AI works over two direct queries; all had unique canonical status URLs, visible engagement and capture time.
- Search result parsing was hardened for TikTok and Zhihu. Zhihu staging collected 20 unique content URLs with positive visible votes and wrote two verified six-hour cache records. TikTok parsing is capable of recovering real `/@user/video/id` cards, but current direct/reload/US attempts all returned the platform's server-error page; no current TikTok work was fabricated.
- `deea9b2`/`438b123` classify transient errors, perform one bounded page reload and automatically load private proxy defaults. TikTok evidence records direct then US failure; Xiaohongshu records direct then CN, both ending at platform IP-risk/service errors. Public/no-cookie fallback was tested and required login.
- `26a3d09` added a strict private logged-search cache. Cache rows require same platform/query, canonical URL, positive engagement, captured time, strong source evidence, and matching text/screenshot SHA-256. Six-hour TTL, tamper, identity and contract failures are fail-closed. Two manually replayed TikTok snapshots parsed 6/7 unique works but were over 11 hours old; cache loading rejected them as expired and the two seed files were removed.
- `fdd3beb` added a real Kuaishou creator-backend collector. Live staging opened `https://cp.kuaishou.com/profile` with no login prompt and captured four current creation-inspiration signals. The 2026-09-06 official matrix has SHA-bound evidence; loader reports ready/valid/native=false and AI lane selection keeps only `ai工具` (15.6万人参与), rejecting unrelated general trends.
- `2fac194` connected the existing Video Channels collector. Live state resolved, but the platform redirected to `login.html`; `2f4f612` now classifies that exact final URL as login-required instead of layout drift.
- `2f4f612` connected the existing Douyin native hot-board API and fixed empty public-search semantics. Live direct API returned 50 rows. Neither AI-efficiency nor pet lane had a qualifying current row, so both report `no_lane_results`; generic `AI展现不了安徽的美` was correctly rejected. Public work pages returned no verified works and now report `no_verified_results` rather than `ok`.
- Other live same-lane results: Bilibili 12 verified works, Juejin 24, YouTube 2, WeChat public article search 20. WeChat rows have no public engagement values and therefore remain reference articles, not verified hot works. WeWrite returned 15 Baidu/Weibo/Toutiao general hot topics with no AI-lane match and was not treated as WeChat-native evidence.
- Consolidated current parameter pack contains 86 real samples: X 8, YouTube 2, Bilibili 12, Zhihu 20, Juejin 24, WeChat 20. Task9 input preparation improved from 4/12 to 6/12: ready are Kuaishou, Juejin, X, Bilibili, Zhihu and YouTube. Missing are WeChat, Douyin AI, Douyin pet, Video Channels, Xiaohongshu and TikTok, each with explicit evidence reasons.
- Final local suite for `2f4f612`: 1661 passed plus 37 subtests; JUnit 1698 tests, zero failures/errors in 302.060s. Project/privacy audit scanned 578 files with zero issues; license audit covered 65 capabilities with zero issues. Linux focused suite passed 103 tests before live platform checks.
- Signed release `production-runtime-v8-2f4f612-20260906` is current. Postcheck: gateway active since 12:43:44 CST (MainPID 2580740), MCP connected and discovered 22 tools, NO_PROXY loopback drop-in preserved, zero failed units, zero enabled project timers, zero release pyc, shared DB unchanged at inode/size/jobs 1642977/63,143,936/433.
- This milestone proves trend collection/routing improvements and truthful failure states. It does not prove 12/12 generated artifacts, real delivery postchecks, performance uplift, or timer readiness.

## 2026-09-07 Juejin Article Recovery Hardening (Local Only)

- Real server Canary v18 generated a title/body, cover and three section images. All four image semantic gates and the article media contract passed; Pipeline reached `review_required`.
- The safe Task9 publisher did not produce a real Juejin draft and no delivery claim was made. Manual review rejected the body because it contained `Skills.sh` split across lines, unsupported named-tool recommendations/rankings and `npx skills add` without verified evidence.
- Red/green regression proved the model-based humanizer previously accepted newly introduced unsupported claims. Commit `4b141c4` now normalizes and revalidates the candidate against both claim and hygiene gates, retains the accepted original on failure and records `humanize_rejected`.
- The same commit adds claim checks for unsupported named-tool recommendations and install commands, prevents article jobs from generating unrelated narration audio, and stops optional Agnes availability from failing a required artifact probe.
- Focused command covering Pipeline, claim ledger, Task9 Canary, platform policy and image/media behavior: 310 passed in 55.84 seconds.
- Full command `python -m pytest -q --junitxml=artifacts/test-reports/p10-content-recovery.xml`: 1699 passed plus 37 subtests in 297.08 seconds, exit 0.
- `python -m content_platform.cli project-audit`: ok true, 581 files, zero issues. License audit: 65 capabilities, zero issues. `git diff --check`: clean.
- These are local code/test results. Linux staging, refreshed v18 artifact probing, a clean v19 Juejin generation and real platform draft upload/readback remain pending; production release and timers were not changed.

## 2026-09-07 Juejin v19 Final-Copy Gate (Local And Staging Observation)

- Linux staging at `baff40e` passed the 310-test content/media subset in 242.77 seconds; project/privacy audit scanned 581 files with zero issues and license audit checked 65 capabilities with zero issues.
- Reprobing the existing v18 package with `baff40e` passed all probes; the earlier optional Agnes failure disappeared and 17 capability records passed. This repairs evidence semantics only and does not make the rejected v18 copy publishable.
- Fresh v19 used the dynamically discovered Hermes active model `opencode-go/mimo-v2.5`. It completed the first 7,617-character generation request in about 258 seconds, reached `review_required`, generated cover plus article images, omitted narration audio, and passed the current Pipeline/artifact probes.
- Manual copy inspection rejected v19 despite those green probes. It contained inline/malformed fences, comma-only YAML lines, broken `.agent`/`package.json` identifiers, unverified repository endorsements and unverified automatic-loading mechanism claims. Both old text gates had returned passed.
- Red/green tests reproduce those exact classes. Commit `3c5de37` repairs the deterministic formatting damage, expands claim validation, and applies a final automated prose-hygiene gate after factual repair. An ordering regression was caught: early prose blocking skipped the bounded factual repair, so the final gate was moved after factual repair while source-page contamination remains early.
- Focused regression after the ordering correction: 154 passed. Full `p10-final-copy-gate.xml`: 1702 passed plus 37 subtests in 299.65 seconds. Project/privacy audit 581/0; license audit 65/0; diff check clean.
- v19 was not sent to the real Juejin draft publisher. Commit `3c5de37` still requires Linux staging verification and a clean v20 real generation before any draft upload/readback.
- Offline staging re-evaluation repaired inline fences, comma-only YAML, `.agent` and `package.json`, and rejected the unverified repository endorsement. It also revealed that `SKILL.md` stopped the mechanism regex at its period; red/green follow-up `fd1e9c0` covers the exact v19 sentence and `.agent/skills` path. Focused 154 passed; full `p10-final-copy-gate-v2.xml` remained 1702 passed plus 37 subtests in 295.34 seconds, with privacy 581/0 and license 65/0.

## 2026-09-07 Juejin v20 Bounded Retry Evidence

- v20 ran on Linux staging `efa54fb` with dynamically discovered `opencode-go/mimo-v2.5`. Attempt one: prompt length 7,617, hard timeout at 420 seconds. Attempt two: prompt length 5,603, hard timeout at 180 seconds. Heartbeat transitions were recorded every 15 seconds; the second attempt began automatically.
- Final state was failed with `GenerationTimeoutError: Hermes hard deadline exceeded`. No artifact directory content, image generation or publisher invocation occurred. This is truthful timeout containment, not a completed content Canary.
- A new red test measured the retry at 6,638 characters under large platform/style/rule inputs. `b63547e` implements a retry-only minimal prompt and a 3,072-byte compiled-context cap; the test then passed below 4,000 characters while retaining topic, `claim_ledger` and the 1,200-1,800 character requirement.
- Focused generation/recovery/Pipeline suite: 139 passed in 44.82 seconds. Full `p10-compact-final-retry.xml`: 1703 passed plus 37 subtests in 298.66 seconds. Project/privacy audit 581 files and zero issues; license audit 65 capabilities and zero issues.
- Linux verification and a clean v21 are required. Production release, gateway roots, shared database and timers were not changed.

## 2026-09-07 Juejin v21 Source-Evidence And Structure Evidence

- Linux staging `6fa2d56` generation-recovery suite passed 49 tests. v21 dynamically used `opencode-go/mimo-v2.5`; the first 7,617-character attempt succeeded in about 236 seconds.
- v21 failed at article media with `article media requires at least three mapped sections`. No cover, section image or publisher call occurred. The body had only two readable H2 headings.
- The prior hotspot snapshot was only 600 bytes and contained a search-card title, URL, visible engagement and classification. It did not contain the technical facts needed for a tutorial.
- A read-only logged Playwright probe using the existing private Juejin state opened the source URL and extracted 8,657 visible characters. This confirmed source access but also confirmed that hot-work content must remain a structure/style reference unless technical facts are independently verified.
- `4ce550d` adds the technical fact-pack pre-generation gate, Task9 hash-bound source-claim contract, a three-H2 generation requirement and a final three-H2 Pipeline gate. Red/green tests cover insufficient/valid fact packs, source-claim SHA/excerpt binding and missing article sections.
- Focused suite: 184 passed in 48.92 seconds. Full `p10-technical-fact-pack.xml`: 1707 passed plus 37 subtests in 297.13 seconds. Project/privacy audit 581/0; license audit 65/0; diff check clean.
- Next: Linux verification, build a new private v22 input with Agent Skills primary-source snapshots and at least three verified claims, then run a fresh Juejin Canary. Production and timers remain unchanged.

## 2026-09-07 Task9 Production-Admission Bypass Closure

- A direct production-mode preflight comparison exposed that standalone Task9 runs inherited no `CONTENT_PLATFORM_RUNTIME_MODE`; `validate_pre_generation` therefore returned `skipped=true`. Production config paths do not activate that environment gate.
- Red test instrumented Pipeline creation and observed no runtime mode. Commit `6bcdcaa` sets `production` around the complete `_run_pipeline_case` transaction and restores the previous value in `finally`; green test observes production and no leaked variable afterward.
- Related Task9/pre-generation/Pipeline suite passed 139 tests. Full `p10-canary-production-admission.xml`: 1708 passed plus 37 subtests in 303.40 seconds. Project/privacy audit 581 files with zero issues; license audit 65 capabilities with zero issues.
- A private v22 input root was prepared from the prior Juejin hotspot evidence. It adds the official `agentskills.io/specification.md` snapshot, mode 0600, SHA-256 `2b1dbb4fd80c31748d15812c4ebd3e66c09383d0c792801f617718684489e40d`, and five Chinese claims each bound to an exact official English excerpt. No credentials or source body entered Git.
- The v22 generation has not yet run under `6bcdcaa`. Production release, gateway, shared database and timers remain unchanged.

## 2026-09-07 Juejin v22 Production-Admission Result

- Linux Task9/admission suite at `f178071` passed 74 tests. v22 then loaded five hash-bound official Agent Skills facts and the `validate_pre_generation_contract` step succeeded under production runtime mode.
- Hermes dynamically selected `opencode-go/mimo-v2.5`. Attempt one used an 8,035-character prompt and succeeded in about 188 seconds. No retry was needed.
- The final text-hygiene gate blocked `malformed_quotes` before media. No cover, section image, audio or publisher call occurred. This is correct fail-closed behavior.
- The block exposed that Pipeline had not saved the full candidate before raising, so the database retained empty title/body and only the workflow's compact 700-character excerpt. `a162adb` persists complete blocked candidates and gate metadata first.
- Red/green tests also cover safe removal of one unmatched straight quote outside fenced code while preserving `print("keep me")` inside code. Focused suite: 166 passed. Full `p10-blocked-draft-recovery.xml`: 1709 passed plus 37 subtests in 300.50 seconds; privacy 581/0 and license 65/0.
- v23 must verify full-copy persistence or successful normalization plus production admission, media and artifact probes. Production release and timers remain unchanged.

## 2026-09-07 Juejin v23 Final-Heading Media Evidence

- Linux blocked-draft/Pipeline subset at `c848eba` passed 117 tests in 262.08 seconds. v23 used the live Hermes `opencode-go/muse-spark-1.3-contributor` identity and completed its first 8,035-character generation attempt in about 191 seconds.
- Production admission, official five-claim fact pack, final copy hygiene, claim gate, content depth and three-H2 structure passed. No independent narration was generated.
- Cover passed on its first attempt. Section 02 and 03 eventually passed. Section 01 failed three semantic attempts: two generic people/office images and one deterministic interface graphic; all expected `repetitive task loop`, which came from stale opening-fragment metadata rather than the final heading.
- `6516e55` changes `normalize_article_sections` to parse final body headings before generator metadata. The red test supplied three stale metadata titles plus three final headings and observed stale selection; green returns exactly the final headings.
- Focused article media tests: 7 passed. Related media/Pipeline set: 241 passed. Full `p10-final-section-mapping.xml`: 1710 passed plus 37 subtests in 306.55 seconds; privacy 581/0 and license 65/0.
- v23 was not delivered. Linux verification and a clean v24 remain required; production release and timers were unchanged.

## 2026-09-07 Juejin v24 Verified-Source Rendering Evidence

- Linux article-media regression at `2fb8f2c` passed 104 tests. v24 passed production admission, official fact pack, final text/claim/depth/three-H2 and platform gates, then blocked at required quality because GEO was 30.
- Independent GEO recomputation reported: direct answer true, short paragraphs true, source false, structured list false, authority quote false, numeric false, FAQ false. The claim ledger nevertheless contained six verified rows and two unique public source URLs.
- `13c4634` deterministically appends `## 参考来源` with one sanitized Markdown bullet per unique verified HTTP(S) URL. It neither adds unsupported facts nor exposes evidence paths.
- Unit and Pipeline tests prove URL dedupe, private-scheme rejection and GEO recognition of both source and structured-list dimensions. Related suite: 174 passed. Full `p10-verified-source-appendix.xml`: 1712 passed plus 37 subtests in 307.75 seconds; privacy 581/0 and license 65/0.
- v24 generated no media and was not delivered. Linux verification and v25 remain required; production release and timers were unchanged.

## 2026-09-07 Juejin v25 Fragment-Precision Evidence

- Linux source/GEO/Pipeline subset at `d3e5872` passed 112 tests in 248.47 seconds. v25 completed generation quickly and persisted its full candidate.
- It blocked before GEO and media only because `跑顺一个，再做下一个。` matched the prior broad classifier-ending fragment rule. No media or delivery occurred.
- Red/green `600a011` accepts that complete parallel action while continuing to reject `这只是一个。` and the existing English dangling-article example.
- Focused suite: 158 passed. Full `p10-chinese-fragment-precision.xml`: 1713 passed plus 37 subtests in 307.44 seconds. Project/privacy audit 581/0; license audit 65/0.
- Linux verification and v26 remain required; production release and timers were unchanged.

## 2026-09-07 Juejin v26 Deterministic Visual Diversity Evidence

- Linux hygiene/Pipeline subset at `1155431` passed 80 tests in 253.58 seconds. v26 passed copy, source, GEO and platform gates and entered article media.
- It failed with `article media contains duplicate asset checksums`. Checkpoint evidence showed section 02 and 03 both SHA `a12b2590...`; cover background had the same SHA. All were `deterministic_editorial_v1` workflow layouts despite distinct final headings.
- The final body also retained `SKILL.\nmd` because the old `\b` extension boundary failed between ASCII and Chinese word characters.
- `91adeec` adds `document_anatomy` and `resource_stack` layouts, routes on title/subtitle plus concepts, adds lock-protected per-asset checksum claims/retries, persists duplicate retry evidence, and corrects ASCII boundaries for technical filenames.
- New red/green tests cover all three defects. Related suite: 263 passed. Full `p10-deterministic-visual-diversity.xml`: 1716 passed plus 37 subtests in 314.67 seconds; project/privacy audit 581/0 and license 65/0.
- v26 was not delivered. Linux verification and v27 remain required; production release and timers were unchanged.

## 2026-09-07 Juejin v27 Heading-Preservation Evidence

- Linux deterministic-visual/media subset at `f9f3655` passed 126 tests. v27 produced a final body with three content H2 headings plus a verified references appendix.
- Media normalization returned two sections because it merged all three short/question headings into one and kept `参考来源` as the second. Article media failed before provider calls; no delivery occurred.
- Red/green `adca5ef` keeps the three content headings distinct and excludes references headings. Existing heading-and-body-on-one-line and metadata fallback tests remain green.
- Focused article media: 9 passed. Related suite: 264 passed. Full `p10-article-heading-preservation.xml`: 1717 passed plus 37 subtests in 313.14 seconds; project/privacy audit 581/0 and license 65/0.
- Linux verification and v28 remain required. Production release and timers were unchanged.

## 2026-09-07 Juejin v28 Machine Pass And Manual Review Evidence

- Linux heading/media subset at `bfb7ca7` passed 39 tests. v28 reached `review_required` with Pipeline passed, artifact probe passed and no probe failures.
- Verified gates: claims passed with six ledger rows; content hygiene passed; GEO 90; quality 8/8; Juejin platform 13/13; media contract passed. Four role image SHA-256 values were unique and no audio file existed.
- Machine-green was not accepted for delivery. Manual review found Unicode YAML delimiters, split numbered-list text, unsupported Agent routing descriptions and mixed section-image ratios. The safe Task9 receipt remained a local boundary, not a real draft ID.
- `7eac44d` converts all findings into red/green tests and minimal implementation: formatting repair, expanded technical mechanism validation and atomic 1200x800 section normalization before semantic evidence.
- Related suite: 267 passed. Full `p10-final-copy-media-polish.xml`: 1720 passed plus 37 subtests in 304.56 seconds. Project/privacy audit 581/0; license audit 65/0.
- v29 is required before any real draft upload. Production release and timers remain unchanged.

## 2026-09-07 Juejin v29 Reader-Facing Review Evidence

- Linux final-copy/media subset at `212c9bf` passed 79 tests. v29 reached `review_required`; Pipeline and artifact probe passed with no failures.
- Three section images are all 1200x800 and have unique SHA-256 values; cover is 1800x1200; no MP3/WAV exists. Capability probe passed 17 records and media asset pipeline reached artifact verified.
- Manual review found joined H2/prose lines and internal source labels. It did not find the v28 Unicode YAML/list defect because the new draft contained no such block.
- `72f76e5` adds constrained heading/prose splitting and reader-facing source labels. Red/green focused tests passed; related 192 passed. Full `p10-reader-facing-article-copy.xml`: 1722 passed plus 37 subtests in 313.97 seconds; privacy 581/0 and license 65/0.
- v29 remains a safe local Task9 package, not a real Juejin draft. Linux verification and deterministic offline revalidation are next; production and timers were unchanged.

## 2026-09-08 Juejin v30 Claim-Coverage Evidence

- Linux reader-facing content/Pipeline subset at `2b4de36` passed 117 tests with zero failures/errors in 251.248 seconds.
- v30 dynamically followed Hermes back to `opencode-go/mimo-v2.5`. Generation succeeded and media began, but cover semantic validation failed three attempts. No delivery occurred.
- The generated body contained unsupported token counts, an approximate client count/support list, no-fee/no-registration promises and a split `agentskills.io` domain. The stored and freshly recomputed claim gate incorrectly passed because these syntax variants were not recognized.
- `c16d943` adds exact v30 red/green tests for token/count modifiers, reverse product attribution, Chinese promotional promises and source-URL domain restoration.
- Related suite: 165 passed. Full `p10-v30-claim-coverage.xml`: 1724 passed plus 37 subtests in 306.58 seconds. Project/privacy audit 581/0; license audit 65/0.
- v30 is rejected. Linux verification and one final fresh Juejin run are required; production release and timers remain unchanged.

## 2026-09-08 Juejin v31 Technical-Fact Coverage Evidence

- Linux v30 claim/Pipeline subset at `4cafb41` passed 102 tests in 238.76 seconds. v31 dynamically used `opencode-go/mimo-v2.5` and produced a machine-green package.
- Manual review rejected v31: advanced-engineer workflow and quality uplift claims, spec-driven-development phases, Chrome/Google derivation, slash commands, repository/license and instant-install claims were outside the official fact pack. Existing claim recomputation still returned passed.
- `9b0a75c` adds deterministic technical-anchor coverage and red/green examples for a grounded directory/SKILL.md paraphrase, explicit advice and unsupported engineering-workflow assertions. Initial related regression exposed imperative-advice false positives; the exemption was narrowed to explicit instruction starters while declarative claims remain checked.
- Related suite: 154 passed. Full `p10-technical-fact-coverage.xml`: 1725 passed plus 37 subtests in 301.43 seconds. Project/privacy audit 581/0; license audit 65/0.
- v31 remains rejected and was not sent to the Juejin publisher. Linux/offline re-evaluation is next; production and timers were unchanged.

## 2026-09-08 Grounded Technical Rebuild Evidence

- Linux technical fact/Pipeline subset at `744aaa7` passed 103 tests in 245.26 seconds. Re-evaluating v31 produced eight unsupported technical facts, including its title, workflow/quality assertions, phases, slash commands and repository/license claim.
- Deterministic sentence deletion yielded an empty title and a 1,509-character body with broken numbering, empty code blocks and unsupported residual claims. It was not accepted.
- `6e6bb36` adds `build_grounded_technical_article` and a Pipeline branch that rebuilds from verified primary claims, records the trigger/count, recompiles cover direction and reruns claim gates.
- Red/green tests prove non-primary hot-work text is excluded, the result has four H2 sections and passes claim validation; Pipeline test proves the unsupported generated title/body are replaced.
- Related suite: 191 passed. Full `p10-grounded-technical-rebuild.xml`: 1727 passed plus 37 subtests in 315.88 seconds. Project/privacy audit 581/0; license audit 65/0.
- Linux verification and a deterministic recovery package remain pending. Production release and timers were unchanged.

## 2026-09-08 Juejin v32 Grounded-Rebuild Hygiene Evidence

- Linux grounded-rebuild/Pipeline subset at `5e8337a` passed 105 tests in 251.24 seconds. v32 used live `mimo-v2.5`; the initial draft failed multiple factual codes and Pipeline invoked the five-claim `verified_primary_claims_v1` rebuild.
- Rebuilt title/body and claim gate were correct, but repeated section boilerplate triggered both repeated paragraph and repeated sentence. No media or delivery occurred.
- `1b3d6a9` consolidates the evidence-boundary sentence and requires the deterministic rebuild to pass `validate_generated_text` in addition to `validate_claims`.
- Related suite: 156 passed. Full `p10-grounded-rebuild-hygiene.xml`: 1727 passed plus 37 subtests in 297.63 seconds. Project/privacy audit 581/0; license audit 65/0.
- Linux deterministic recovery validation remains pending; production and timers were unchanged.

## 2026-09-08 Juejin v33 Provider Authentication Evidence

- Staging advanced cleanly to `9fadd9e`; grounded builder/Pipeline focused tests passed 2 tests with zero failures.
- v33 discovered live `opencode-go/muse-spark-1.3-contributor` and ended with `ProviderAuthError: provider_auth_failed` before draft generation. Artifact probe reported missing cover/capability evidence because no artifact stage ran.
- Fresh server check confirms current production is still signed `production-runtime-v8-2f4f612-20260906`, staging is `9fadd9e`, gateway is active and both overnight timers are inactive.
- No model setting, production release, shared database, timer or publisher was changed. Next work is deterministic end-to-end recovery/media validation independent of live model availability.

## 2026-09-08 Juejin v34b Grounded-Depth Evidence

- A deterministic recovery run reused the complete v31 draft metadata and the private five-claim Agent Skills specification pack. It did not call Hermes, change its active model or touch production.
- The rebuilt draft passed claim validation, final text hygiene, GEO, growth and all Juejin platform dimensions except `base_article_quality.body_length`. The old builder produced only 513 effective characters in the unit fixture, below the production range of 1,200 to 3,000, so media and delivery correctly remained closed.
- Red test added the actual `validate_article_packet` body-length assertion. Commit `46b1616` expands only the deterministic fallback with clearly marked task-framing, resource-planning, execution-review and verification advice; verified primary claims remain the only factual assertions.
- Local related command covering claim, Pipeline and media/platform quality returned 175 passed. Full `artifacts/test-reports/p10-grounded-rebuild-depth.xml` returned 1727 passed plus 37 subtests in 300.59 seconds. `python -m content_platform project-audit` scanned 581 files with zero issues; `python scripts/license_audit.py` checked 65 capabilities with zero issues; `git diff --check` passed.
- Linux staging validation and v34c remain pending. Production stays on signed `2f4f612`; timers remain disabled and no real Juejin publisher call has been made.

## 2026-09-08 Juejin v34c Image-Semantic Evidence

- Staging fast-forwarded cleanly to `9245ccd`. Linux grounded builder/Pipeline tests passed 2/2 in 7.23 seconds and `python3 -m content_platform project-audit` scanned 581 files with zero issues.
- v34c used a new private directory and the recorded v31 draft plus verified five-claim pack. It made no model call. The rebuilt copy passed every pre-media content and platform gate, proving the 1,200-character depth correction in the real Pipeline.
- The run failed closed at cover semantics after three attempts. Attempt one was a robot at a desk, attempt two was a game-like screenshot collage, and attempt three was a dark-blue numbered INPUT/SKILL/VERIFY modular playbook. Vision evidence was hash-bound; the third candidate matched the playbook concept but not the workflow-node phrase and scored 0.425 against 0.6.
- Section flowchart candidates showed the same deterministic vocabulary gap; one matched two requested concepts but scored 0.591667. Failed candidates, captions, scores and SHA-256 values remain under the private v34c evidence directory.
- Red/green `8ec883d` models node/card/rectangle as one visible module concept. The exact modular-playbook fixture now passes and a generic robot-office fixture remains below threshold with no matches. Related tests: 39 passed. Full `artifacts/test-reports/p10-visible-workflow-semantics.xml`: 1728 passed plus 37 subtests in 307.96 seconds. Project/privacy 581/0 and license 65/0.
- Production remains signed `2f4f612`; gateway and timer state were not changed. A fresh v34d is required before copy/media acceptance.

## 2026-09-08 Juejin v34d Section-Routing Evidence

- Linux positive/negative workflow-semantic tests at `06057a6` passed 2/2. v34d then completed its cover after the intended retries, so the prior cover false negative no longer terminated the run.
- All three sections still received abstract H2 text as a third expected concept. Relevant AI-agent/playbook flowcharts matched two concepts but scored 0.591667 against 0.6; generic robot and office attempts scored lower or zero and remained rejected.
- `f5e5cd7` makes the grounded H2 subjects visibly testable and adds route/score tests for directory trees, resource documents and on-demand loading. Ordinary office imagery is an explicit negative control.
- Related tests returned 128 passed. Full `artifacts/test-reports/p10-grounded-section-visuals.xml` returned 1730 passed plus 37 subtests in 301.85 seconds. Project/privacy audit scanned 581 files with zero issues; license audit checked 65 capabilities with zero issues.
- v34d was not delivered. Production, gateway configuration, shared state and timer state were unchanged. Linux staging and a new v34e remain required.

## 2026-09-08 Juejin v34e Final-Layout Evidence

- Linux grounded heading/routing/score tests at `29103f4` passed 3/3. v34e then completed three of four required assets: cover score 0.7875, section 01 score 0.7875 and section 03 score 0.775.
- Section 02 expected only `structured skill directory documents`. Provider attempts produced generic cards and an office; the deterministic third attempt produced three unlabeled-looking bars because the renderer reused cover copy and selected `verification_dashboard`. All three correctly remained below the semantic gate.
- `0f3ee1c` adds one renderer-copy selector and aligns deterministic layout/analyzer vocabulary with compiled directory/loading concepts. Tests cover layout selection, section-vs-cover copy, visible SCRIPTS/REFERENCES/ASSETS scoring and an office negative.
- Focused regression returned 117 passed. Full `artifacts/test-reports/p10-section-render-routing.xml` returned 1732 passed plus 37 subtests in 295.08 seconds. Project/privacy audit 581/0 and license audit 65/0.
- v34e was not delivered. Production remains signed `2f4f612`; gateway configuration, shared data and timers were unchanged. A fresh v34f remains required.

## 2026-09-08 Juejin v34f Manual-Review Evidence

- Linux final-layout tests at `e68e3c3` passed 3/3. v34f reached `review_required` with Pipeline and artifact probes passing and no reported failures. Body length was 1,706 characters and machine quality/platform gates passed.
- Asset evidence: cover 0.825, section 01 0.7875, section 02 0.8 and section 03 0.775; all four SHA-256 values were unique. Manual inspection accepted the first three semantics but rejected section 03, which showed three people talking in an office and no loading action.
- Full section-03 caption explicitly said there were no papers on the table. The bag-of-words scorer canonicalized `papers` as a document/archive token and matched `selective document loading sequence` despite no loading anchor. The title and first body line also retained unsupported hot-title language and mechanical repetition.
- `522e13d` adds exact red/green fixtures for the negated-paper caption and grounded fallback title/hook. Related tests: 135 passed. Full `artifacts/test-reports/p10-v34f-manual-review.xml`: 1732 passed plus 37 subtests in 308.32 seconds. Privacy 581/0; license 65/0.
- v34f is rejected and was never sent to the real Juejin publisher. Production and timers remain unchanged. A fresh v34g is required.

## 2026-09-08 Juejin v34g Accepted Recovery Evidence

- Staging fast-forwarded to `cc71400`; Linux false-positive/title/Pipeline tests passed 3/3 in 7.71 seconds. v34g used a fresh private directory, the recorded rejected v31 draft and the five SHA-bound primary claims. It did not call Hermes or any real publisher.
- Pipeline state is `review_required`; Pipeline probe and artifact probe both passed with zero failures. The title is `Agent Skill 入门：一份来源核对清单`, body length is 1,700, machine quality and platform gates pass, and all required capability records are complete.
- Artifact-bound semantic scores: cover 0.8375, section 01 0.7875, section 02 0.8 and section 03 0.775. Manual review verified their distinct purposes: modular workflow cover, directory/playbook, categorized resources and explicit on-demand sequence.
- Pillow decode/dimension review: cover 1800x1200; each section 1200x800. Four SHA-256 values are unique. Audio inventory is empty. Private `manual-review.json` records `passed=true` and `publisher_called=false`.
- v34g is accepted only as the Juejin deterministic-recovery Canary. Production remains signed `2f4f612`, the gateway configuration is unchanged and both overnight timers remain disabled. Current-model and remaining platform Canaries are still pending.

## 2026-09-08 Hermes Region-Proxy Evidence

- Read-only active config reported `default: muse-spark-1.3-contributor`, provider `opencode-go`; no project code hardcodes it. `hermes -z 'Return exactly: HERMES_MODEL_OK' --cli` returned a country HTTP 403 yet exited zero.
- `hermes-proxy-toggle status` showed the gateway process using the US SOCKS route. The standalone SSH environment had no proxy variables. Repeating the minimal CLI probe with explicit HTTPS/ALL proxy returned exactly `HERMES_MODEL_OK`.
- The actual overnight service loads its private `proxy.env`; only key names `CN_PROXY` and `US_PROXY` were inspected, not values. Therefore code can perform direct-first fallback without making all platform traffic proxied.
- `4403eb8` adds RegionError classification and one proxy-scoped retry. Tests prove the second process receives proxy variables, neither command contains model/provider overrides, attempt evidence records `provider_region_failed` without the proxy value, and generic key rejection is not retried.
- Focused generator/batch tests returned 88 passed. Full `artifacts/test-reports/p10-hermes-region-fallback.xml` returned 1734 passed plus 37 subtests in 313.69 seconds. Project/privacy audit 581/0; license audit 65/0. Linux real DraftGenerator validation remains pending.

## 2026-09-08 Juejin v35 Real-Model Evidence

- Linux proxy tests at `4ae1952` passed 2/2. A complete real `DraftGenerator.generate` probe, with HTTPS/ALL proxy unset and only private `US_PROXY` exported, returned a normalized 227-character result. Attempts were exactly `provider_region_failed` then `success`; prompt hash remained unchanged.
- v35 then used the active `opencode-go/muse-spark-1.3-contributor` via the same direct-first recovery. The first regional failure took about 13 seconds; the proxied 8,035-character generation succeeded in about 82 seconds with regular 15-second heartbeats.
- Generated unsupported numeric and technical mechanism claims triggered the five-primary-claim deterministic rebuild. Media failed because section 02 claimed deterministic resource-stack SHA first; section 01 and section 03 independently reached the same SHA on their third attempts and were rejected as duplicates.
- `0f104b6` adds a separate selective-loading layout and correct document-vs-resource precedence. Related tests: 36 passed. Full `artifacts/test-reports/p10-distinct-fallback-layouts.xml`: 1735 passed plus 37 subtests in 297.15 seconds. Project/privacy audit 581/0; license audit 65/0.
- v35 was not delivered. Production remains signed `2f4f612`, timers remain disabled and a fresh real-model v35b is required.

## 2026-09-08 Juejin v35b Specific-Concept Evidence

- Linux distinct-layout tests at `94768c7` passed 2/2. v35b recorded the same active-model regional recovery and completed the proxied 8,035-character generation in about 83 seconds.
- Verified-primary rebuild activated. Cover completed; section 02 completed with the resource layout and section 03 completed with a distinct selective-loading SHA. No duplicate checksum failure occurred.
- Section 01 failed after three semantic attempts. The first two visibly contained notebook/files and matched only `structured skill directory documents`; the third visibly contained SKILL.md, YAML FRONTMATTER and MARKDOWN INSTRUCTIONS but matched only generic playbook. Requiring both concepts made all valid candidates fail.
- `8f9770a` selects the specific directory concept and extends observable directory synonyms to the document-anatomy labels. Related tests: 136 passed. Full `artifacts/test-reports/p10-specific-section-concepts.xml`: 1735 passed plus 37 subtests in 292.13 seconds. Privacy 581/0; license 65/0.
- v35b was not delivered. Production and timers remain unchanged; a fresh v35c is required.

## 2026-09-08 Juejin v35c Accepted Real-Model Evidence

- Staging specific-concept tests at `5545dc7` passed 2/2. v35c used the dynamically active `opencode-go/muse-spark-1.3-contributor`: direct attempt recorded `provider_region_failed`, proxy-scoped retry retained prompt hash `c7bc5b...` and succeeded in about 65 seconds.
- The generated draft contained unsupported technical mechanism claims, so the five-primary-claim rebuild activated. Final title/body were the safe 1,700-character grounded version. Pipeline and artifact probe passed with zero failures and all 17 required capability records complete.
- Artifact semantic scores: cover 0.825, section 01 0.8, section 02 0.8, section 03 0.85. Manual review verified a modular cover, directory graph, resource stack and separate on-demand loading sequence.
- Pillow decode/dimension review recorded cover 1800x1200 and three 1200x800 sections. Four SHA-256 values are unique. Private `manual-review.json` records `passed=true`, `model_call=real_active_model`, empty audio and `publisher_called=false`.
- Juejin v35c is accepted as the real-model content/media Canary, not live draft proof. Production remains signed `2f4f612`; gateway config and timers are unchanged. WeChat source readiness is the next blocker.

## 2026-09-08 WeChat Source-Provenance Evidence

- A bounded read-only backend collection used the existing private Playwright state and returned `status=login_required`, reason that the backend requires scan login, and zero records. No account setting or publication state changed.
- The latest Sogou WeChat search pack contained 20 rows but `strong_sample_count=0` and `ready=false` because no row carried a qualifying view/like/favorite/engagement metric.
- Absolute WeWrite 4.2.1 was present despite not appearing in non-interactive PATH. Live `hotspots --limit 20` completed successfully but declared sources Weibo, Baidu and Toutiao; examples used those hosts and therefore are not WeChat official signals.
- Red test proved such a Weibo row was previously accepted. `77ea76f` now rejects it with `wechat_first_party_url_required`; valid `mp.weixin.qq.com` rows still pass. Focused suite returned 24 passed plus 4 subtests.
- Full `artifacts/test-reports/p10-wechat-first-party-source.xml` returned 1736 passed plus 37 subtests in 307.11 seconds. Project/privacy audit 581/0; license audit 65/0. WeChat Canary remains source-blocked and was not generated or published.

## 2026-09-08 WeChat Evergreen-Compiler Evidence

- Read-only inspection of the private overnight slots found two WeChat schedule rows with stage/estimate/weekdays only and no `editorial_fallback`. No private configuration was changed.
- The checked-in WeChat recovery playbook already requires a 14-day topic and title-frame dedupe, column rotation, low frequency and explicit factual boundaries. `6b336ec` adds four advice-only fallback topics with stable directions and columns.
- Red/green tests prove three empty recapture rounds produce one `ready_for_plan` editorial row; strategy source is preserved in bounded model input; no hotspot identity exists; all-reserved topics block; and absence of a requery adapter cannot bypass collection.
- Related tests returned 78 passed. Full `artifacts/test-reports/p10-wechat-evergreen-fallback.xml` returned 1739 passed plus 37 subtests in 341.78 seconds. Project/privacy audit 581/0; license audit 65/0.
- Linux prepare-only verification and a WeChat content/media/draft-safe Canary remain pending. Production and timers remain unchanged.

## 2026-09-08 WeChat v2 And Intelligence Expansion Evidence

- Linux prepare-only v2 used the real compiled WeChat strategy SHA and produced `ready_for_plan`, three zero-candidate research rounds, editorial evidence and no associated hotspot. Bounded input contained six content pillars and six structures.
- WeChat content v2 used the active Hermes model for its initial draft. WeWrite `llm-write` returned HTTP 400; explicit Hermes writer then recorded direct and US-proxy routes with return code zero and produced 2,074 characters. Final writer gate recorded `passed=true, writer=hermes_writer`.
- The 1,953-character article was readable and growth gate passed, but old WeChat quality logic required GitHub project/dual-channel fields plus unavailable same-lane/cross-platform samples for every article. No media or publisher call occurred.
- `9c819aa` adds mode-aware gates and packet fields. `df736e6` adds `platform_intelligence_registry_v1`, registry loaders, aggregate/reference adapters and deterministic multi-factor scoring. Tests prove all 12 delivery targets have collectors/queries and 11 reference sources remain cross-platform only.
- Full `artifacts/test-reports/p10-expanded-intelligence-registry.xml` returned 1749 passed plus 37 subtests in 357.30 seconds. Project/privacy audit scanned 586 files with zero issues; license audit checked 65 capabilities with zero issues.
- Linux live registry/aggregate smoke and WeChat v3 remain pending. Production stays signed `2f4f612`; timers remain disabled.

## 2026-09-08 Intelligence Reference-Integrity Evidence

- Linux registry tests at `fc5da22` passed 5/5. An initial adapter smoke returned WeWrite aggregate 20, CSDN 5 and Dev.to 3, but direct inspection showed the latter two were synthetic `source_fallback` rows with empty URLs, not real collection.
- The same smoke showed 17 parameter-pack platform keys because observed reference platforms were unioned with publishing targets. WeChat correctly remained not ready, but target/reference storage was not clean enough.
- `8e36bb7` adds platform and unavailable identity to synthetic fallbacks and fixes the default pack to 12 publishing targets. Tests prove reference observations cannot create new target keys or readiness.
- Full `artifacts/test-reports/p10-intelligence-reference-integrity.xml` returned 1750 passed plus 37 subtests in 357.97 seconds. Project/privacy audit 586/0; license audit 65/0.
- A corrected Linux smoke using the official collector report remains pending. Production and timers were not changed.

## 2026-09-08 WeChat v3-v4 And Live Collector Evidence

- Official Linux `TrendCollector.collect_with_report` returned 12 sources: 7 ok, 5 degraded, 0 failed, 135 deduplicated rows. WeWrite aggregate returned 30; CSDN returned eight real URL rows; 36Kr/Reddit/Product Hunt/Dev.to/Medium synthetic fallbacks were correctly degraded.
- Resulting parameter pack contained exactly 12 publishing targets. WeChat was not ready; eight cross-platform references were ranked with explicit dimensions and all had `target_ready_eligible=false`.
- WeChat v3 produced a 2,009-character Hermes-writer article but blocked before media. Missing brief-level `research_attempts` caused same-lane/trend and batch gates to miss editorial mode; the external slop checker found one exact binary contrast.
- `ff66fa3` fixed both. WeChat v4 then recorded WeWrite HTTP 400 and Hermes writer direct plus US-proxy attempts, but the provider returned HTTP 429 after its internal retries. No media or publisher ran.
- `6b64239` adds one same-route transient retry with bounded delay. Related suite returned 191 passed. Full `artifacts/test-reports/p10-wechat-writer-rate-limit.xml` returned 1752 passed plus 37 subtests in 374.31 seconds. Privacy 586/0; license 65/0.
- WeChat v5 remains pending. Production stays signed `2f4f612`; timers remain disabled.

## 2026-09-08 WeChat v5 Slop-Gate Evidence

- v5 used the same safe publisher boundary and reached the mode-aware WeChat gate with a 1,861-character Hermes-writer article. Every failed v3 operational dimension was resolved.
- Only `no_ai_slop_check` failed. Running the server checker against the persisted body found one `假深刻收尾` on line 69: `这就是真正的改进清单`.
- `f76a3c2` adds an exact post-writer rewrite and test. Related suite returned 175 passed. Full `artifacts/test-reports/p10-wechat-v5-slop-repair.xml` returned 1753 passed plus 37 subtests in 357.19 seconds. Privacy 586/0; license 65/0.
- v5 was not delivered and generated no media. Production and timers remain unchanged; v6 is required.

## 2026-09-08 WeChat v6 Short-Contrast Evidence

- v6 used the safe boundary and produced a 2,270-character Hermes-writer article. Writer and every operational/content-mode gate passed.
- External no-AI-slop found one binary contrast on line 71: `卡住的根本不是写，而是等确认、缺口径`. No media or publisher ran.
- `15e3a3c` adds the exact red/green case and generalizes the existing binary pattern from two characters to one while absorbing optional `根本`.
- Full `artifacts/test-reports/p10-wechat-single-char-contrast.xml` returned 1754 passed plus 37 subtests in 357.35 seconds. Privacy 586/0; license 65/0. v7 remains required.

## 2026-09-08 WeChat v7 Image-Intent Evidence

- Isolated v7 job `4ca34f998dda4d48` reached image generation after all copy and platform gates passed. The cover semantic score was 0.8. Section 01 then failed three providers with generic desk/library/office captions and no matching concrete section concept.
- `image_quality_recovery.json` showed the expected concepts were the full article title, abstract H2 and shortened title. The persisted article contained explicit visual plans for a multi-tool desk, a goal/input/output card and a four-panel boundary checklist, proving the loss occurred in media-plan compilation rather than content generation.
- Local red/green tests reproduce that loss and verify plan-to-H2 binding plus three distinct observable concepts. Related image/media/WeChat regression returned 154 passed.
- Full `artifacts/test-reports/p10-wechat-explicit-visual-plans.xml` returned 1755 passed plus 37 subtests in 347.35 seconds. Project/privacy audit scanned 586 files with zero issues; license audit checked 65 capabilities with zero issues; `git diff --check` passed.
- Production remains signed `2f4f612`; timers and real publishers remain disabled. Linux staging and a fresh v8 run are pending.
