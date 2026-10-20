# ADR-001: Integrate evidence-backed viral breakdown into topic admission

## Status
Accepted

## Date
2026-09-12

## Context

The project used platform trend signals and topic independence checks, but a topic could enter generation without a complete same-lane breakdown of representative works. In practice this caused four failure modes:

- global trend data was mistaken for platform-native evidence;
- old analysis files were reused for a new day;
- plans/manifests claimed templates or motion without real work evidence;
- blocked platforms silently degraded into topic generation.

A complete breakdown is useful, but doing the full six-dimension analysis for every platform every day would block production.

## Decision

Add an evidence-backed `viral_breakdown_v1` module and integrate it with the existing same-lane and hot-work flows.

Each reference work may provide the complete media dimensions:

1. `content_form`
2. `copy_or_script`
3. `writing_style`
4. `content_structure`
5. `topic_direction`
6. `asset_analysis`
7. `theme_template`
8. `voiceover`
9. `motion_combination`
10. `transition_combination`

The evidence record must also include a native work URL or equivalent visual evidence. Video platforms require verified motion evidence and visual evidence. Static article platforms may use `motion_combination.status=not_applicable` with an explicit reason.

The workflow uses three operating cadences:

- daily light scan: fresh native signals and candidate works;
- weekly deep breakdown: one or two works per platform;
- monthly style review: template, visual structure, and motion fatigue review.

Breakdown reports are cached for seven days by default. An expired or incomplete report is never silently reused as `ready`.

Current/future topic admission is fail-closed: `platform_source_matrix` must contain a same-day platform-native sample set, multi-source trend samples, and `viral_breakdown.status=ready`. Historical replay dates retain the previous compatibility behavior.

## Alternatives considered

### Full deep breakdown every day
Rejected: it duplicates work, delays production, and provides little incremental value when the same samples remain valid.

### Keep the breakdown only in markdown
Rejected: prose is not machine-verifiable and cannot reliably gate generation.

### Infer templates and motion from titles/manifests
Rejected: a plan or title is not evidence that a visual structure was actually present in a reference work.

### Replace existing same-lane intelligence
Rejected: `same_lane_intelligence.py` already owns native sample filtering and topic-pattern extraction. The new module adds evidence validation and cache semantics behind a small interface.

## Consequences

- `content-platform viral-breakdown` provides a stable CLI for operators and agents.
- `same-lane-intel` and `hot-works-collect` emit viral breakdown artifacts.
- Missing visual evidence blocks video-platform readiness instead of producing a misleading pass.
- Existing historical replay tests remain compatible; current/future production dates are stricter.
- Platform collectors remain responsible for collecting native samples; the breakdown module does not fabricate them.
