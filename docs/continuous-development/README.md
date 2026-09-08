# Production Runtime V8 Continuous Development

This directory is the coordination source of truth for the production-runtime-v8 work.

## Required reading order

1. `README.md` (this file) - coordination and ownership protocol.
2. `STATUS.md` - current phase, active owner, blockers, and next command.
3. `DECISIONS.md` - architecture decisions that must not be silently reversed.
4. `SERVER_EVIDENCE.md` - observed production facts and verification evidence.

Then read `../superpowers/plans/2026-08-31-production-runtime-v8.md` for the implementation sequence and acceptance gates. Re-read all four coordination files after an interruption; an earlier chat summary is not the current source of truth.

## Collaboration protocol

- Branch: `codex/production-runtime-v8`
- Worktree: `D:/Onedrive/CodeX/worktrees/ai-self-media-production-runtime-v8`
- Base: `149362f23a93f64d35ae16d2f17bb38080ec9dd3`
- Do not edit the private mutable runtime (`$PRIVATE_RUNTIME`) directly.
- Do not enable overnight timers until `STATUS.md` records all production gates as passed.
- Before editing a shared file, record the owner and file list in `STATUS.md`.
- Each change uses failing test -> minimal implementation -> targeted tests -> full tests -> commit.
- A task is complete only after updating `STATUS.md` and adding durable evidence to `SERVER_EVIDENCE.md`.
- Never report `review_required`, `approved`, uploader success, or artifact existence as a completed platform delivery.

## Shared-file lock convention

Record one row per active work item in `STATUS.md`. Only one owner may hold a file at a time. If work overlaps, split by adapter/test file rather than editing the same core module concurrently.

## Current handoff

