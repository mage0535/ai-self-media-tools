# Overnight Batch Acceptance

The overnight job is accepted from runtime evidence, not from a Hermes notification.

## Required result contract

`data/overnight/YYYY-MM-DD/result.json` must contain one of:

- `completed`
- `partial`
- `blocked`
- `no_run`

Unknown, empty, or missing result files fail acceptance. A `blocked` or `partial`
result is not treated as a successful run; it is retained as truthful operational
evidence and requires the stated reason to be reviewed.

## Artifact evidence

Every terminal task in `state.json` is checked. A staged task must have a real
artifact. A video task in `staged` or `handoff_ready` must have all three handoff
artifacts: video, cover, and publish information. The artifact directory must also
contain `scene_manifest.json` and `tts_config.json`, so the rendered result is
traceable to its scene plan and actual TTS inputs.

The gate writes `acceptance_report.json` and the batch exits non-zero when the
evidence is incomplete. Publishing state is never inferred from the notification.

## Scheduling

The timer accepts a bounded catch-up start window controlled by
`OVERNIGHT_ADMISSION_WINDOW_MINUTES` (default `60`). This covers a short reboot or
resource delay without allowing an unbounded daytime start. A skipped run is
recorded as `no_run`.

## Verification

```bash
python3 -m pytest tests/test_overnight_acceptance.py tests/test_overnight_entrypoint.py -q
python3 scripts/overnight_acceptance.py \
  --result data/overnight/YYYY-MM-DD/result.json \
  --state data/overnight/YYYY-MM-DD/state.json \
  --output data/overnight/YYYY-MM-DD/acceptance_report.json
```
