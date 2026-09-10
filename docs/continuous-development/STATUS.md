# Production Runtime V8 Status

Last updated: 2026-09-10 Asia/Shanghai (Sol plan execution resumed; B0 baseline and B1 unified topic decision in progress)

## Current state

- Phase: P10 real Canaries, deployment, rollback, and controlled activation
- Production timers observed on 2026-09-06: all 11 related timers disabled/inactive.
- Production release observed on 2026-09-06: `production-runtime-v8-2f4f612-20260906`.
- Production/GitHub commit: `2f4f6125ff9c0d5dff1ffaa1e4e7defe51b3c15f`.
- Development branch: `codex/production-runtime-v8`
- Latest complete regression on this branch: 1831 passed + 37 subtests; zero failures; JUnit saved at `artifacts/test-reports/sol-b2-juejin-visible-card-20260910.xml`.

## Active work

| Work item | Owner | Files reserved | State | Next verification |
|---|---|---|---|---|
| Sol B2 Juejin visible-card contract | Codex primary | Juejin card parser, 30-day gate, tests and four coordination documents | local_complete | commit, staging sync and real Juejin strict-contract smoke |
| Sol B2 Juejin detail evidence | Codex primary | Juejin saved DOM/API evidence and four coordination documents | recovered_with_visible_card | strict card adapter implemented; real staging acceptance pending |
| Sol B2 Bilibili Linux collector acceptance | Codex primary | server staging evidence and four coordination documents | verified | preserve isolated evidence; Bilibili collector can proceed to later content Canary |
| Sol B2 Bilibili real-DOM card ordering | Codex primary | Bilibili card parser and four coordination documents | committed `3e0eed1` | Linux live acceptance passed 24 rows and 10/10 strict pack samples |
| Sol B2 Bilibili visible-card fallback | Codex primary | Bilibili card parser, detail fallback, login classification, tests and four coordination documents | committed `4c98dc1` | real-DOM follow-up required after first live retry returned zero rows |
| Sol B2 Bilibili strict detail enrichment | Codex primary | `content_platform/hot_work_intelligence.py`, Bilibili detail tests and four coordination documents | local_complete | commit and sync staging; run fresh Bilibili live collector and strict contract report |
| Sol B2 all-target collection scope | Codex primary | CLI hot-work scope, parser help, scope tests and four coordination documents | local_complete | commit milestone; then run isolated server collector smokes for every no-sample target |
| Sol B2 live contract-gap audit | Codex primary | contract report helper, generated private-safe report and four coordination documents | local_complete | commit milestone; then repair omitted target aliases followed by incomplete/empty collectors |
| Sol B2 platform intelligence evidence contract | Codex primary | `content_platform/topic_selection_engine.py`, hot-work normalization, B2 tests and four coordination documents | local_complete | commit milestone; next generate live per-platform contract-gap report and repair collectors without fabricating missing identity |
| Sol B0/B1 runtime convergence and unified three-layer topic decision | Codex primary | topic decision, Pipeline/CLI/MCP/overnight integration, run contract, tests and four coordination documents | local_complete | commit milestone; then enforce B2 evidence contracts and produce shadow difference reports before authoritative cutover |
| Runtime code/config/data convergence | Codex primary | `content_platform/runtime_paths.py`, `content_platform/mcp_server.py`, systemd/deploy/runtime tests | committed `c9babbd` | verify gateway drop-in and shared DB during deployment |
| Automated admission contract | Codex primary | `content_platform/task_admission.py`, `content_platform/pipeline.py`, `content_platform/mcp_server.py`, admission tests | committed `4d9c567` | server verification during deployment |
| Platform artifact completion contract | Codex primary | `content_platform/artifact_contract.py`, pipeline/store recovery, P3 tests | committed `277f1e3` | server fault injection during deployment |
| Pre-generation operations/source gates | Codex primary | `content_platform/pre_generation_gate.py`, pipeline and P4 tests | committed `6b9052b` | production fault injection during deployment |
| Unified capability execution evidence | Codex primary | capability registry/router/DAG and P5 tests | committed `c629116`, `1f7e93e` | server capability smoke during deployment |
| Bounded Hermes worker sessions | Codex primary | generator/run contract/pipeline and P6 tests | committed `6e6abf5` | server generation fault test during deployment |
| Image checkpoint/provider fallback | Codex primary | MediaBridge/checkpoint/provider evidence and P7 tests | committed `652f5fb` | production image Canary during deployment |
| Renderer retry/checkpoint | Codex primary | `scripts/film_renderer.py`, runtime adapter, P8 tests | committed `a371b69` | production FFmpeg/Playwright Canary |
| Delivery postcheck and ledger | Codex primary | trace/DAG/Pipeline/ledger/runtime adapter and P9 tests | local_complete | commit P9; verify real platform postchecks in P10 |
| 12-platform Canary and deployment | Codex primary | P10 Canary/evidence files and four coordination documents | in_progress | run serial real platform Canaries; verify live publisher/draft/handoff boundaries before timer decision |
| Hermes MCP child runtime convergence | Codex primary | `scripts/deploy_release.py`, `tests/test_release_systemd.py`, `tests/test_deploy_release.py`, four coordination documents | deployed `d79128c` | complete: live MCP env, tool discovery, byte stability and rollback/forward verified |
| Hot-work collector automatic auth/query routing | Codex primary | platform collectors, parsers, cache, focused tests, four coordination documents | deployed `2f4f612` | 6/12 Canary inputs ready; resolve remaining platform evidence without fabrication |
| Deterministic abstract-media fallback | Codex primary | `content_platform/deterministic_visual.py`, `content_platform/media.py`, `tests/test_deterministic_visual.py`, media-focused tests | committed through `7d6f3e6` | rerun real Juejin Canary after staging sync |
| Article recovery and final-copy truth gate | Codex primary | claim/content policy/Pipeline/Task9 Canary and focused tests | committed `4b141c4` | Linux regression, v18 probe refresh, then clean Juejin Canary |
| Final generated-copy artifact gate | Codex primary | content hygiene/claim ledger/Pipeline and regression tests | committed `3c5de37`, `fd1e9c0` | Linux regression, v19 offline re-evaluation, then clean Juejin v20 |
| Minimal final Hermes retry | Codex primary | generator retry prompt and recovery tests | committed `b63547e` | Linux recovery regression and clean Juejin v21 |
| Technical source fact pack and article structure | Codex primary | pre-generation gate/Task9 source claims/generator/Pipeline | committed `4ce550d` | Linux regression, build official v22 input, run v22 |
| Canary production admission | Codex primary | Task9 runtime environment and tests | committed `6bcdcaa` | Linux regression, prove old input blocks and official fact-pack input proceeds |
| Blocked-copy observability and quote repair | Codex primary | content hygiene/Pipeline and tests | committed `a162adb` | Linux regression and clean Juejin v23 |
| Final article heading to image binding | Codex primary | article media adapter and tests | committed `6516e55` | Linux media regression and clean Juejin v24 |
| Verified article source appendix | Codex primary | claim ledger/Pipeline/GEO tests | committed `13c4634` | Linux source/GEO regression and clean Juejin v25 |
| Chinese fragment precision | Codex primary | content hygiene and tests | committed `600a011` | Linux hygiene regression and clean Juejin v26 |
| Deterministic visual diversity and per-asset dedupe | Codex primary | deterministic visual/article media/content normalization | committed `91adeec` | Linux media regression and clean Juejin v27 |
| Article heading preservation | Codex primary | article media section normalization and tests | committed `adca5ef` | Linux regression and clean Juejin v28 |
| Final copy and section-media polish | Codex primary | content hygiene/claim ledger/article media and tests | committed `7eac44d` | Linux regression and clean Juejin v29 |
| Reader-facing article formatting | Codex primary | content normalization/source labels and tests | committed `72f76e5` | Linux regression and offline v29 rebuild; decide final v30 vs draft proof |
| Technical claim variant coverage | Codex primary | claim ledger and tests | committed `c16d943` | Linux regression and final fresh Juejin validation |
| Technical anchor coverage | Codex primary | claim ledger and tests | committed `9b0a75c` | Linux regression and v31 offline re-evaluation; do not accept v31 |
| Grounded technical rebuild | Codex primary | claim ledger/Pipeline and tests | committed `6e6bb36` | Linux regression and deterministic v31 recovery package |
| Grounded rebuild prose hygiene | Codex primary | grounded builder and tests | committed `1b3d6a9` | Linux regression and deterministic recovery validation |
| Hermes active-model availability | Codex primary | server-only runtime evidence | v33 blocked | keep production unchanged; validate recovery without model, retry live model only after provider health returns |

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
- [x] Rollback rehearsal passes.
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

