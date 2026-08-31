# Production Runtime V8 Status

Last updated: 2026-08-31 Asia/Shanghai (P1 local verification complete)

## Current state

- Phase: P1 runtime convergence
- Production timer: disabled/inactive
- Production release observed: `149362f`
- GitHub feature branch: `codex/unified-capability-closure@149362f`
- Development branch: `codex/production-runtime-v8`
- Latest known complete regression before this branch: 1524 passed + 37 subtests; post-baseline changes require a fresh full run.

## Active work

| Work item | Owner | Files reserved | State | Next verification |
|---|---|---|---|---|
| Runtime code/config/data convergence | Codex primary | `content_platform/runtime_paths.py`, `content_platform/mcp_server.py`, systemd/deploy/runtime tests | local_complete | commit P1; verify gateway drop-in and shared DB during deployment |
| Automated admission contract | unassigned | `content_platform/task_admission.py`, MCP admission tests | pending | reject production job without run contract |
| Platform artifact completion contract | unassigned | pipeline acceptance modules and tests | pending | no media means no review/approved |
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
