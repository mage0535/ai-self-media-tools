# Worktree Task Triage - 2026-07-18

This triage separates current local changes into sync-worthy work, optional archival work, and cleanup candidates.

## Sync-Worthy

These changes directly harden the all-channel Local Ops Lab and Hermes workflows.

- Channel hard constraints: `AGENTS.md`, `docs/CHANNEL_DEVELOPMENT_CONSTRAINTS.md`
- All-channel operating rules: `docs/CHANNEL_CONTENT_OPERATIONS_PLAYBOOK.md`, `docs/CONTENT_OPERATIONS_QUALITY_DIRECTIVE.md`, `config/channel_content_rulebook.json`, `scripts/validate_channel_rulebook.ps1`
- Delivery health gate: `content_platform/delivery_health.py`, `content_platform/pipeline.py`, `content_platform/cli.py`, `config.example.json`, `scripts/install.py`, `tests/test_delivery_health.py`, `tests/test_pipeline.py`, `tests/test_cli_v2.py`
- Strategy and media quality gates: `content_platform/strategy_router.py`, `content_platform/media_quality.py`, `content_platform/content_policy.py`, `tests/test_strategy.py`, `tests/test_media_quality.py`
- Domestic platform recovery and adaptation: `content_platform/formatters.py`, `content_platform/platform_catalog.py`, `content_platform/platform_checks.py`, `tests/test_platform_checks.py`
- Social-auto-upload and Video Channels runtime compatibility: `content_platform/paths.py`, `content_platform/readiness.py`, `content_platform/publishers.py`, `content_platform/tool_registry.py`, `tests/test_publishers_v2.py`, `tests/test_social_auto_upload_runtime.py`
- Privacy and evidence boundary audit: `content_platform/project_audit.py`, `tests/test_project_audit.py`
- Continuity record: `docs/CONTINUOUS_DEVELOPMENT.md`

## Archived Design History

These are useful as design history but are not required by runtime code, so they have been moved out of the active plan/spec paths:

- `docs/superpowers/archive/2026-07-17-domestic-content-quality-rebuild/implementation-plan.md`
- `docs/superpowers/archive/2026-07-17-domestic-content-quality-rebuild/design.md`

Keep them for traceable design rationale. They can be omitted from a lean runtime deployment package.

## Cleanup Candidates

No currently visible tracked or untracked file is an obvious disposable generated artifact. Do not delete code, rules, tests, or docs from this list without an explicit cleanup decision.

If a lean commit is needed, the archived design-history files can be excluded. Runtime evidence, cookies, screenshots, browser profiles, and local private artifacts are already ignored and do not appear in the current Git status.

## Hermes-Only Cleanup Candidates

These were found by the Hermes-side project audit after sync, but they are not present in the local worktree status:

- `docs/SERVER_WORKFLOWS_20260714.md`: contains a Hermes private absolute path. Sanitize or move to a private runtime note before treating the remote tree as public-clean.
- `tmp/codex_publishers/shipinhao_cookie_health.py`: appears under a scanned `tmp` path and matches the forbidden cookie filename pattern. Move it under ignored runtime evidence or delete it after confirming it is no longer needed.

## Verification

- Local focused tests: `64 passed`
- Rulebook validation: `channel rulebook ok: 14 channels`
- Project audit: `ok: true`, `issues: []`
- Hermes focused tests after sync: `64 passed`
- Hermes project audit after sync: current sync package is functional, but two pre-existing Hermes-only cleanup candidates remain listed above.

## Notes

- Public-safe repo files use `hermes://...` or `hermes_skill:...` identifiers instead of Hermes private absolute paths.
- The Hermes deployment can resolve those identifiers to its local private paths at runtime.