## 2026-09-05 Hermes MCP Runtime Convergence

- Root cause: the gateway environment was correct, but `mcp_servers.content-platform.env` in Hermes private config explicitly replaced the child environment with only two runtime fields. MCP startup could therefore resolve wrong roots and write bytecode into a signed release.
- Commit `d79128c` atomically updates only that MCP env block with all eight production assignments. It preserves every other MCP entry/server field, uses no new YAML dependency, and restores exact prior bytes/mode before old gateway startup on failure.
- Local focused regression: 160 passed; final deploy/systemd subset: 75 passed. Full: 1639 passed plus 37 subtests; JUnit 1676 tests, zero failures/errors/skips. Privacy scan: 576 files, zero issues. License audit: 65 capabilities, zero issues.
- Linux staging at `d79128c`: 161 deployment/systemd/operational tests passed. A read-only transformation of the real Hermes config accepted its structure, produced all eight expected fields, and left source SHA unchanged.
- Signed production release `production-runtime-v8-d79128c-20260905` activated successfully. A real rollback to `bootstrap-runtime-v8-b16d796-20260905` and forward activation back to `d79128c` both passed systemd and MCP config verification.
- Final postcheck: gateway active since 17:40:14 CST, MainPID 2074498, zero failed units, zero enabled project timers, NO_PROXY loopback drop-in preserved, journal retained. MCP watchdog/server inherited all eight fields; `hermes mcp test content-platform` connected in 1709ms and discovered 22 tools.
- Signed release remained at zero `.pyc` files and zero `__pycache__` directories after MCP startup. Shared DB remained inode 1642977, 63,143,936 bytes and 433 jobs.
- Remaining gate: 12 serial real platform Canaries and live delivery/postcheck evidence are not complete. Do not enable timers or describe unit/MCP verification as completed content production.

## 2026-09-07 Juejin Recovery Checkpoint

