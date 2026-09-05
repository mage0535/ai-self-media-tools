# Production Runtime V8 Status

Last updated: 2026-09-04 Asia/Shanghai (P10 bootstrap hardening verified locally)

## Current state

- Phase: P10 real Canaries, deployment, rollback, and controlled activation
- Production timers observed on 2026-09-02: all related timers disabled; overnight/supervisor inactive.
- Production release observed on 2026-09-02: `unified-capability-v7-149362f`.
- GitHub feature branch: `codex/unified-capability-closure@149362f`
- Development branch: `codex/production-runtime-v8`
- Latest complete regression on this branch: 1636 passed + 37 subtests.

## Active work

| Work item | Owner | Files reserved | State | Next verification |
|---|---|---|---|---|
| Runtime code/config/data convergence | Codex primary | `content_platform/runtime_paths.py`, `content_platform/mcp_server.py`, systemd/deploy/runtime tests | committed `c9babbd` | verify gateway drop-in and shared DB during deployment |
| Automated admission contract | Codex primary | `content_platform/task_admission.py`, `content_platform/pipeline.py`, `content_platform/mcp_server.py`, admission tests | committed `4d9c567` | server verification during deployment |
| Platform artifact completion contract | Codex primary | `content_platform/artifact_contract.py`, pipeline/store recovery, P3 tests | committed `277f1e3` | server fault injection during deployment |
| Pre-generation operations/source gates | Codex primary | `content_platform/pre_generation_gate.py`, pipeline and P4 tests | committed `6b9052b` | production fault injection during deployment |
| Unified capability execution evidence | Codex primary | capability registry/router/DAG and P5 tests | committed `c629116`, `1f7e93e` | server capability smoke during deployment |
| Bounded Hermes worker sessions | Codex primary | generator/run contract/pipeline and P6 tests | committed `6e6abf5` | server generation fault test during deployment |
| Image checkpoint/provider fallback | Codex primary | MediaBridge/checkpoint/provider evidence and P7 tests | committed `652f5fb` | production image Canary during deployment |
| Renderer retry/checkpoint | Codex primary | `scripts/film_renderer.py`, runtime adapter, P8 tests | committed `a371b69` | production FFmpeg/Playwright Canary |
| Delivery postcheck and ledger | Codex primary | trace/DAG/Pipeline/ledger/runtime adapter and P9 tests | local_complete | commit P9; verify real platform postchecks in P10 |
| 12-platform Canary and deployment | Codex primary | `scripts/deploy_release.py`, `tests/test_release_systemd.py`, four coordination documents | in_progress | finish rollback-order full regression and Linux fault tests; reconcile forward/rollback unit inventories before activation |

## Server Blockers From The 2026-08-31 Audit

These describe the audited production release, not the current development code. Local fixes below require Linux and live workflow verification before these server blockers can be closed.

1. MCP searches only `$CONTENT_PLATFORM_HOME/config.json`; immutable releases contain no private config.
2. MCP can create a release-local `data/state.db`, while operators monitor the shared production database.
3. Hermes can execute the dirty server checkout and mix it with renderer scripts from the current release.
4. Jobs without a run contract can skip content-depth and mandatory-media gates.
5. `review_required` and `approved` can currently exist with zero media artifacts.
6. Stale RUNNING jobs are not recovered automatically; Hermes created a direct SQL lock-clearing helper.
7. Film renderer continues after a failed shot and discards the remaining successful work.
8. The current 12-platform Canary and publication metrics feedback are not complete.

## Latest verification

