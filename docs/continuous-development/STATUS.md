# Production Runtime V8 Status

Last updated: 2026-08-31 Asia/Shanghai (P9 identity/retry submilestone verified)

## Current state

- Phase: P9 delivery postchecks and Publication Ledger
- Production timer: disabled/inactive
- Production release observed: `149362f`
- GitHub feature branch: `codex/unified-capability-closure@149362f`
- Development branch: `codex/production-runtime-v8`
- Latest complete regression on this branch: 1569 passed + 37 subtests.

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
| Delivery postcheck and ledger | Codex primary | publication ledger/store/collector and P9 tests | in_progress | commit identity/retry; implement unified postcheck capability evidence |
| 12-platform Canary | unassigned | Task9 scripts/reports only | pending | 12/12 artifact-verified |

## Confirmed blockers

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
- Project/privacy audit initially detected private absolute paths in coordination docs; paths were replaced with stable logical aliases and must be re-audited before commit.
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