- Real Juejin v18 reached `review_required`; cover plus three section images passed semantic gates and the formal article media contract passed.
- It was not published or uploaded as a real draft because final copy contained a split identifier plus unsupported product recommendations and an unsupported install command.
- `4b141c4` adds post-humanizer claim/hygiene validation, rejects unsupported tool recommendations and install commands, limits independent audio generation to actual audio content forms, and treats optional artifact providers as non-blocking in the Canary probe.
- Fresh local focused regression: 310 passed. Fresh full regression: 1699 passed plus 37 subtests in 297.08 seconds. Project/privacy audit scanned 581 files with zero issues; license audit checked 65 capabilities with zero issues.
- Remaining immediate gates: Linux staging verification, recompute v18 artifact evidence, run a clean Juejin Canary, inspect final copy, then use the real Juejin draft publisher only if platform upload/readback evidence can be produced.

## 2026-09-07 Juejin v19 Finding

- Hermes active model `opencode-go/mimo-v2.5` completed generation on its first attempt in about 258 seconds. Pipeline and artifact probes returned passed; cover and article images were generated, and no narration artifact was created.
- Manual final-copy review still rejected the result: code fences were attached to prose, YAML contained comma-only corruption, `.agent` and `package.json` were split/corrupted, and unverified repository endorsements plus Agent Skills loading mechanisms remained.
- The existing generated-text and claim gates both incorrectly returned passed. `3c5de37` adds deterministic repairs for those known formatting corruptions, claim patterns for repository endorsements/loading mechanisms, and a final automated prose-hygiene gate after factual repair but before media.
- Fresh focused regression: 154 passed. Fresh full regression: 1702 passed plus 37 subtests in 299.65 seconds. Privacy audit: 581 files and zero issues. License audit: 65 capabilities and zero issues.
- v19 is evidence of a caught gate defect, not an accepted publication. Linux verification and a new v20 real generation remain required.
- Offline v19 re-evaluation after `3c5de37` repaired all four observed formatting corruptions and rejected the repository endorsement. Follow-up `fd1e9c0` is required because a dotted `SKILL.md` token initially evaded the loading-mechanism pattern; full regression remained 1702 passed plus 37 subtests.

## 2026-09-07 Juejin v20 Timeout Finding

- v20 used the current Hermes `opencode-go/mimo-v2.5`. Attempt one reached its 420-second hard limit with regular 15-second heartbeats; attempt two started automatically but its 5,603-character prompt also reached the 180-second hard limit.
- The task failed explicitly with `GenerationTimeoutError`; it created no media and made no delivery attempt. This proves bounded termination, but not successful recovery.
- `b63547e` gives only the retry a minimal prompt: output contract, language, factual boundary, article length, 500-byte platform rules, one 240-byte hook reference and at most 3,072 bytes of compiled verified context. The normal first attempt remains unchanged.
- Red test observed a 6,638-character retry prompt; green test requires under 4,000 characters and retained topic, claim ledger and length contract. Focused generation/Pipeline tests: 139 passed. Full: 1703 passed plus 37 subtests in 298.66 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v21 Fact-Evidence Finding

- v21 completed the full first Hermes request in about 236 seconds; retry compression was not exercised. It then failed before image generation because the article had fewer than three mapped sections.
- The more important defect was factual: the only evidence was a 600-byte search-card snapshot containing title, URL and engagement. The generated tutorial invented or copied unverified Claude Code paths, precedence, commands, dynamic injection and loading behavior while the claim gate passed.
- A logged Playwright probe successfully extracted the 8,657-character Juejin source article. It is useful for trend, style and structure analysis, but it is not automatically authoritative technical evidence.
- `4ce550d` requires at least three verified, URL-backed, evidence-path and provenance-hash claims before a production automated Juejin technical article can call the model. Task9 source claims additionally bind a source excerpt to an input-local file and SHA-256.
- Article generation now requests at least three substantive H2 sections; the Pipeline blocks automated article copy below that threshold before media. Focused related suite: 184 passed. Full: 1707 passed plus 37 subtests in 297.13 seconds; privacy 581/0 and license 65/0.

## 2026-09-07 Task9 Admission Correction

- Direct preflight inspection showed `_run_pipeline_case` did not set `CONTENT_PLATFORM_RUNTIME_MODE=production`; therefore earlier Task9 Pipeline runs skipped `validate_pre_generation` even when using production configuration.
- `6bcdcaa` sets production mode for the full case execution and restores the prior environment in `finally`, including failures. A red environment-probe test observed `None`; green observes `production` and confirms cleanup.
- Related Task9/Pipeline suite: 139 passed. Full: 1708 passed plus 37 subtests in 303.40 seconds. Project/privacy audit 581/0; license audit 65/0.
- Prior real media artifacts remain useful provider/render evidence, but they cannot count as production-admission Canary passes. v22 is the first Juejin rerun intended to exercise both production admission and real generation.

## 2026-09-07 Juejin v22 Result

- v22 was the first Juejin case to pass Task9 production admission with five SHA-bound claims from the official Agent Skills specification. Hermes `mimo-v2.5` completed the first 8,035-character request in about 188 seconds.
- Final text hygiene correctly blocked the draft for an unmatched straight quote before any image or delivery operation. The failure showed a separate observability defect: blocked candidate copy was not persisted, leaving only a compact workflow excerpt.
- `a162adb` removes only an unmatched final straight quote from non-code Markdown segments while preserving quoted code. Before final hygiene or article-structure blocking, Pipeline now persists the full candidate copy, metadata and gate evidence for checkpoint repair.
- Focused related regression: 166 passed. Full: 1709 passed plus 37 subtests in 300.50 seconds. Privacy audit 581/0; license audit 65/0.