- Focused runtime/MCP/systemd/deploy regression: `85 passed`.
- Full regression: `1532 passed, 37 subtests passed`.
- License audit: `65` capabilities, zero issues.
- Project/privacy audit initially detected private absolute paths in coordination docs; logical aliases replaced them and subsequent phase audits passed.
- A full-suite failure exposed a video checkpoint collision: repeated fallback section labels reused one image. The checkpoint identity now includes the scene index, and the focused video test passes.
- Automated admission focused regression: `102 passed`.
- P2 full regression: `1537 passed, 37 subtests passed`.
- Production automated create/run requires one platform and a current validated run contract; MCP compiles the contract deterministically.
- P3 completion/recovery focused regression: `89 passed`.
- P3 full regression: `1543 passed, 37 subtests passed`.
- Production review/approval cannot pass required zero/missing artifacts; expired generation leases recover by job ID and resume through Pipeline.
- P4 pre-generation focused regression: `100 passed`.
- P4 full regression: `1546 passed, 37 subtests passed`.
- Missing/mismatched native evidence, generation context, media capability, or publisher route blocks before the model call.
- P5 inventory scan: 65 capabilities = 26 executable, 20 parent-executed with telemetry, 19 inventory-only.
- P5 evidence test completed: an assets/render adapter without file/hash evidence remains `output_verified` and fails any required artifact contract.
- P5 evidence-level focused regression: `150 passed`; full regression: `1550 passed, 37 subtests passed`.
- Registry now declares an explicit verification level for all 26 executable capabilities.
- Artifact verification requires readable non-empty files and matching SHA-256; effect verification additionally requires a passing named probe bound to a verified artifact hash.
- P5 inventory classification completed for all 19 inventory-only capabilities.
- P5 inventory governance focused regression: `60 passed`; full regression: `1551 passed, 37 subtests passed`.
- All 19 inventory-only capabilities now have a machine-readable disposition: compiled reference, license exclusion, or planned P9 adapter.
- P5 local scope is complete; real server execution remains a deployment/Canary gate.
- P6 focused generator/pipeline regression: `89 passed`; full regression: `1555 passed, 37 subtests passed`.
- Production generation SLO: 90s soft, 180s hard, 15s heartbeat, maximum two attempts; run contract remains the source of truth.
- Heartbeats begin before the soft deadline, and each job has a private checkpoint/attempt directory plus pipeline execution correlation ID.
- P7 focused image/provider/video-asset regression: `69 passed`; full regression: `1559 passed, 37 subtests passed`.
- Mid-batch timeout recovery reuses the verified cover and regenerates only the missing section image.
- Provider timeout records the attempted provider, rotates to the next provider, and preserves verified fallback evidence.
- Image checkpoint signatures include provider/model/quality/method; resumed perceptual hashes remain part of duplicate detection.
- P8 focused renderer/effect/runner/Pipeline/Canary regression: `222 passed`; full regression: `1567 passed, 37 subtests passed`.
- Each shot retries locally up to two times; exhaustion stops before later shots and writes an atomic checkpoint.
- Scene execution evidence v2 binds final.mp4 SHA to all scene plans, real assets, renderer modes, transitions, and measured motion probes.
- `video_toolchain_runner` now requires effect verification; final file existence alone is rejected.
- P9 identity/metric focused regression: `111 passed`; full regression: `1569 passed, 37 subtests passed`.
- Bare manual confirmation cannot create a publication identity or metric windows; management/API/browser/URL-probe verification levels are explicit.
- Unavailable metric collection remains pending with delayed retry; only the third failed attempt becomes `insufficient`.
- P9 remains in progress until publisher-specific postchecks enter the unified delivery capability evidence.
- P9 postcheck capability focused regression: `71 passed`; full regression: `1572 passed, 37 subtests passed`.
- Registry now contains 27 executable and 18 inventory-only capabilities; postcheck is an allowlisted runtime adapter.
- Verified publication executes postcheck; drafted/scheduled/handoff results skip with explicit non-publication reason; published without identity fails.

## Current P9 Handoff

- Adapter output is now persisted in delivery-attempt metadata before updating the job's draft metadata; the canonical trace reads the latest stored job.
- Published results always require postcheck, including when evidence is absent. Invalid contract/output hash and different content identity fail.
- Required trace evidence is platform-scoped. A previous successful delivery cannot satisfy a later failed check on this or another platform.
- Publication account/content/platform bindings are checked against the immutable intent before registering identity/windows.
- Failure evidence participates in the delivery manifest hash. Missing pre-delivery trace on an automated job persists a failed trace and raises.
- Focused verification: `146 passed` before the final identity/hash tests; final full regression: `1593 passed + 37 subtests`.
- Remaining live gap: source names such as `management_page` are labels, not independent browser/API proof. All publication identity adapters, draft readback, scheduled-time postcheck, and manual-handoff boundaries still need real-platform verification.
- Final negative-path coverage includes absent/invalid/tampered postcheck, account/content/platform mismatch, cross-platform and same-platform stale-success masking, draft metadata write failure, and missing automated pre-delivery trace.
- JUnit: `artifacts/test-reports/p9-trace-closure.xml` => 1630 tests, 0 failures, 0 errors, 290.565 seconds.
- Final audits: project/privacy 574 files with zero issues; license 65 capabilities with zero issues; `git diff --check` clean.

