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
- Juejin v35c is the first accepted real-active-model article Canary: direct-first region recovery, weak-model factual rebuild, media generation, capability/artifact probes and manual copy/image review all passed in one fresh run. The real publisher was intentionally not called.
- WeChat source probing found the stored creator-backend state expired and WeWrite `hotspots` returning Weibo/Baidu/Toutiao aggregate trends. Commit `77ea76f` prevents any non-WeChat URL from being promoted to a WeChat official keyword/activity contract.
- Commit `6b336ec` closes the no-source dead end without inventing a hotspot: after three empty same-platform recaptures, WeChat may select a versioned strategy evergreen, provided its 14-day fingerprint is unused. The result is explicitly `editorial_calendar` with no associated hotspot.
- WeChat v2 proved the explicit Hermes writer fallback but exposed GitHub-only metadata gates on a Q&A evergreen. Commit `9c819aa` validates required operations by content mode and compiles the real editorial/writer evidence into the packet.
- Commit `df736e6` replaces fixed intelligence platform lists with one registry: all 12 publishing targets plus 11 domestic/international reference sources. Target and reference evidence stay separate and every ranked row exposes seven scoring dimensions.
- Linux smoke exposed synthetic search fallback rows being counted as successful reference collection and reference platforms expanding the target pack. Commit `8e36bb7` keeps the target pack at 12 and labels synthetic rows unavailable so they cannot enter reference evidence.
- WeChat v3 reached the mode-aware gate but exposed missing recapture evidence in the brief and one remaining binary-contrast slop phrase; `ff66fa3` closes both. WeChat v4 then hit a real Hermes 429, and `6b64239` adds one bounded same-route writer retry.
- WeChat v5 passed every operational/content-mode gate except the external no-AI-slop checker, which caught one false-profound checklist ending. Commit `f76a3c2` deterministically rewrites that observed phrase before the unchanged external gate.
- WeChat v6 again reached only the final slop gate; a single-character binary contrast escaped the prior minimum-length regex. Commit `15e3a3c` handles that general pattern without weakening the external checker.
- WeChat v7 passed copy and platform gates but exposed that explicit `配图计划` lines were ignored. Commit `73de8ea` binds each final H2 to its adjacent visual plan and compiles observable visual concepts before provider routing; a fresh v8 media Canary remains required.
- WeChat media v8-v20 exposed provider branding, semantic false positives and multilingual OCR drift. v21 accepted four unique, watermark-free, topic-matched images after structured visual-plan persistence, provider rotation and hash-bound visual evidence; it is content/media proof only, not a live draft.
- Sol execution resumed on 2026-09-10. Read-only B0 verification confirmed production remains signed `2f4f612` with timers inactive; the server mutable main repository has protected dirty work. A TDD B1 milestone adds the unified three-layer topic decision to overnight pre-generation evidence and passes 1818 tests plus 37 subtests. CLI/MCP/Pipeline authority and Linux staging remain pending.
- The next B1 milestone routes Pipeline, MCP, CLI auto and overnight through the same `topic_decision_v1` evidence contract and passes 1820 tests plus 37 subtests. Legacy ranking remains a compatibility path until B2 collector contracts and shadow comparisons pass; production is unchanged.
- B2 now requires complete same-platform work identity, timestamps, query, nested metrics and raw snapshot hash, preserves them through the compact hot-work handoff, and records legacy/unified shadow differences. Full regression is 1823 tests plus 37 subtests; live collector completeness and authoritative cutover remain pending.
- A read-only audit of the server's 2026-09-10 hot-work pack reports 0/12 strict-ready platforms: WeChat has incomplete legacy rows, nine targets have no samples, and X plus Shipinhao are omitted. Collector repair must follow these distinct statuses; no missing identity may be synthesized.
- The contract-gap reporter now distinguishes `platform_missing`, `no_samples` and `contract_incomplete`; its final regression is 1824 tests plus 37 subtests with zero failures.
- Hot-work collection now defaults to every registry publishing target, labels explicit subsets and rejects unknown platform names. Full regression is 1825 tests plus 37 subtests; live collector smokes remain next.
- Isolated public smokes found 49 Bilibili/Juejin/YouTube discovery rows but zero strict-ready rows. Bilibili now has a tested public-detail enrichment contract; Linux live confirmation remains pending before Juejin and YouTube adapters.
- Bilibili's public detail API returned HTTP 412, so complete visible search cards now form an independent strict evidence route; normal login navigation no longer causes a false login-wall status. Full regression is 1829 tests plus 37 subtests; Linux confirmation remains pending.
- The first live retry exposed Bilibili's split-title DOM ordering. A follow-up parser reconstructs title fragments between duration and author while keeping neighboring card text out; another isolated live rerun is pending.
- Bilibili Linux staging acceptance now passes: 24 direct discovery rows and 10/10 strict contract-ready top samples on `3e0eed1`. This does not change production or establish any other platform.
- Juejin discovery works but inspected results are outside 30 days, and its public detail endpoint returned an application error. Juejin remains blocked pending embedded-page or authenticated detail evidence; publication dates cannot be inferred.
- Juejin now has a tested visible-card contract with a hard 30-day publication boundary and card snapshot evidence. Full regression is 1831 tests plus 37 subtests; Linux staging acceptance remains pending.
- Juejin live staging found one complete recent sample. Top3 readiness now requires three complete samples and reports 1–2 as insufficient; navigation login text no longer creates a false auth failure. Full regression is 1833 tests plus 37 subtests.
- Juejin current-month collection now uses the observed public latest-published route (`type=0&sort=1`) while preserving engagement and strict Top3 gates. Full regression is 1834 tests plus 37 subtests; Linux acceptance remains pending.
- Juejin defaults now use three live-probe-selected recent queries and retain RAG Agent only for bounded recapture. Full regression is 1835 tests plus 37 subtests; an override-free Linux run remains pending.
- Juejin override-free Linux acceptance now passes on `13f98f9`: eight deduplicated recent rows and 8/8 strict contract-ready pack samples. This is collector evidence only; content and draft Canaries remain separate.
- YouTube now uses the browser-verified This month filter and strict visible-card evidence for IDs, channels, ages and views. Full regression is 1837 tests plus 37 subtests; Linux acceptance remains pending.
- The first YouTube Linux retry exposed live metadata ordering and login-navigation false positives. The parser and classifier now match saved real DOM while retaining age/view/CAPTCHA gates; full regression is 1838 tests plus 37 subtests.
- The second retry exposed undersized YouTube anchor contexts. Extraction now uses full `ytd-video-renderer` containers without changing other platforms; full regression is 1839 tests plus 37 subtests.
- The third retry found a selector collision: YouTube title anchors matched the generic video-class selector themselves. YouTube now uses only real renderer custom elements; a fourth Linux run remains pending.
- YouTube override-free Linux acceptance now passes on `dc8d366`: 24 direct monthly rows and 10/10 strict pack samples. This is collector evidence only; generation and handoff Canaries remain separate.
- Zhihu now enriches real search URLs from public detail metadata, preserves votes/comments semantics and rejects answer 403 or out-of-window rows. Full regression is 1841 tests plus 37 subtests; Linux acceptance remains pending.
- Zhihu Linux staging retained two complete recent articles but did not reach the required Top3; bounded query expansion added none. Status is `insufficient_sample_count`, with official topic/hot-list detail or a later snapshot next.
- At handoff, update all four documents with exact commands/results, remaining gaps, and file ownership. Do not describe an old server observation as a fresh health check.