## 2026-09-07 Juejin v23 Media Result

- v23 dynamically followed the changed Hermes active model `opencode-go/muse-spark-1.3-contributor`; no model was hard-coded. Production admission, five official facts, copy hygiene, claim and three-H2 gates passed.
- The final article copy was persisted and materially better, but article media failed because `section-01` expected the stale concept `repetitive task loop`. Three candidates scored 0.0 and were retained; no delivery occurred.
- Root cause: `normalize_article_sections` preferred early `draft_meta.sections` and parsed final body headings only when metadata had fewer than three items. The final body already had accurate headings for Skill directory, SKILL.md and progressive loading.
- `6516e55` makes final body headings authoritative and uses metadata only to fill a shortage. Article media focused tests: 7 passed; related media/Pipeline tests: 241 passed. Full: 1710 passed plus 37 subtests in 306.55 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v24 GEO Result

- v24 passed production admission, five official facts, final-copy hygiene, claim validation, content depth, three-H2 structure and the full platform gate. It blocked before media because the aggregate quality gate's GEO score was 30, below 40.
- Fresh GEO decomposition: direct answer and short paragraphs passed; sources, structured list, authority quote, numeric claims and FAQ failed. Adding fake numbers or fabricated quotes was rejected as a solution.
- `13c4634` appends a deduplicated Markdown source list from verified public claim-ledger URLs for article platforms. It excludes non-HTTP/private paths and does not duplicate an existing references section.
- The source list raises v24-equivalent GEO by satisfying real source and structured-list checks. Related source/GEO/media tests: 174 passed. Full: 1712 passed plus 37 subtests in 307.75 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v25 Result

- v25 generated a complete fact-grounded article but blocked before GEO/media because `跑顺一个，再做下一个。` was classified as `sentence_fragment` solely for ending in `一个`.
- `600a011` keeps conjunction-ending fragments and explicit incomplete classifier phrases such as `这只是一个。`, while allowing complete action pairs that use classifier ellipsis.
- Focused hygiene/Workflow suite: 158 passed. Full: 1713 passed plus 37 subtests in 307.44 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v26 Media Result

- v26 passed production admission, generation, fact/structure/hygiene, verified-source rendering, GEO and platform gates. Article media then failed because cover background, section 02 and section 03 used identical deterministic fallback pixels.
- Root causes: the deterministic renderer mapped every `step-by-step operating playbook` concept to one fixed workflow layout; duplicate SHA was checked only after all four assets; `SKILL.\nmd` next to Chinese evaded filename repair because both sides were Unicode word characters.
- `91adeec` adds document-anatomy and resource-stack layouts selected from final title/subtitle semantics, claims checksums under a lock per asset and retries duplicates immediately, preserves duplicate failures after eventual success, and repairs ASCII technical extensions adjacent to Chinese.
- Focused new tests: 3 passed. Related media/text/Pipeline suite: 263 passed. Full: 1716 passed plus 37 subtests in 314.67 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v27 Section-Normalization Result

- v27 passed production admission and generation, then failed before media with fewer than three mapped sections.
- Final body contained three valid content H2 headings plus `参考来源`. The media normalizer merged the short question headings as if they were transition prose and then retained the source appendix, producing only two sections.
- `adca5ef` returns three or more final body headings directly without transition merging and excludes `参考来源`, `参考资料` and `References` headings from illustration mapping. Metadata fallback behavior remains for bodies with fewer than three headings.
- Focused article media tests: 9 passed. Related suite: 264 passed. Full: 1717 passed plus 37 subtests in 313.14 seconds. Privacy 581/0; license 65/0.

## 2026-09-07 Juejin v28 Machine Pass And Manual Rejection

- v28 reached `review_required`; Pipeline and independent artifact probe passed with zero failures. GEO scored 90, media contract and platform gate passed, four published-role image hashes were unique and no audio was generated.
- Manual review still rejected the package: the YAML example used Unicode dashes instead of `---`, list numbers were split from their text, and several Agent routing behavior statements exceeded the five official facts. Section images also mixed 2752x1536 and 1024x1024.
- `7eac44d` repairs Unicode YAML delimiters and split numbered lists, extends technical-mechanism evidence checks to Agent resource/routing behavior, and crops every article section image atomically to the requested 1200x800 before semantic/hash validation.
- Focused new tests: 3 passed. Related content/media suite: 267 passed. Full: 1720 passed plus 37 subtests in 304.56 seconds. Privacy 581/0; license 65/0.
- v28 was not sent to the real Juejin publisher despite machine-green status. v29 must pass both machine and manual review.

## 2026-09-07 Juejin v29 Result

- v29 reached `review_required`; Pipeline and artifact probes passed with zero failures. Claims/hygiene/depth/quality passed, GEO scored 80, three sections were mapped to unique 1200x800 images, cover passed and no audio was generated.
- Manual review confirmed v28's YAML/list and ratio defects were gone, but H2 titles still contained their first prose sentence on the same line and source labels exposed internal names such as `verified_primary_source`.
- `72f76e5` safely splits H2 lines only when a recognized Chinese sentence opener follows, outside code fences. Verified source types map to reader labels such as `官方技术规范` and `本平台同赛道参考作品`.
- Focused tests: 2 passed. Related suite: 192 passed. Full: 1722 passed plus 37 subtests in 313.97 seconds. Privacy 581/0; license 65/0.
- v29 was not uploaded. The next step is Linux verification plus offline reconstruction; only run v30 if the output cannot be proven from the existing candidate.

