# Production Runtime V8 Status

Last updated: 2026-09-04 Asia/Shanghai (P10 bootstrap hardening verified locally)

## Current state

- Phase: P10 real Canaries, deployment, rollback, and controlled activation
- Production timers observed on 2026-09-02: all related timers disabled; overnight/supervisor inactive.
- Production release observed on 2026-09-02: `unified-capability-v7-149362f`.
- GitHub feature branch: `codex/unified-capability-closure@149362f`
- Development branch: `codex/production-runtime-v8`
- Latest complete regression on this branch: 1607 passed + 37 subtests.

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
| 12-platform Canary and deployment | Codex primary | deploy/systemd tests and four coordination documents | in_progress | commit/push bootstrap hardening; implement explicit system/user scope before signed server preparation |

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
