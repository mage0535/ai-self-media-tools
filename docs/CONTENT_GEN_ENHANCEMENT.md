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

## Production Optimization Status / 生产优化落地状态

> Updated: 2026-09-13
>
> This section records the production optimization work that is actually present in the checkout. It distinguishes executable integrations from registry-only plans.
>
> 本节记录当前工作树中已经真实落地的生产优化，明确区分“可执行集成”和“仅注册/规划”，避免把配置声明误认为运行态完成。

### 1. Runtime architecture / 运行时架构

```text
Platform Profile
    ↓
Prompt Registry
    ↓
Deterministic Prompt Compiler
    ↓
SearchSpec + Source Router
    ↓
Provider / Asset Cache
    ↓
Generation
    ↓
Preflight + Quality Gates
    ↓
Artifact Fingerprint + Manifest
    ↓
Regression Verification
```

主要实现文件：

- `config/prompt_registry.json` — 平台 Profile、语言、画幅、时长、硬约束和禁止项。
- `content_platform/prompt_registry.py` — 只读、版本化 Profile 加载器。
- `content_platform/prompt_compiler.py` — 确定性生成主题、文案、生图、视频 Prompt、关键词和质量契约。
- `content_platform/search_contract.py` — semantic/tags/platform 三类查询、候选硬门禁和可解释评分。
- `content_platform/source_registry.py` — 素材、浏览器、视频、AI 生图来源注册表。
- `content_platform/media_source_router.py` — 免费优先、外部服务和付费 Provider 的安全路由计划。
- `content_platform/asset_cache.py` — typed content-addressed cache key。
- `scripts/image_gen.py` — 图片生成入口的 Prompt Bundle preflight。
- `scripts/script_enhancer.py` — 旧 screencast 视频脚本入口的 Prompt Bundle preflight。
- `content_platform/generator.py` — 正文主生成器的 Prompt Bundle trace。
- `scripts/video_toolchain_runner.py` — 视频主 Runner 的 Prompt Bundle manifest evidence。

### 2. Prompt and content compilation / Prompt 与内容编译

`compile_prompt_bundle()` 的输入包括：

- platform / content type
- topic / audience / goal
- evidence references
- visual style
- duration
- user constraints

输出包括：

- topic/copy/visual/video prompt sections
- platform/topic/visual/evidence keyword groups
- registry version
- language/aspect ratio/duration contract
- forbidden constraints
- deterministic fingerprint

默认行为是确定性的：相同输入、相同 Registry、相同编译器版本产生相同 Bundle fingerprint。

**重要边界：**

- Bundle 是生成要求和追踪证据，不等于最终成品已经满足全部质量要求。
- 最终质量仍由正文、图片、视频、字幕、音频和平台门禁分别验证。
- 未知平台不会自动伪造平台规则；入口应显式映射别名或失败关闭。

### 3. Media source registry and route / 素材来源与路由

| Source / 来源 | Registry | Adapter/入口 | Unified route | Runtime status |
|---|---:|---:|---:|---|
| Pexels | ✅ | ✅ `image_provider.py`, `pexels_image_search.py` | ✅ | 已有 mock/本地回归；真实网络需凭据 |
| Pixabay | ✅ | ✅ `image_provider.py`、旧视频脚本 | ✅ | Provider 路径存在，统一许可证证据仍需补强 |
| Wikimedia Commons | ✅ | ❌ | ✅ plan only | 未标记为已执行 |
| User URL | ✅ | 部分 | ✅ | 主要由 URL→yt-dlp 路径消费 |
| yt-dlp | ✅ | ✅ 旧视频链路 | ✅ plan/旧链路 | 需逐任务保存 rights/source evidence |
| Platform native | ✅ | 平台采集器分散存在 | ✅ plan | 不等于统一 Media Source Adapter |
| Playwright CLI | ✅ | 平台浏览器脚本分散存在 | ✅ plan | 适合高吞吐采集，需逐任务 receipt |
| Playwright MCP | ✅ | ❌统一 Source Adapter | ✅ plan only | 不标记为已执行 |
| Apify MCP | ✅ | ❌统一 Actor Adapter | ✅ external fallback plan | 必须显式 `allow_external` |
| Cloudflare Workers AI | ✅ | ✅ `image_provider.py` | ✅ | Provider=`cloudflare` |
| GPT Image | ✅ | ✅ `image_provider.py` | ✅ paid opt-in | Source=`gpt_image`, Provider=`openai` |
| SenseNova | ✅ | ✅ `image_provider.py` | ✅ | Provider=`sense_nova` |
| Pollinations | ✅ | ✅ `image_provider.py` | ✅ | 免费优先 fallback |
| Pixazo | ✅ | ✅ `image_provider.py` | ✅ paid opt-in | 非默认自动源 |

