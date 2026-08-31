# Production Runtime V8 Status

Last updated: 2026-08-31 Asia/Shanghai (P5 evidence-level submilestone verified)

## Current state

- Phase: P5 unified capability/MCP/Skill execution evidence
- Production timer: disabled/inactive
- Production release observed: `149362f`
- GitHub feature branch: `codex/unified-capability-closure@149362f`
- Development branch: `codex/production-runtime-v8`
- Latest complete regression on this branch: 1550 passed + 37 subtests.

## Active work

| Work item | Owner | Files reserved | State | Next verification |
|---|---|---|---|---|
| Runtime code/config/data convergence | Codex primary | `content_platform/runtime_paths.py`, `content_platform/mcp_server.py`, systemd/deploy/runtime tests | committed `c9babbd` | verify gateway drop-in and shared DB during deployment |
| Automated admission contract | Codex primary | `content_platform/task_admission.py`, `content_platform/pipeline.py`, `content_platform/mcp_server.py`, admission tests | committed `4d9c567` | server verification during deployment |
| Platform artifact completion contract | Codex primary | `content_platform/artifact_contract.py`, pipeline/store recovery, P3 tests | committed `277f1e3` | server fault injection during deployment |
| Pre-generation operations/source gates | Codex primary | `content_platform/pre_generation_gate.py`, pipeline and P4 tests | committed `6b9052b` | production fault injection during deployment |
| Unified capability execution evidence | Codex primary | capability registry/router/DAG and P5 tests | in_progress | commit evidence levels; classify 19 inventory-only capabilities |
| Renderer retry/checkpoint | unassigned | `scripts/film_renderer.py`, renderer tests | pending | failed shot retries and stops early |
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
- P5 next failing test: an assets/render adapter without file/hash evidence must remain `output_verified`, not be promoted to `artifact_verified` by stage alone.
- P5 evidence-level focused regression: `150 passed`; full regression: `1550 passed, 37 subtests passed`.
- Registry now declares an explicit verification level for all 26 executable capabilities.
- Artifact verification requires readable non-empty files and matching SHA-256; effect verification additionally requires a passing named probe bound to a verified artifact hash.
- P5 remains in progress: 19 inventory-only capabilities still require executable/consulted/excluded classification and durable reasons.

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