## 2026-09-08 Juejin v30 Result

- v30 used the live Hermes `mimo-v2.5` and generated a new article, but cover semantics failed three attempts. No delivery occurred.
- Manual review found a more important upstream failure: unsupported `100/5000 tokens`, `20 多个` client support list, and no-fee/no-registration promises were not detected. The body also split `agentskills.io` across lines.
- `c16d943` expands numeric units/modifiers, catches support actions before named products, recognizes Chinese no-fee/no-registration promises, and derives verified domains from source URLs for line-break restoration.
- Focused claim/Workflow suite: 165 passed. Full: 1724 passed plus 37 subtests in 306.58 seconds. Privacy 581/0; license 65/0.
- v30 remains rejected regardless of its cover result. One fresh validation is required after Linux verification.

## 2026-09-08 Juejin v31 Result

- v31 reached `review_required`; Pipeline/artifact probes passed and media artifacts were structurally valid. Manual review rejected the entire copy because it invented an advanced-engineer workflow, named workflow phases, Chrome/Google provenance, commands, repository/license and quality claims outside the six-row ledger.
- Fresh `c16d943` recomputation still passed because those new syntactic variants contained no previously enumerated trigger. This established that regex enumeration cannot be the primary factual gate.
- `9b0a75c` extracts technical anchors such as Agent Skill, SKILL.md, directory, loading, routing, workflow, execution, quality and commands. Declarative technical sentences require at least two aligned verified claim anchors; questions and explicit recommendations/hypotheticals remain allowed.
- Focused related suite: 154 passed. Full: 1725 passed plus 37 subtests in 301.43 seconds. Privacy 581/0; license 65/0.
- v31 was not delivered. It is retained as the negative sample for Linux/offline verification.

## 2026-09-08 Grounded Technical Rebuild

- Simulating sentence deletion on v31 left a blank title, broken numbered list, empty code blocks and unsupported Chrome/Google/repository claims. It was rejected as an automatic recovery strategy.
- `6e6bb36` builds a conservative four-section article only from verified primary-source claims when an automated Juejin technical draft fails `unsourced_technical_fact_claim`.
- The fallback preserves the original selected topic as title, includes explicit evidence/advice boundaries, a practical checklist and reader CTA, then reruns claim, hygiene, GEO, cover and media planning.
- Related suite: 191 passed. Full: 1727 passed plus 37 subtests in 315.88 seconds. Privacy 581/0; license 65/0.

## 2026-09-08 Juejin v32 Result

- v32 triggered `grounded_technical_rebuild` from five verified primary claims, replacing the model's unsupported facts and preserving the selected topic.
- Claim validation passed, but text hygiene blocked because the same evidence-boundary sentence appeared after each of three factual sections.
- `1b3d6a9` emits that boundary once after all factual sections and extends the builder test to require both claim and full generated-text hygiene passes.
- Focused related suite: 156 passed. Full remained 1727 passed plus 37 subtests in 297.63 seconds. Privacy 581/0; license 65/0.

## 2026-09-08 Juejin v33 Result

- Linux grounded rebuild focused tests passed 2/2 after staging advanced to `9fadd9e`.
- Task9 dynamically discovered `opencode-go/muse-spark-1.3-contributor`, then Hermes returned `provider_auth_failed` before any draft, media or delivery work.
- The failure was not retried as a content error and no fallback model was silently selected. Production remains `2f4f612`; gateway is active and overnight timers remain inactive.

## 2026-09-08 Juejin v34b Grounded Depth

- v34b reused the persisted v31 contract and verified primary-source pack without a model call. The grounded rebuild passed factual, hygiene, GEO, growth and all Juejin dimensions except `base_article_quality.body_length`; media and delivery correctly did not start.
- `46b1616` adds a direct regression against `validate_article_packet().gates.body_length` and expands the evidence-safe fallback above the 1,200-character production minimum. Related regression: 175 passed. Full regression: 1727 passed plus 37 subtests. Project/privacy audit: 581 files, zero issues. License audit: 65 capabilities, zero issues.
- Next: advance Linux staging, run focused grounded/Pipeline tests, then run deterministic v34c with the private five-claim input and inspect copy plus every generated image before any real publisher call.

## 2026-09-08 Juejin v34c Visible-Workflow Semantics

- Linux staging at `9245ccd` passed the grounded builder and Pipeline tests 2/2 and project audit 581/0. v34c then passed content depth, factual, safety, growth and platform gates and entered real article media.
- Cover attempts one and two were correctly rejected as a generic robot-office visual and an unrelated game-like screenshot collage. Attempt three visibly rendered numbered INPUT/SKILL/VERIFY rectangles and a modular playbook, but scored 0.425 because `rectangle/cards` were not normalized to the expected workflow-node concept.
- `8ec883d` adds a narrow node/card/rectangle visual synonym group. Its regression requires the observed modular layout to pass while the robot-office negative remains rejected. Semantic/media related tests: 39 passed. Full regression: 1728 passed plus 37 subtests. Privacy 581/0; license 65/0.
- Next: push the commit and docs, advance clean Linux staging and run a fresh v34d directory. Do not resume the failed v34c checkpoint and do not call a real publisher.

## 2026-09-08 Juejin v34d Section-Concept Routing