## Production release gate

- [ ] One code root, private config path, shared data root, and shared database proven for CLI/MCP/systemd.
- [ ] Automated jobs without validated run contracts rejected.
- [ ] Mandatory platform artifacts enforced before review/approval.
- [ ] Stale lease recovery passes fault-injection tests.
- [ ] Renderer per-shot retry/checkpoint passes fault-injection tests.
- [ ] Full local and Linux suites report zero failures.
- [ ] Privacy and license audits pass.
- [ ] 12 serial platform Canaries pass.
- [ ] Rollback rehearsal passes.
- [ ] Timers explicitly approved and restored.

## 2026-09-02 Server Refresh

- System `hermes-gateway.service` is enabled and active; ai-self-media timers are disabled.
- Gateway-launched MCP has only `CONTENT_PLATFORM_HOME` and `PYTHONPATH`; it still lacks explicit config/data/secrets/runtime-mode roots.
- Shared database contains 433 jobs; release-local database contains 0 jobs and remains a separate inode.
- Private config still points `data_dir` at an obsolete release directory. Current release has no `release-metadata.json`.
- Current production is therefore still the old split runtime. Do not run production jobs until P10 activation fixes gateway environment and private config.
- Linux staging at `e1d6068` passed 70 focused tests and JUnit 1630 tests with zero failures/errors; project audit 573 files clean and license audit 65 capabilities clean.
- Legacy release comparison against Git `149362f`: 10 tracked files differ and 130 extra runtime files exist, including release-local DB/cache/pyc. It must not be adopted as a signed rollback.
- New local `prepare_bootstrap_release` builds a tracked-only signed rollback from clean Git without changing current/systemd. Deployment-focused regression: 116 passed; full local: 1594 passed plus 37 subtests.
- P10 bootstrap hardening added pre-side-effect validation for release names and raw path boundaries, explicit-key fail-closed behavior, exclusive target reservation, and transaction-owned cleanup. Bootstrap subset: 16 passed; deployment/release focused suite: 129 passed.
- P10 full regression: 1607 passed plus 37 subtests; JUnit 1644 tests, zero failures/errors/skips. Project/privacy audit: 574 files, zero issues. License audit: 65 capabilities, zero issues.
- Newly confirmed activation blocker: deploy helpers invoke `systemctl --user`, while the observed production gateway and content units are system-scoped. Explicit scope support and Linux fault tests are required before activation.

## 2026-09-04 Resume And Server Drift Review

- Bootstrap hardening is committed/pushed as `d4db062`. Explicit scope propagation is the current local work; production has not been activated.
- Fresh read-only SSH observation: current release remains `unified-capability-v7-149362f`, mutable checkout remains `6f4c88a`, gateway active, all 11 listed project timers disabled.
- Mutable checkout has 17 modified tracked files (459 insertions, 36 deletions) plus untracked assets/config/backups. None were overwritten or attributed to a particular author.
- Image provider, film renderer, and private config timestamps precede September 2; no top-level source/script files newer than that cutoff were found. This limited check is not an exhaustive proof that all private/nested assets are unchanged.
- Available disk is about 23 GB (74% used). Server staging is still `e1d6068`.
- Effective systemd WorkingDirectory is expanded, not literal `%h`; current effective-unit verifier still compares literal templates. This remains a separate activation blocker after scope command routing.
- Scope propagation full regression: 1612 passed plus 37 subtests (285.26s); project/privacy 574 files clean, license 65 capabilities clean. No production activation performed.

## Effective-Path Follow-Up

- Scope propagation committed as `9748bff`. Local effective-path fix now expands the deployment user's home and checks exact environment assignments; module-based ExecStart is no longer confused with scraper environment paths.
- Five new tests first failed against the old implementation. Focused deploy/systemd/release/Canary regression: 133 passed.
- Fresh 12:40 BJT SSH check: same current release, mutable HEAD, 17-file diff summary and two recorded image/renderer hashes. No claim is made that all private assets are byte-identical.
- Current content service environment lacks explicit CODE_ROOT and production mode. Gateway/root convergence and actual Linux activation remain required; no services or timers changed.
- Effective-path full regression: 1617 passed plus 37 subtests, 283.41 seconds. Linux staging verification is next; this is not production activation evidence.
- Linux staging advanced cleanly to `de506e2`: 97 deploy/systemd/release tests passed in 5.55 seconds; project/privacy 574 files clean, license 65 capabilities clean. Current production remains old release and gateway active.
- No full Linux suite on `de506e2` yet; previous full Linux evidence at `e1d6068` is historical, not interchangeable. Candidate signing, gateway/config convergence, rollback rehearsal and live Canaries remain pending.