默认图片路由不进入 GPT Image/Pixazo；只有显式 `allow_paid=True` 或 `IMAGE_PROVIDER_ALLOW_PAID=1` 才允许付费 Provider。Apify 单独受 `allow_external=True` 控制。

### 4. Cache and idempotency / 缓存与幂等

图片 Provider 的缓存 Key 由以下字段决定：

- prompt
- provider
- model
- size
- input image hash
- renderer version

因此更换 Provider、模型、尺寸、输入素材或 Renderer 版本会自动失效；缓存命中会写入 `cache_hit`。

`asset_cache.py` 提供三类 Key：

```text
prompt / asset / render
```

生产代码当前已经消费 `asset` Key；正文和视频的 render 级缓存仍需继续扩展，不能将其误报成已完成的全链路增量渲染缓存。

### 5. Gate and bypass policy / 门禁与绕过策略

已验证的门禁：

- Prompt Bundle validation
- 图片 preflight prompt gate
- 图片 visual gate
- 视频 script structure gate
- video visual contract gate
- pre-render gate
- final artifact gate
- scene duration gate
- motion evidence gate
- project audit
- final delivery gate

门禁跳过只允许显式本地应急模式，并会在结果 JSON 写入：

```json
{
  "skipped_gates": ["prompt_preflight", "visual_gate"],
  "gate_skip_mode": "audited_local_emergency"
}
```

生产发布不能把“上传器返回成功”“handoff_ready”或“文件写入 outbox”当成已发布；必须有平台侧回查或明确人工确认。

### 6. Configuration and operational safety / 配置与运维安全

当前配置已完成以下修复：

- Kuaishou postcheck 指向当前有效脚本路径。
- WeChat adapter 指向当前有效脚本路径。
- TikTok/YouTube 与 manual-handoff 状态一致，`can_publish_now=false`。
- 缺失的图像语义分析器被标记为 optional/unavailable，不再声明 required。
- 历史 `.bak` 文件移出项目工作树，但保留在 Hermes archive 中。
- 运行时代码默认路径使用 `CONTENT_PLATFORM_HOME`、`Path.home()` 或显式环境变量。
- Toutiao 直发默认阻断；找不到草稿保存控件时返回 unknown/failed，不自报成功。

### 7. Verification evidence / 验收证据

最近一次完整验收：

```text
pytest -q --tb=short
967 passed, 33 subtests passed

python3 -m compileall -q content_platform scripts
PASS

python3 -m content_platform.cli project-audit
{"ok": true, "scanned_files": 707, "issues": []}

git diff --check
PASS
```

相关专项测试覆盖：

- Prompt Compiler / Registry / fingerprint
- SearchSpec / candidate score
- Media Source Router
- Pexels evidence mode
- Image generation CLI
- Video script enhancer
- Video toolchain runner
- Generator evidence
- Viral breakdown and topic gate
- Project audit
- Final delivery gate

### 8. Installation and test environment / 安装与测试环境

测试依赖已写入 `pyproject.toml`：

```bash
pip install -e '.[test]'
pytest -q --tb=short
```

不要只运行 `python -m compileall` 就宣布系统完成。编译只能证明语法可解析，不能证明 Provider、浏览器、外部 MCP、账号状态或平台回查可用。

### 9. What is deliberately not claimed / 明确未宣称完成的能力

以下项目目前只能标记为“注册/计划/外围能力”，不能写成全链路已完成：

- Wikimedia Commons 统一素材适配器。
- Playwright CLI/MCP 统一素材 Source Adapter。
- Apify Actor/MCP 执行器和成本/许可证闭环。
- 所有平台的真实外部发布回查。
- 正文、图片、视频三类都完全共享同一套 render-level 增量缓存。
- 所有历史旁路脚本都已经接入统一 Pipeline。

新开发人员新增来源时必须同时提交：

1. Registry profile；
2. 真实 Adapter；
3. SourceEvidence/许可证字段；
4. 候选硬门禁；
5. 运行态 smoke test；
6. 失败与 fallback receipt；
7. 文档和回归测试。

只添加一个 Registry 条目或 Router 计划，不算来源适配完成。