- v34d completed the cover path, proving `8ec883d` fixed the modular workflow false negative. It failed closed on section 01 after three attempts; relevant flowcharts matched the AI-agent and playbook concepts but scored 0.591667 because abstract heading text remained a third, non-visible expectation.
- `f5e5cd7` changes only grounded fallback H2 headings to concrete directory, file-resource and on-demand-loading subjects. `image_routing` compiles those subjects to `structured skill directory documents` and `selective document loading sequence`; the analyzer recognizes visible folder-tree/document/loading evidence while a plain office remains negative.
- Focused regressions: 14, 1 and 128 tests passed. Full regression: 1730 passed plus 37 subtests. Project/privacy audit: 581/0. License audit: 65/0.
- Next: push and advance staging, run Linux focused tests, then start a fresh v34e. Inspect all final artifacts before any publisher call.

## 2026-09-08 Juejin v34e Final-Layout Routing

- v34e completed cover at 0.7875, section 01 at 0.7875 and section 03 at 0.775. Section 02 failed because its deterministic final attempt rendered a generic verification dashboard rather than the requested scripts/references/assets stack.
- Root cause: the deterministic renderer received `cover_design.title_text/subtitle_text` for every role, and its layout dispatch did not recognize compiled directory/loading concept IDs. Analyzer vocabulary also did not map visible SCRIPTS/REFERENCES/ASSETS labels to a directory.
- `0f3ee1c` selects cover copy only for covers, section/purpose copy for sections, routes both compiled concepts to `resource_stack` and normalizes the three visible resource labels. Focused tests: 117 passed. Full regression: 1732 passed plus 37 subtests. Privacy 581/0; license 65/0.
- Next: push and advance staging, run focused Linux tests and a fresh v34f. No real publisher call is allowed before manual artifact review.

## 2026-09-08 Juejin v34f Manual-Rejection Closure

- v34f reached `review_required`; Pipeline and artifact probe both passed. Four assets were unique and structurally complete. Manual review nevertheless rejected the package.
- Copy defects: the selected hot title retained unsupported `26 年最火`, and the generic hook repair prepended a repetitive `为什么{标题}` line. Visual defect: section 03 was an ordinary office conversation; its caption said there were no papers, but token scoring treated the negated word as document evidence and gave the loading concept 0.775.
- `522e13d` builds a conservative title from the first verified-primary claim subject, supplies a fact-relevant question hook, and adds required observable anchors for directory and loading concepts. Negated/static document nouns cannot satisfy loading without a loading action token.
- Related regression: 135 passed. Full regression: 1732 passed plus 37 subtests. Privacy 581/0; license 65/0. Next: Linux focused tests and fresh v34g, followed by manual copy and four-image review.

## 2026-09-08 Juejin v34g Accepted Recovery Canary

- Linux title/semantic/Pipeline regression at `cc71400` passed 3/3. v34g reached `review_required`; Pipeline and artifact probes passed with no failures, all 17 required capability records were at `output_verified` or `artifact_verified`, and no real publisher was invoked.
- Final title is `Agent Skill 入门：一份来源核对清单`; the 1,700-character body begins with a fact-relevant question, contains verified source facts plus clearly marked advice, and has no unsupported hot-title modifier or repeated title hook.
- Manual image review passed: topic-matched modular cover, directory/playbook section, categorized resource-box section and explicit on-demand resource-loading sequence. Cover is 1800x1200; three sections are 1200x800; four SHA-256 values are unique; no audio exists.
- The private `manual-review.json` records copy/image decisions, dimensions, hashes, empty audio list and `publisher_called=false`. Juejin recovery Canary is accepted. Next work is a fresh active-model generation check and the next platform Canary; production deployment and timers remain gated.

## 2026-09-08 Hermes Region-Proxy Recovery

- Active model remains dynamic at `opencode-go/muse-spark-1.3-contributor`. A direct minimal CLI probe returned `HTTP 403: This model is not available in your country` with exit code zero. The same probe with an explicit US proxy returned `HERMES_MODEL_OK`.
- Gateway has HTTPS proxy in its process environment, but standalone SSH/Task9 workers do not inherit it. The overnight unit loads private `proxy.env`, which exposes `US_PROXY`/`CN_PROXY` names but intentionally does not force all traffic through either route.
- `4403eb8` keeps direct-first behavior and retries exactly once only when response content proves a country/region restriction and `US_PROXY` is available. Generic 401/403 remains fail-fast. It never writes the proxy URL to attempts or pins provider/model.
- Generation/overnight focused regression: 88 passed. Full regression: 1734 passed plus 37 subtests. Privacy 581/0; license 65/0. Next: Linux real attempt evidence, then current-model Juejin or WeChat Canary when source evidence is valid.

## 2026-09-08 Juejin v35 Real-Model And Duplicate Recovery

- A complete Linux `DraftGenerator.generate` probe with only `US_PROXY` available recorded `provider_region_failed` followed by `success`, returning a normalized title/body. The same real active model then generated v35 from the 8,035-character production prompt through automatic proxy recovery.
- v35 generation succeeded in about 82 seconds. Its unsupported numeric/mechanism claims correctly triggered the verified-primary rebuild. Media then failed closed because sections 01, 02 and 03 all selected the same deterministic resource-stack fallback; one completed and the other two were rejected as duplicate SHA.
- `0f104b6` makes SKILL.md headings prefer `document_anatomy`, resource headings use `resource_stack`, and loading headings use a new `selective_loading_sequence`. Related media tests: 36 passed. Full regression: 1735 passed plus 37 subtests. Privacy 581/0; license 65/0.
- Next: push, advance Linux staging and run v35b with the real active model. Manual copy/image review remains mandatory and the publisher stays disabled.

