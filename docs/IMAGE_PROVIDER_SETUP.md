# Image Provider Setup

This project supports generated and edited images through the standard script:

```bash
python3 scripts/image_gen.py --provider auto --prompt "..." --output /tmp/image.png
python3 scripts/image_gen.py --provider openai --prompt "..." --input-image /tmp/source.png --output /tmp/edit.png
python3 scripts/image_gen.py --provider gemini --prompt "..." --input-image /tmp/source.png --output /tmp/edit.png
python3 scripts/image_gen.py --provider go_gemini --model gemini-3.1-flash-image --prompt "..." --output /tmp/go-image.jpg
python3 scripts/image_gen.py --provider go_gemini --model gemini-3.1-flash-image --prompt "..." --input-image /tmp/source.png --output /tmp/go-edit.jpg
python3 scripts/image_gen.py --provider stock --prompt "AI workflow workspace" --output /tmp/stock.png
python3 scripts/smoke_image_provider.py --providers pollinations,cloudflare,auto
```

The script emits JSON on stdout and sends diagnostics to stderr. It is safe for Pipeline subprocess parsing.

## Provider Order

`--provider auto` uses task-specific routing:

- 普通文生图（高额度/低成本组合）：`go_gemini` → `sense_nova` → `cloudflare`（FLUX Schnell）→ `pollinations`（FLUX）→ `stock`
- 普通文改图（支持参考图）：`go_gemini` → `sense_nova`
- `--quality-first` 文生图：`openai`（GPT）→ `go_gemini` → `sense_nova` → `cloudflare` → `pollinations`
- `--quality-first` 文改图：`openai`（GPT）→ `go_gemini` → `sense_nova` → `gemini`

模型选择原则：go Gemini 用高额度承担日常主流量；SenseNova 保留较高质量且支持编辑的 fallback；Cloudflare FLUX Schnell 承担高并发快速生图；Pollinations FLUX 作为最后的免费概念图 fallback；GPT 只在质量优先或显式指定时启用。图库源 `stock` 不是生成模型，仅作为语义匹配的真实照片 fallback。

`go_gemini` 调用导入的 Hermes `go` 通道，模型默认为 `gemini-3.1-flash-image`，使用 `chat/completions` 的 `message.images[].image_url.url` 图片输出协议。输入图会在发送前限制到默认最长边 1024px，避免大图触发上游超时；可用 `GO_GEMINI_IMAGE_INPUT_MAX_DIM` 调整。

Paid providers are not used by default. Set `IMAGE_PROVIDER_ALLOW_PAID=1` only for an audited run that explicitly permits paid image generation. When enabled, the paid providers are appended after the free chain:

4. `openai`
5. `gemini`

Override the chain with `IMAGE_PROVIDER_CHAIN`, for example:

```bash
IMAGE_PROVIDER_CHAIN=pollinations,cloudflare,stock
```

