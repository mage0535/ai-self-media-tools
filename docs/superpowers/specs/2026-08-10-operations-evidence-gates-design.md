# Operations Evidence Gates Design

## Goal

Prevent repeated cross-platform topics, incomplete video deliverables, and policy drift before content is handed to a publisher. The feature records evidence only and never changes a platform account or publishes content.

## Design

Each operating date has one JSON run manifest under `data/ops_runs/<date>/run_manifest.json`. It records topic decisions, their normalized direction, the evidence source, generated asset facts, validation results, and exceptions. A topic may not reuse an already selected direction during the configured lookback unless it explicitly declares a prior run, a distinct angle, and a recap reason.

The existing topic-independence checker remains the compatibility entry point. When a run manifest is present, it consumes the manifest direction register in addition to its existing source-matrix and textual-similarity checks.

The final-artifact verifier reads only the rendered video and its render manifest. It checks platform duration limits, expected vertical dimensions, placeholder card titles, subtitle dimensions, and evidence of actual frame movement. It returns structured JSON and can be called by the video runner after a local render; it does not upload or alter the artifact.

The strategy/skill audit compares only declared policy facts: WeChat recovery frequency, new-picture dual-track rule, vertical subtitle dimensions, short-video duration, and layered-motion requirement. A mismatch fails the audit rather than choosing an undocumented winner.

## Error Handling

All new gates fail closed only at their explicit command or integration point. Missing manifests, missing media probes, or incomplete evidence produce named failed dimensions. Existing direct publishing behavior is unchanged until callers opt into the new `ops-run` commands.

## Verification

Regression tests cover direction-level blocking with different wording, valid documented follow-ups, static and invalid video evidence, placeholder titles, and policy/skill conflicts. The existing topic and video suites, rulebook validation, and project audit remain required before handoff.