## 2026-09-08 Juejin v35b Specific-Concept Recovery

- v35b used the real active model through direct-first proxy recovery and completed generation in about 83 seconds. Unsupported mechanism claims again triggered the verified-primary rebuild.
- Distinct deterministic layouts removed the prior duplicate checksum failure. Sections 02 and 03 completed independently. Section 01 failed because routing required both generic playbook and specific directory-document concepts; real directory imagery matched only the latter, while the deterministic SKILL.md anatomy matched only the former.
- `8f9770a` keeps only the most specific directory/loading concept when present and recognizes visible SKILL.md/YAML-frontmatter/Markdown labels as directory-document evidence. Related regression: 136 passed. Full: 1735 passed plus 37 subtests. Privacy 581/0; license 65/0.
- Next: Linux verification and fresh real-model v35c. No publisher call and no production switch before manual review.

## 2026-09-08 Juejin v35c Accepted Real-Model Canary

- Linux specific-concept tests at `5545dc7` passed 2/2. v35c dynamically used the active Hermes model, recorded direct `provider_region_failed`, retried through private US proxy and completed the same 8,035-character prompt in about 65 seconds.
- Unsupported model claims triggered verified-primary rebuild. Pipeline reached `review_required`; artifact probe passed with zero failures; all 17 required capabilities were complete.
- Manual copy review passed the fact-safe title, non-repeated opening, readable 1,700-character body and source appendix. Manual image review passed four distinct roles; cover 1800x1200 and sections 1200x800 with four unique SHA-256 values. No audio and no publisher call.
- Juejin real-model Canary is accepted. Next serial target is WeChat, but its latest public-search pack reports `ready=false` and zero strong samples; source collection/admission must be repaired before generation. Production and timers remain unchanged.

## 2026-09-08 WeChat Source Admission

- Stored WeChat browser state returned `login_required` with zero records in a bounded read-only seven-day backend collection. The prior Sogou pack contains 20 same-lane search results but zero metric-bearing strong samples, so `ready=false` remains correct.
- The absolute WeWrite CLI exists outside the non-interactive PATH. Its live `hotspots --limit 20` returned Weibo, Baidu and Toutiao aggregate boards, not WeChat first-party keywords or activities.
- `77ea76f` requires WeChat-hosted URLs for both creator-backend and WeWrite official contracts, while retaining a specific Sogou rejection. Cross-platform rows remain usable only as general trend references.
- Focused source tests: 24 passed plus 4 subtests. Full: 1736 passed plus 37 subtests. Privacy 581/0; license 65/0. WeChat generation remains blocked until a fresh first-party backend/WeChat URL signal exists.

## 2026-09-08 WeChat Bounded Evergreen Fallback

- Private WeChat slots specify only platform, format, estimate and weekdays; they contain no executable editorial fallback. The growth playbook had columns and dedupe rules but no versioned evergreen topics, so exhausted recapture could only block forever.
- `6b336ec` adds four advice/Q&A evergreen directions to the WeChat recovery playbook and compiles one only after a real requery adapter completes all configured rounds with zero candidates. It skips every reserved 14-day fingerprint and blocks if the pool is exhausted.
- The selected row is labeled `editorial_calendar`, carries strategy source/calendar column/date/dedupe evidence, has no `associated_hotspot`, and receives no hotspot score. No requery adapter means no fallback.
- Related strategy/overnight tests: 78 passed. Full: 1739 passed plus 37 subtests. Privacy 581/0; license 65/0. Next: Linux prepare-only verification, then a fresh WeChat content/media Canary under the safe draft boundary.

## 2026-09-08 WeChat v2 And Expanded Intelligence Registry

- Linux prepare-only v2 selected `先加工具还是先拆任务？一张边界清单帮你判断` after three empty recaptures. It carried strategy source, calendar column, date and dedupe, no hotspot identity, and a compiled strategy with six pillars and six structures in bounded input.
- WeChat content v2 preserved WeWrite HTTP 400 evidence, then used the explicit Hermes writer with direct regional failure and US proxy success. Writer gate passed as `hermes_writer`; the 1,953-character article was blocked only by old platform gates that unconditionally required GitHub dual channels and unavailable hot-account metadata.
- `9c819aa` makes editorial mode require account analysis, topic/article plan, workflow inputs, growth playbook, three recaptures and a one-item batch. Same-lane/trend and GitHub gates become not-applicable only for a fully evidenced editorial fallback. The toolchain writes those inputs and actual writer identity into the packet.
- `df736e6` adds a single intelligence registry covering 12 publishing targets and 11 reference sources across CN/intl regions. Default hot-work collection and parameter-pack coverage are registry-driven; cross-platform references are separately scored and cannot make a target ready.
- Related regression: 204 passed plus 4 subtests. Full: 1749 passed plus 37 subtests. Privacy 586/0; license 65/0. Next: Linux registry/collection smoke and WeChat v3 content/media Canary.

## 2026-09-08 Intelligence Reference Integrity