Successful generated images are cached under `{{CONTENT_PLATFORM_HOME}}/data/cache/image_provider` by prompt, provider, model, size, and input image hash. Set `IMAGE_PROVIDER_DISABLE_CACHE=1` only when a fresh image is required.

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
GO_GEMINI_API_KEY=...
GO_GEMINI_API_BASE_URL=<Hermes go channel base_url>
GO_GEMINI_API_KEY_ENV=HERMES_CUSTOM_107_148_244_244_8317_API_KEY
GO_GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
GO_GEMINI_IMAGE_GENERATE_TIMEOUT=120
GO_GEMINI_IMAGE_EDIT_TIMEOUT=240
GO_GEMINI_IMAGE_INPUT_MAX_DIM=1024
GO_GEMINI_USE_SYSTEM_PROXY=0
PEXELS_API_KEY=...
PIXABAY_API_KEY=...
PIXAZO_API_KEY=...
SN_API_KEY=...
SN_BASE_URL=https://token.sensenova.cn/v1
CF_WORKER_URL=...
CF_WORKER_KEY=...
CLOUDFLARE_IMAGE_WORKER_URL=...
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_IMAGE_MODEL=@cf/black-forest-labs/flux-1-schnell
```

The project reads `GEMINI_API_KEY` first and falls back to `GOOGLE_API_KEY`.

Pixabay credentials are loaded from `PIXABAY_API_KEY` in the environment or the ignored runtime file `{{CONTENT_PLATFORM_HOME}}/secrets/pixabay.env`. The same key serves the image endpoint (`/api/`) and video endpoint (`/api/videos/`). Do not put it in tracked config or source files.

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
- Pixabay stock video: `python3 scripts/pixabay_video_search.py "workflow automation" --count 1 --output-dir /tmp/pixabay-video`. The adapter uses `https://pixabay.com/api/videos/`, caches search JSON for 24 hours, downloads the selected MP4 locally, and records `source_url`, `download_url`, `duration`, `dimensions`, `license`, and `sha256`. Video results remain candidates until the downstream semantic gate passes.
- Pollinations: free text-to-image fallback. It does not support project-grade image editing or reference locking, so it should be used for low-risk concept backgrounds or draft illustrations only. The project uses retries plus local cache because the public service can be intermittently slow or unavailable.
- Cloudflare Workers AI: stable free-tier/low-cost image provider when a Worker URL or account API token is configured. It is not considered configured unless one of these is present: `CF_WORKER_URL`, `CLOUDFLARE_IMAGE_WORKER_URL`, or `CLOUDFLARE_ACCOUNT_ID` plus `CLOUDFLARE_API_TOKEN`.
- FLUX/BFL: useful for high-quality photorealistic and reference-style images. Official BFL API is pay-as-you-go; fal/Replicate may provide starter credits and can be added as lower-cost providers.
- Ideogram: useful for posters, covers, and text-heavy images. Official API is pay-per-image; use it only when typography matters enough to justify cost.

## Auto 修图（按需）

`--provider auto` 在拿到首张图（多为 stock 实景）后，会自动判断是否需要 AI 修图：
- 判定信号：prompt 含 `修图/去水印/换背景/去除/美化/风格化/无文字/no text/clean background` 等，或 stock 图与 AI 插画风格严重不匹配时触发
- 触发后自动以该图为底，按 `sense_nova` → `go_gemini` → `gemini` → `openai` 顺序尝试编辑，产物标记 `edited:true` + `edit_provider/edit_prompt`
- 默认仅在显式修图信号时触发，不额外消耗 paid 额度；可设 `IMAGE_PROVIDER_AUTO_EDIT=1` 强制每次都尝试，或 `IMAGE_PROVIDER_AUTO_EDIT=0` 彻底关闭
- 仅当编辑 provider key 已配置时才会执行，否则跳过保留原图

## Acceptance Criteria

A generated or edited image is usable only when all are true:

- the JSON result has `ok=true`;
- `provider`, `model`, `mode`, `path`, `bytes`, and `checksum` are recorded;
- the output file exists under an ignored runtime/artifact directory;
- `scripts/visual_gate.py` passes;
- article images include section-level mapping and purpose;
- no API key, cookie, token, local absolute secret path, or server address is written to tracked files.

## Daily Provider Smoke Test

Run this before automated content generation:

```bash
python3 scripts/smoke_image_provider.py --providers pollinations,cloudflare,auto --output-dir /tmp/image-provider-smoke
```

Expected behavior:

- `pollinations` should usually pass or hit cache.
- `cloudflare` may report `missing_config`; that is a configuration issue, not a generation failure.
- `auto` should pass if at least one free provider or stock provider is available.
- The script must never print token values.

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

For workflows that explicitly request stock B-roll, the source router exposes `plan_source_route("stock_video")` and resolves it to `pixabay_video` → `scripts/pixabay_video_search.py`. The downloaded video is local and its provenance is retained; it must not be treated as a user-owned source or silently hotlinked.