## Real Configuration Preflight

- Read-only 12:52 BJT refresh: same release/HEAD/status-list hash and provider/renderer hashes as previous refresh; gateway active. No claim of an exhaustive private-asset comparison.
- Real config validation fails on external Agent-Reach bridge; Lux and knowledge-card bridges are also configured outside the release. All three exist on server; tool presence is not a governed runtime dependency contract.
- No candidate was signed or activated. Existing release-only script gate remains enforced.
- Bootstrap/deploy now preflight config before evidence generation and candidate creation; retain final post-build check and restore caller environment. Focused regression: 99 passed.
- Next implementation must govern the three external dependencies without bypassing security/quality gates, then resume signed candidate preparation.
- Config-preflight full regression: 1619 passed plus 37 subtests, 273.90 seconds, exit 0; project/privacy and license audits remain clean.

## External Hermes Bridge Governance

- Private config may attest a `hermes_bridge` only with exact config key, exact path under Hermes home, regular non-symlink file, and SHA-256. Duplicate, malformed, unused, missing, symlinked, wrong-key or drifted records fail closed.
- This is deployment dependency trust only. Agent-Reach, Lux and knowledge-card bridge runtime probes/adapters/effect evidence remain separate P10 work.
- Focused deployment suite: 145 passed. Full regression: 1623 passed plus 37 subtests, 284.78 seconds.
- Next: commit/push, Linux test, create a permission-restricted candidate config copy with current hashes, and preflight it without changing production config.
- Linux bridge tests at `ef39e15`: 6 passed. A mode-600 candidate config copy was created in isolated staging with three current bridge hashes; production config was not changed.
- First candidate preflight then failed on an internal `$CURRENT_RELEASE` image script resolving into old production. One red test reproduced it; loader now supports explicit code root and Canary supplies its candidate root.
- First full regression exposed one Canary path regression (1 failed, 1623 passed); targeted repair passed 103 tests. Final full regression: 1624 passed plus 37 subtests, 286.97 seconds.
- Linux alias/bridge subset: 7 passed; private candidate config preflight passed in 10ms.
- Historical `149362f` bootstrap attempt failed correctly: JUnit 1565 tests, 1 failure because required four video visual assets produced two. It was not signed; no candidate directory remains.
- Clean runtime bootstrap `7bfa13c` succeeded with JUnit 1661, zero failures/errors/skips. Signed/frozen release is prepared but inactive; current remains v7, timers remain disabled, gateway active, shared DB unchanged.
- Gateway drop-in transaction is implemented locally: install the one project-owned file, restart active gateway, verify seven exact roots/mode, and restore prior drop-in/current/gateway state on failure. Unrelated gateway drop-ins remain untouched.
- Gateway focused deployment suite: 148 passed. Full JUnit: 1663 tests, zero failures/errors/skips, 286.505 seconds; equivalent pytest scale 1626 plus 37 subtests.
- Privacy audit initially rejected a test-only literal private path; it was replaced with `Path.home()`. Systemd subset 17 passed and privacy scan 575 files clean afterward.
- Next: commit/push, Linux gateway fault tests, prepare a signed forward candidate from the new commit, then perform controlled system-scope activation and rollback rehearsal with timers disabled.
- Candidate private-config promotion is now part of local deploy transaction. It occurs after release signing/freeze and before gateway restart; activation failure restores prior config bytes/mode.
- Private-config focused suite: 108 passed. Full regression: 1628 passed plus 37 subtests; JUnit 1665 zero failures/errors/skips, 287.140 seconds. Privacy 575 files and license 65 capabilities clean.
- Next: commit/push and run Linux POSIX mode/failure tests before any system-scope activation.
- Linux at `03b4b66`: 65 gateway/deploy tests passed. A newer inactive signed bootstrap from `cad932c` was prepared because the earlier `7bfa13c` lacks the gateway drop-in.
- Pre-activation unit inventory found a missing dedicated WeChat metrics timer. Added its existing 07:20 Asia/Shanghai definition without enabling it; focused 62 passed, full 1629 plus 37 subtests (293.31s).
- New activation blocker: outer config rollback currently runs after inner systemd recovery starts old services. Must restore old config before any old-service restart; final file-state tests alone are insufficient.
- Startup-time assertion reproduced old gateway reading candidate config during rollback. Local correction invokes config restoration before restoring service states; restoration failure prevents starts/enables. Systemd subset: 20 passed. Production not activated.
- Current signed `cad932c` bootstrap predates the restored WeChat timer and rollback-order fix; do not describe it as a fully compatible rehearsed rollback for newer code without explicit compatibility verification.
- Rollback-order full regression: 1630 passed plus 37 subtests in 288.58s, zero failures. Linux verification next; no production activation.
- Linux staging `ec08d1c`: 109 operational/deployment/systemd tests passed in 5.92s, including POSIX config mode checks. Current remains v7 and gateway active; next is forward/rollback compatibility review, not automatic timer restoration.