- Initial Linux smoke executed WeWrite aggregate, CSDN and Dev.to adapters. Aggregate returned 20 real rows, while CSDN/Dev.to returned synthetic `source_fallback` hypotheses. The ad hoc smoke incorrectly labeled every non-empty result `ok`, and the parameter pack expanded from 12 targets to 17 because it unioned observed reference platforms.
- `8e36bb7` keeps default pack keys equal to the 12 publishing targets, adds platform plus `identity_role=unavailable` to synthetic fallbacks, and excludes them from `cross_platform_references` because they lack real URL/provenance.
- Reference-integrity tests: 62 passed plus 4 subtests. Full: 1750 passed plus 37 subtests. Privacy 586/0; license 65/0.
- Next: Linux official `TrendCollector.collect_with_report` smoke, then WeChat v3 under the safe publisher boundary. Production and timers remain unchanged.

## 2026-09-08 WeChat v3-v4 And Live Intelligence Smoke

- Official Linux TrendCollector smoke ran 12 sources in about 15 seconds: 7 ok, 5 degraded, 0 failed, 135 rows. WeWrite aggregate and CSDN returned real URL rows; search-only unavailable sources stayed degraded. The parameter pack had exactly 12 targets; WeChat stayed not-ready and its eight references were all `target_ready_eligible=false`.
- WeChat v3 writer fallback succeeded and produced 2,009 characters. It remained blocked because `research_attempts` was on the task row but absent from brief, preventing editorial mode recognition; no-AI-slop found one binary reference-boundary sentence.
- `ff66fa3` copies recapture evidence into brief and deterministically rewrites that sentence. WeChat v4 then completed initial generation but its Hermes writer fallback ended with a real HTTP 429 after the route retry.
- `6b64239` performs one delayed retry on the same direct/US route for transient writer errors, then fails closed. Related tests: 191 passed. Full: 1752 passed plus 37 subtests. Privacy 586/0; license 65/0.
- Next: Linux v5 content/media Canary. Production and timers remain unchanged.

## 2026-09-08 WeChat v5 Final Slop Gate

- v5 completed active-model generation and explicit Hermes writer fallback, producing a 1,861-character article. Writer, account, recapture, editorial, topic, workflow, growth and batch gates passed.
- The only failure was external `no_ai_slop_check`: line 69 contained `这就是真正的改进清单`, classified as a false-profound ending. No media or publisher ran.
- `f76a3c2` rewrites the observed phrase to `这些断点组成下一轮改进清单` and retains the external checker as final authority.
- Related tests: 175 passed. Full: 1753 passed plus 37 subtests. Privacy 586/0; license 65/0. Next: Linux v6 content/media Canary.

## 2026-09-08 WeChat v6 Short Binary Contrast

- v6 completed active-model and Hermes-writer generation with a 2,270-character body. All operational/content-mode gates passed; only external no-AI-slop failed.
- The exact sentence was `卡住的根本不是写，而是等确认、缺口径`. The prior contrast regex required at least two characters after `不是`, so the single character `写` escaped.
- `15e3a3c` accepts one-character contrast subjects and consumes optional `根本` to avoid producing `根本真正关键`. Related tests: 75 passed. Full: 1754 passed plus 37 subtests. Privacy 586/0; license 65/0.
- Next: Linux v7; media and publisher remain unopened until copy passes.

## 2026-09-08 WeChat v7 Explicit Visual-Plan Recovery

- v7 produced a 2,084-character article and passed the writer, content-mode, platform and no-AI-slop gates. Its cover passed semantic validation, but section 01 exhausted SenseNova, Pixazo and Cloudflare retries with `semantic_match_below_threshold`.
- The article already contained three concrete `配图计划` lines. The media bridge ignored them, used the H2 plus a generic purpose, and therefore requested raw Chinese marketing text while providers returned generic office scenes.
- `73de8ea` extracts the visual plan adjacent to each final H2, feeds it into prompts and semantic requests, and compiles three observable concepts for tool-tab overload, goal/input/output and four-panel boundary checks. The 0.6 semantic threshold and duplicate gates remain unchanged.
- Related regression: 154 passed. Full regression: 1755 passed plus 37 subtests. Privacy audit: 586 files, zero issues. License audit: 65 capabilities, zero issues.
- Next: advance isolated staging, run Linux focused tests and a fresh v8 WeChat content/media Canary. The real draft publisher remains disabled pending manual article, cover and all-section review.

## 2026-09-09 WeChat v21 Accepted Content/Media Canary

- v8 proved the explicit visual plans entered provider prompts, but manual review rejected generic tool imagery and visible provider marks. v9-v20 retained every failed candidate while closing plan persistence, provider branding, multilingual labels and image-semantic evidence gaps.
- The WeChat toolchain now persists each `配图计划` in `draft_meta.section_image_map`; the media bridge consumes that mapping after reader-facing body cleanup. Three concrete concepts route to distinct Chinese knowledge-card layouts.
- SenseNova declares possible embedded branding during both new calls and old-cache finalization. Branded cover or section candidates fail and rotate. The final deterministic fallback is limited to the WeChat article path; other platform recovery behavior is unchanged.
- v21 completed four unique images. Scores were 0.8/0.88/0.88/0.82; final providers were one `cover_renderer` plus three `knowledge_card_renderer` outputs. Manual review passed title completeness, Chinese labels, semantic roles, watermark absence and SHA uniqueness.
- Final regression: 1764 passed plus 37 subtests. Project/privacy audit: 586/0. License audit: 65/0. Private `manual-review.json` records `publisher_called=false` and explicitly excludes live draft or 12-platform proof.
- Next: fast-forward staging to the final evidence-isolation commit, then continue the serial platform Canary matrix. Production and timers remain unchanged.
