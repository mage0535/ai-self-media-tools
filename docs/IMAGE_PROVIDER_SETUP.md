# Image Provider Setup

This project supports generated and edited images through the standard script:

```bash
python3 scripts/image_gen.py --provider auto --prompt "..." --output /tmp/image.png
python3 scripts/image_gen.py --provider openai --prompt "..." --input-image /tmp/source.png --output /tmp/edit.png
python3 scripts/image_gen.py --provider gemini --prompt "..." --input-image /tmp/source.png --output /tmp/edit.png
python3 scripts/image_gen.py --provider stock --prompt "AI workflow workspace" --output /tmp/stock.png
```

The script emits JSON on stdout and sends diagnostics to stderr. It is safe for Pipeline subprocess parsing.

## Provider Order

`--provider auto` tries:

1. `openai`
2. `gemini`
3. `stock` (`pexels`, then `pixabay`)
4. `pollinations`

Free or low-cost fallbacks such as FLUX via fal/Replicate, Pollinations, Pexels, or Pixabay must be recorded as their real providers, not silently reported as OpenAI or Gemini output.

## Required Private Environment

Do not commit credentials. Put them in ignored runtime files such as:

```bash
{{CONTENT_PLATFORM_HOME}}/secrets/image.env
{{CONTENT_PLATFORM_HOME}}/secrets/provider.env
{{HERMES_HOME}}/.env
```

Supported keys:

```bash
OPENAI_API_KEY=...
OPENAI_IMAGE_MODEL=gpt-image-1
GOOGLE_API_KEY=...
GEMINI_API_KEY=...
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
```

The project reads `GEMINI_API_KEY` first and falls back to `GOOGLE_API_KEY`.

## Hermes OAuth Boundary

Hermes may have a ChatGPT/Codex OAuth image tool, but that is not the same as a service-readable `OPENAI_API_KEY`.

For unattended project runs:

- If using direct project scripts, configure a private API key in `secrets/image.env`.
- If using Hermes agent-native `image_generate`, record the actual provider returned by Hermes. Do not mark a Pollinations or other fallback image as GPT Image output.
- If Hermes proxy is used, it must expose a stable local OpenAI-compatible image endpoint before the project can depend on it.

## Provider Notes

- OpenAI GPT Image: best default for article covers, section illustrations, and image editing when a real `OPENAI_API_KEY` is available.
- Gemini Nano Banana: good for multi-turn image editing and text plus image inputs. The REST `interactions` endpoint is used, so `google-genai` is not required by this project script.
- Pexels/Pixabay: stock-photo search fallback for real-scene images. They support generation-by-search only, not image editing. Returned artifacts include `source_url`, provider, and license fields for attribution/review.
- Pollinations: free text-to-image fallback. It does not support project-grade image editing or reference locking, so it should be used for low-risk concept backgrounds or draft illustrations only.
- FLUX/BFL: useful for high-quality photorealistic and reference-style images. Official BFL API is pay-as-you-go; fal/Replicate may provide starter credits and can be added as lower-cost providers.
- Ideogram: useful for posters, covers, and text-heavy images. Official API is pay-per-image; use it only when typography matters enough to justify cost.

## Acceptance Criteria

A generated or edited image is usable only when all are true:

- the JSON result has `ok=true`;
- `provider`, `model`, `mode`, `path`, `bytes`, and `checksum` are recorded;
- the output file exists under an ignored runtime/artifact directory;
- `scripts/visual_gate.py` passes;
- article images include section-level mapping and purpose;
- no API key, cookie, token, local absolute secret path, or server address is written to tracked files.

## Automatic Image Package Size

When `media.image.min_count` is not configured, `MediaBridge` chooses a safe default:

- `wechat`, `zhihu`, `juejin`, `bilibili`, or body text over 1000 characters: 3 images, with cover plus section-level mapping.
- `xiaohongshu`: 6 images for carousel-style handoff.
- other short-form channels: 1 cover image.

Set `media.image.min_count` only when a workflow needs a fixed override.

## Video Workflow Integration

Original card/knowledge videos use the same image chain before rendering:

- `MediaBridge.generate("video")` first reuses existing job image artifacts when available.
- If no image artifacts exist and `media.image.enabled=true`, it generates scene images through `scripts/image_gen.py`.
- The selected images are copied into the video work directory as `backgrounds/bg_01.*`, `backgrounds/bg_02.*`, etc.
- `video_visual_assets.json` records every scene-to-image assignment and is passed to `scripts/video_toolchain_runner.py` through `VIDEO_VISUAL_ASSETS_PATH`.
- `localized_repost_video` is excluded from this step because it must preserve source-video evidence rather than fabricate visual backgrounds.
