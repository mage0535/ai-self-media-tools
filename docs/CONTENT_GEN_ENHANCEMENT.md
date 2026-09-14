# Content Generation Enhancement Layer

## Purpose

This repository has a built-in content pipeline.
When a Hermes environment is available, it can optionally call extra skill-based tooling for research, writing, review, and media planning.

## Base Mode

Use the repository's own workflow:

```bash
python -m content_platform trends --limit 5
python -m content_platform analyze-topic --topic "AI Agent"
```

## Enhanced Mode

If the Hermes companion script exists under the local Hermes home, it can be invoked directly:

```bash
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --topic "AI Agent" --type article
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --topic "大模型落地" --type video-script
python "${HERMES_HOME:-$HOME/.hermes}/scripts/content_gen_fusion.py" --list-types
```

## Optional Capabilities

| Capability | Typical Source | Gap It Fills |
|------------|----------------|--------------|
| real-time trend collection | AutoCLI | live hot-topic collection |
| cover and image planning | Hermes image skills | richer visual planning |
| video script drafting | Hermes video skills | platform-native video outlines |
| proofreading and review | Hermes review skills | stronger editorial checks |
| infographic generation | Hermes design skills | structured visual assets |

## Preconditions

- Hermes runtime is installed and reachable.
- Optional Hermes skills exist under `${HERMES_HOME:-~/.hermes}/skills/`.
- AutoCLI browser-dependent features require the local daemon when used.

## Production Integration Status / 生产集成状态

The 2026-09-13 mutable-runtime optimization was reviewed as design input. Its
standalone Prompt Registry, Prompt Compiler, SearchSpec, source router, and
cache prototype are not copied into this branch because that would create a
second source of truth and its profile set does not cover all twelve targets or
horizontal YouTube.

The accepted production path is:

```text
platform evidence and strategy
  -> content_blueprint
  -> four-axis content_profile
  -> deterministic capability plan
  -> compiled skill rules and content assets
  -> bounded_model_input
  -> generation
  -> parent/child provider telemetry
  -> artifact and effect gates
  -> policy-safe draft, handoff, or publication postcheck
```

### Integrated capabilities

- Platform- and content-form-specific rules are filtered before model input.
- Prompt/rule consumption has stable hashes and named affected outputs.
- Image intent routing distinguishes cover, section, knowledge card, video
  scene, and image edit for all twelve target platforms.
- Pexels and Pixabay are child capabilities of the executable media asset
  pipeline for article, carousel, short-video, and long-video work. Provider,
  source URL, license, semantic evidence, dimensions, and SHA-256 remain part
  of the artifact contract.
- Generated-image routes remain content-driven. Agnes is health-isolated;
  paid providers require explicit opt-in at the provider boundary.
- Video scene assets reject unrequested named products even when stock source
  metadata is otherwise valid. Cover selection separately checks platform UI,
  embedded text, subject relevance, and named-product conflict.
- Image provider cache keys bind provider, model, size, prompt, intent, and
  input-image content. A cache hit is not quality evidence; the resulting file
  still passes the normal semantic and artifact gates.
- Failure receipts are fail-closed. A generated MP4 without an accepted cover,
  ASR, capability evidence, and handoff/delivery contract is still a failed
  work.

### Deliberately pending

- Wikimedia Commons needs a project-owned adapter with per-file license and
  source evidence before it may enter automatic selection.
- Playwright CLI/MCP collection needs one allowlisted source adapter and a
  per-task input/output receipt. Browser availability alone is not execution.
- Apify needs an opt-in actor adapter, cost boundary, output schema, source
  rights evidence, and fallback receipt.
- Prompt-, asset-, and render-level incremental cache sharing is not complete.
  Render reuse must bind renderer version, scene manifest, asset hashes,
  FFmpeg parameters, final artifact hash, and effect evidence.
- Twelve-platform real Canaries and publication metric windows remain required
  before enabling unattended production timers.

Only the current capability registry, generation context compiler, image
routing, execution DAG, and quality gates are authoritative. Files in a dirty
server checkout are evidence or design input, not deployable production code.

### 2026-09-14 image-workflow intake

The mutable Hermes checkout's image changes were reviewed against the current
pipeline, not copied wholesale. The integrated corrections are:

- Cat/dog subjects explicitly requested in an AI-knowledge visual take
  precedence over a generic `AI workspace` stock query. This does not force
  pets into unrelated content or override an explicit no-pet instruction.
- Automatic routes and MediaBridge quality-recovery routes both exclude
  Pixazo, OpenAI and Gemini unless `IMAGE_PROVIDER_ALLOW_PAID=1`. An
  explicitly selected provider remains a separate operator decision.
- Cache identity binds prompt, provider, model, size, intent, renderer version
  and input-image bytes, not the input file path. Cache metadata contains an
  output hash; altered or legacy unverified cache entries are ignored.
- An explicit retouch request cannot succeed by returning the untouched stock
  image after every edit provider fails. The original is retained as evidence;
  automatic routing may continue to a different generator, or fail closed.

The following mutable-checkout behaviors were rejected: treating `no text`
alone as an edit request, swallowing edit exceptions with `except: pass`,
selecting a paid source via a quality flag without paid authorization, and
blanket rejection of cat/dog roles in non-pet AI knowledge lanes. Cat/dog
roles are optional: the content blueprint selects them only when the topic or
explicit strategy makes them useful, and then validates their narrative
function and asset relevance.
The new document's 967-test count belongs to that dirty checkout; it is not
this branch's test or deployment evidence.
