# Viral Breakdown Workflow

This workflow turns same-platform, same-lane breakout-work analysis into machine-readable evidence that can be reused by topic selection and content generation.

## What it analyzes

Each reference work should include the complete media reference dimensions:

- `content_form`: article, thread, vertical video, horizontal video, carousel, etc.
- `copy_or_script`: observed copy, transcript, or script summary with evidence path.
- `writing_style`: tone, sentence rhythm, vocabulary, emotional register, and platform voice.
- `content_structure`: hook, promise, proof, steps, boundary, CTA, and pacing.
- `topic_direction`: the concrete lane and angle, not just a broad keyword.
- `asset_analysis`: screenshots, diagrams, real footage, cover, background, and illustration placement.
- `theme_template`: the observed layout/theme and why it fits the platform/lane.
- `voiceover`: language, tone, pace, speaker style, or explicit `not_applicable` for static content.
- `motion_combination`: text motion, subject motion, emphasis effects, or explicit `not_applicable`.
- `transition_combination`: transitions and timing, or explicit `not_applicable` for static content.
A video reference additionally needs:

- a native platform URL;
- real visual evidence (screenshot, frame, or verified render artifact);
- `motion_combination.status=verified`.

The workflow never infers a template or motion combination from a title or a planned manifest.

## Cadence

- **Daily light scan**: collect fresh native samples and candidate topics.
- **Weekly deep breakdown**: deeply analyze one or two representative works per platform.
- **Monthly review**: remove fatigued templates and update platform style/motion combinations.
- **Immediate trigger**: deep-break down a work when it reaches an account-level outlier, a new format appears, a platform rule changes, or performance drops materially.

Reports are cached for 7 days by default. Expired reports must be refreshed; they cannot be silently treated as current evidence.

## CLI

Run from the repository root:

```bash
# Validate a JSON sample file for one or more platforms.
python3 -m content_platform.cli viral-breakdown \
  --platform zhihu \
  --platform juejin \
  --sample-file /private/native_samples.json \
  --output data/intel/viral_breakdown_latest.json
```

The sample file can be a list, `{\"samples\": [...]}`, or a platform keyed object. Each sample must contain the six dimensions above. The command always writes a JSON report, including `status=ready` or `status=blocked` and explicit failure reasons.

Existing collection workflows also emit the report:

```bash
python3 -m content_platform.cli same-lane-intel \
  --platform zhihu \
  --sample-file /private/native_samples.json

python3 -m content_platform.cli hot-works-collect \
  --platform kuaishou \
  --state-file kuaishou=/private/state.json
```

`same-lane-intel` includes `viral_breakdown` per platform. `hot-works-collect` writes `viral_breakdown.json` beside its collection output.

## Topic admission

For the current day and future dates, the topic gate requires all of the following:

- same-day `collected_at`;
- at least one native platform sample;
- at least three multi-source trend samples;
- at least five attempted sources and three successful sources;
- `platform_internal_verified=true`;
- `viral_breakdown.status=ready`;
- selected topic and cross-platform topic independence.

Run the gate explicitly when working outside the default repository root:

```bash
python3 scripts/check_platform_topic_independence.py \
  20260912 \
  --root /absolute/path/to/ai-self-media-tools \
  --platforms wechat,zhihu,juejin
```

A blocked platform must remain `blocked` or `degraded`; do not use a cross-platform trend as a substitute for native breakout evidence.

## Development contract

- Add or update tests before changing evidence semantics.
- Keep native collection in the platform adapter; keep validation and TTL logic in `content_platform/viral_breakdown.py`.
- Store source URLs and evidence paths, never cookies or API keys.
- Run `pytest -q tests/test_viral_breakdown.py tests/test_cli.py` before submitting changes.
- Run the full project test suite and `graphify update .` after changing code.