## Durable Release Config Snapshots

- Post-signing review found all prepared bootstrap metadata pointed to the staging candidate config. These releases remain evidence artifacts but are not final durable rollback targets.
- New release config snapshots live under shared `release-configs`, are created exclusively with mode 0600, handle partial writes, and are removed only when owned by a failed transaction.
- Bootstrap/deploy metadata binds the durable snapshot and hash. Rollback with an active config path promotes the verified snapshot before gateway start and restores the previous config on failure.
- Focused deploy/systemd suite: 70 passed. Full regression: 1634 passed plus 37 subtests, 299.30 seconds. Privacy 576 files and license 65 capabilities clean.
- Next: commit/push, Linux verify, rebuild final compatible bootstrap, then prepare forward release/controlled activation with timers disabled.
- Linux durable-snapshot suite at `9734dd4`: 70 passed. Final durable rollback `ec08d1c` prepared with JUnit 1667, zero failures, mode-600 shared config snapshot and successful metadata verification.
- First forward activation attempt rolled back automatically: old config hash/mode, current, gateway, disabled timers and shared DB inode/size/433 jobs were restored. The failed release/config were removed, but an orphan attestation and no durable error report exposed two cleanup defects.
- Failure cleanup now removes only an unchanged transaction-owned attestation and writes mode-600 `release_failure_v1` evidence. Focused 156 passed; full 1634 plus 37 subtests in 282.71s. Privacy 576 files/license 65 capabilities clean.
- Next: commit/push, Linux failure-path verification, archive the orphan attestation as failure evidence, then retry with a new release name to capture the actual systemd failure reason.
- Linux failure cleanup passed; the first orphan attestation was checksum-verified and archived privately before removal.
- Second activation persisted its failure: stale supervisor drop-ins overrode CONTENT_PLATFORM_CONFIG. Automatic rollback restored old current/config/gateway/timers and removed owned release artifacts.
- Selective conflict removal now governs only runtime env, WorkingDirectory and ExecStart; resource/Qwen/recovery/writer drop-ins are preserved. Focused 158 passed; full 1636 plus 37 subtests in 279.00s.
- Next: Linux selective-dropin tests, third named activation attempt, post-activation MCP/shared-DB checks and rollback rehearsal before Canaries.
- Third activation at `4643ed0` succeeded after removing only stale runtime drop-ins. Postchecks: signed config/current/gateway roots/shared DB all matched, valid functional drop-ins preserved, zero failed units/timers enabled.
- CLI and Hermes venv both resolved current/private-config/shared-data/shared-DB in production mode. Real rollback to durable `ec08d1c` succeeded with systemd verified and zero timers.
- Forward rollback was correctly rejected because root-run Python had added three `__pycache__` directories to signed release. Current remains durable rollback.
- Added `PYTHONDONTWRITEBYTECODE=1` to all project services and gateway, included in exact environment validation and conflict detection. Targeted 115 passed; full JUnit 1673 zero failures/errors/skips, 275.052s.
- Next: commit/push, Linux no-bytecode tests, build a new clean forward release, verify no post-start cache, then repeat rollback/forward rehearsal before Canaries.