- P1-P4 are committed local milestones; production deployment remains prohibited.
- P5 capability evidence and inventory governance are committed local milestones.
- P6 bounded Hermes worker sessions and generation SLOs are a committed local milestone.
- P7 image checkpoint and verified provider fallback is a committed local milestone.
- P8 video shot retry, checkpoint, and final-effect evidence is a committed local milestone.
- P9 publication identity and metric retry are a committed submilestone.
- P9 postcheck capability is implemented and verified as a local submilestone.
- P9 delivery trace persistence and negative-path hardening are a locally verified milestone.
- P10 real media Canaries, Linux deployment, live publisher verification, and rollback rehearsal are the next workstream. Tests with replacement publishers are not live platform proof.
- P10 starts with a read-only server baseline, then a signed immutable release candidate with timers kept disabled. Activation and rollback evidence must be recorded before any live Canary.
- The legacy current release is not a valid rollback artifact because runtime files and tracked drift are present. Use `prepare_bootstrap_release` from a clean Git source to create a signed rollback without activating it.
- Bootstrap preparation now rejects unsafe names and unresolved path boundaries before side effects, and cleans up only outputs proven to belong to its own transaction. Do not bypass these guards with ad hoc copies.
- Server activation must use the same systemd scope as the installed production units. The current server uses system scope; scope convergence remains a P10 gate.
- Deployment and acceptance now accept `--systemd-scope user|system`; this is command routing, not proof of a completed activation. Expanded effective paths and gateway-root convergence still require Linux verification.
- On every resume, compare server HEAD, dirty-file names, and available timestamps/hashes before deployment. Preserve uncommitted server work; unchanged HEAD alone does not establish unchanged content.
- Effective-unit validation compares expanded runtime paths and exact environment assignments. External scraper environment paths must not be mistaken for the service's ExecStart; missing production roots still block activation.
- Effective-path implementation `de506e2` passed local full regression and Linux deployment-focused regression. Continue with signed candidate preparation and gateway/config convergence, not timer restoration.
- Real private-config preflight currently rejects three external Hermes tool bridges. Do not remove tools or loosen the release boundary to obtain a passing signature. Resolve explicit external-tool ownership/contracts first; fail-fast preflight now avoids expensive builds for known incompatible config.
- External bridge trust uses an explicit private-config contract bound to config key, absolute path under Hermes home, regular-file status, and SHA-256. Passing this contract proves dependency identity only, not invocation or content impact.
- Stable `$CURRENT_RELEASE` script aliases are rewritten to the explicitly supplied candidate code root before filesystem resolution. Canary callers pass their code root directly rather than relying on ambient environment.
- Signed bootstrap rollback is now the clean `7bfa13c` runtime, not the failing historical `149362f` source. It is prepared and frozen but inactive. Gateway runtime-root drop-in remains required before forward activation.
- The project owns only `ai-self-media-runtime.conf` under the Hermes gateway drop-in directory. Activation snapshots and restores that file and gateway state while preserving unrelated Hermes drop-ins.
- Forward deployment may validate an isolated candidate config and atomically promote it to the stable private config before gateway restart. A failed activation restores the previous private config bytes and mode.
- Retain the dedicated WeChat metrics timer in release inventory; its definition is not authorization to enable it. Config rollback now precedes old-service restart in the failure path; Linux/live transaction verification remains required.
- Linux staging at `ec08d1c` passed 109 operational/deployment/systemd tests, including POSIX mode and config-before-restart checks. Live activation and rollback rehearsal remain pending.
- Release metadata must reference a durable mode-600 private config snapshot under shared data, never a staging candidate path. Rollback promotes that signed snapshot before gateway start and restores the previous active config on failure.
- Failed deployments persist a private failure report and remove only transaction-owned release, config snapshot and attestation. Preserve the report and system journal before retrying.
- Deployment removes only service drop-ins that override project-managed runtime roots, WorkingDirectory or ExecStart. Other resource/provider/function drop-ins remain; conflicts are restored on failure.
- Every project service and gateway child environment sets `PYTHONDONTWRITEBYTECODE=1`; root-run Python must not create caches inside signed immutable releases.
- Hermes `content-platform` MCP has its own explicit child environment. Production deploy/rollback atomically converges that private YAML block before gateway restart and restores it before old gateway recovery; systemd inheritance alone is not sufficient.
- Production currently runs signed `2f4f612`; timers remain disabled. Runtime convergence and platform trend routing are deployed; the next work is completing missing platform inputs, real serial content Canaries, and publisher postchecks.
- Juejin Canary v18 proved the article media contract and all four image semantics, but its copy was rejected for identifier splitting and unsupported tool/install claims. Commit `4b141c4` keeps article jobs out of the narration path, revalidates model-based humanizer output, blocks unsupported recommendations, and prevents optional providers from failing required-capability evidence.
- Juejin Canary v19 passed its Pipeline and artifact probes but exposed malformed fenced content and additional unsupported technical claims. Commit `3c5de37` normalizes known model formatting damage and enforces final post-factual-repair prose hygiene before media generation.
- Follow-up `fd1e9c0` closes the dotted-identifier gap so claims containing `SKILL.md` or `.agent/skills` cannot evade mechanism validation.
- Juejin v20 proved the old 5,603-character retry could still time out. Commit `b63547e` retains the full first attempt but uses a minimal verified-context contract for the final bounded retry.
- Juejin v21 proved that a hot-title snapshot is insufficient evidence for a technical tutorial. Commit `4ce550d` requires a hash-bound technical fact pack and three readable H2 sections before article media.
- Audit then proved Task9 cases were not setting production runtime mode. Commit `6bcdcaa` makes every real Pipeline Canary exercise production admission and restores the caller environment afterward.
- Juejin v22 passed production admission and official fact-pack loading but exposed an unmatched prose quote. Commit `a162adb` safely repairs unmatched non-code quotes and persists complete blocked drafts for deterministic recovery.
- Juejin v23 passed copy gates but exposed stale image-section routing. Commit `6516e55` binds article images to final H2 headings before falling back to generator metadata.
- Juejin v24 passed facts/structure but failed GEO because verified sources were not rendered. Commit `13c4634` appends a deduplicated public source list from the claim ledger before GEO and media.
- Juejin v25 exposed a Chinese classifier-ellipsis false positive. Commit `600a011` permits complete verb phrases such as `跑顺一个，再做下一个` while retaining real fragment checks.
- Juejin v26 reached media but exposed identical deterministic fallback images. Commit `91adeec` adds semantic layout variants, per-asset duplicate retry and Chinese-adjacent filename repair.
- Juejin v27 exposed short H2 headings being merged and the references appendix being illustrated. Commit `adca5ef` preserves body headings and excludes source sections from media mapping.
- Juejin v28 achieved machine-green output but failed manual copy/media review. Commit `7eac44d` repairs weak-model YAML/list formatting, validates Agent routing claims and normalizes section images before semantic gates.
- Juejin v29 achieved machine-green media with uniform ratios but retained heading/body joins and internal source labels. Commit `72f76e5` repairs those reader-facing defects.
- Juejin v30 exposed unsupported token counts, client support lists and free promises that escaped claim detection. Commit `c16d943` closes those variants and restores domains from verified source URLs.
- Juejin v31 proved enumerating claim regexes is insufficient. Commit `9b0a75c` adds technical-anchor coverage so declarative technical assertions must match verified claim anchors.
- Commit `6e6bb36` adds a verified-primary-claim rebuild for unsafe automated Juejin technical drafts, avoiding both blind model retries and destructive sentence deletion.
- Juejin v32 exercised that rebuild and exposed repeated boilerplate; `1b3d6a9` consolidates the evidence boundary so rebuilt copy passes hygiene.
- Juejin v33 stopped before generation because the live Hermes `muse-spark-1.3-contributor` returned `provider_auth_failed`; no media or delivery work was started.
- Juejin v34b exercised model-independent recovery with the verified five-claim fact pack. It passed claim, hygiene, GEO, growth and every platform-quality dimension except the real 1,200-character article minimum. Commit `46b1616` expands the conservative fallback with advice-only task framing, resource planning, execution review and evidence-boundary checks while preserving the factual gate.
- Juejin v34c passed all copy and platform gates and reached real image generation. The third cover visibly contained numbered INPUT/SKILL/VERIFY modules and a modular playbook but failed deterministic semantic scoring because rectangles/cards were not normalized as workflow nodes. Commit `8ec883d` adds that narrow visual equivalence with an explicit robot-office negative control.
- Juejin v34d completed its cover but showed that abstract H2 text was still appended as an impossible third visual requirement; otherwise relevant flowcharts stopped at 0.591667. Commit `f5e5cd7` gives the grounded article concrete file-directory/resource/loading headings and compiles them to visible section concepts.
- Juejin v34e completed the cover and two sections but exposed a renderer bug: deterministic section fallbacks reused cover typography and ignored the selected section concept. Commit `0f3ee1c` routes section-specific copy and directory/loading concepts into the final deterministic layout and analyzer vocabulary.
- Juejin v34f was machine-green but manual review rejected its unsupported hot-title wording, mechanically repeated question and a false-positive loading image whose caption explicitly said no papers were present. Commit `522e13d` derives safe fallback titles from verified claims and requires process concepts to contain their observable action anchor.
- Juejin v34g is the first accepted model-independent recovery package: production admission, copy/fact/platform gates, four real images, capability manifest, artifact probe and manual review all passed. It remains a safe Task9 handoff package, not a real Juejin draft or evidence that all platform Canaries are complete.
- A direct Hermes CLI probe exposed that gateway proxy state is not inherited by standalone workers and that a regional HTTP 403 exits with code zero. Commit `4403eb8` classifies response content and retries only explicit RegionError failures once through the configured `US_PROXY`, without pinning a model or logging the proxy value.
- Juejin v35 proved the new proxy recovery with the real active Hermes model, then exposed identical deterministic section fallbacks under concurrency. Commit `0f104b6` gives document anatomy, resource stack and selective loading their own deterministic layouts so semantic recovery does not create duplicate assets.
- Juejin v35b proved the distinct layouts removed duplicate SHA failures but exposed over-constrained section semantics. Commit `8f9770a` makes the most specific directory/loading concept authoritative and recognizes visible SKILL.md/frontmatter/Markdown anatomy as directory-document evidence.
- At handoff, update all four documents with exact commands/results, remaining gaps, and file ownership. Do not describe an old server observation as a fresh health check.
