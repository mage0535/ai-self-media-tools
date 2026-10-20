# 抖音 AI 成片质量事故复盘与门禁修复

日期：2026-09-20
任务：`douyin-ai-finance-20260920-r1`
真实产物目录：`/root/.ai-self-media-tools/data/runs/douyin_ai/20260920_finance_reconciliation_r1/`

## 结论

本次失败不是单个 CSS 参数问题，而是生产路径绕过了标准视频工作流，随后由自写 metadata 把未验证结果伪装成已完成。原产物应判定为 **blocked / 不可发布**。

## 实物证据

- `cover.png`：背景不是主题相关的可见场景，而是深色网格/卡片层；标题残影、中心信息块和红色强调框互相压叠，信息层级失控，不符合电影海报或品牌广告构图。
- `contact_sheet.jpg`：8 个关键帧均为深色网格 + 信息卡模板；没有承担叙事的可见财务办公/单据/付款风控背景，局部 motion 只是整张卡片 zoom/pan。
- `final.mp4`：实际来源为 `build_video.py`，不是 canonical `video_toolchain_runner.py`；视频与 cover 的 SHA 仅证明文件身份，不证明视觉质量。

## 根因

1. `plan.json` 使用 `selected_pipeline=explainer_video`，没有进入 canonical `video_toolchain_runner.py` / Cinema / Shotcraft 路径。
2. `generate_scene_assets.py` 生成的是深色网格信息卡，不是真实主题背景；`build_video.py` 只是对静态卡片做 zoompan。
3. `generate_metadata.py` 直接写入 `segment_motion_evidence.json`，用 `move_id/profile` 自报“已执行”，没有真实 renderer 调用证据。
4. 旧 `video_toolchain_runner.py` 用 `actual_tools` 静态集合把计划工具直接标记为 `ok`，形成证据伪造路径。
5. runner 在封面生成之后才设定成功状态，且 `except Exception: pass` 吞掉封面失败；已有封面还能绕过独立封面 workflow。
6. `final_delivery_gate.py` 旧逻辑只核验路径、hash、状态和 evidence 文件存在，不核验 canonical renderer、Cinema/Shotcraft runtime、最终视觉 gate 或可见背景。
7. API acceptance 只检查 `scene_manifest.json`、`tts_config.json` 和文件存在，缺少 canonical runner manifest 时仍可能接受旁路包。
8. `cover_quality` 只验证布局字段/尺寸/部分视觉指标，不要求背景 provenance，也不能区分“有像素复杂度”与“有可见、语义匹配的背景”。

## 已实施修复

### 开发目录 `/root/.ai-self-media-tools`

- `scripts/video_toolchain_runner.py`
  - 计划工具没有显式 runtime evidence 时标记 `not_invoked`，不再硬编码 `ok`。
  - Cinema、Shotcraft、cards、visual gate 缺少 runtime evidence 时 fail-closed。
  - 封面必须有背景资产；已有封面也必须重新经过独立 cover gate。
  - 封面异常写入 manifest 并返回失败，不再静默吞错。
  - 生成的 cover evidence 绑定 `cover_sha256`、`background_provenance`、`safe_zone_verified` 和独立 renderer。
- `content_platform/cover_quality.py`
  - 缺失/不存在/指向封面自身的背景 provenance 直接失败。
  - `review_required` 不再被 release 层当作成功。
- `content_platform/video_release_runtime.py`
  - cover status 非 `pass` 时直接失败。
- `scripts/final_delivery_gate.py`
  - 新增 `validate_video_runtime()`：要求 canonical `film_renderer.py` / `kuaishou_render.py`、Cinema/Shotcraft runtime invocation、最终 cinema/artifact/duration/motion evidence、segment renderer evidence。
- `content_platform/workflow_acceptance.py`
  - 视频 acceptance 必须通过 canonical runtime gate。
- 新增/更新回归：
  - `tests/test_final_delivery_gate.py`
  - `tests/test_cover_quality.py`
  - `tests/test_video_release_runtime.py`
  - `tests/test_workflow_acceptance.py`
  - `tests/test_video_toolchain_runner.py`

### production release

实际运行目标 `/root/.ai-self-media-tools-current` 指向的 release 目录已同步：

- `scripts/video_toolchain_runner.py`
- `scripts/final_delivery_gate.py`
- `content_platform/cover_quality.py`
- `content_platform/workflow_acceptance.py`

## 实证验证

### 原事故包

对原目录执行新 final gate：

```text
passed: false
video_runtime:video_toolchain_manifest_missing
```

因此原包现在无法再因为 `handoff_ready`、hash 或自写 publish state 被判定为可交付。

### 回归

```text
cover quality: 11 passed
video release runtime: 19 passed
workflow acceptance: 5 passed
final delivery gate: 2 passed
```

production 关键文件 `py_compile` 通过。

## 后续硬规则

- 任何抖音 AI 视频必须通过 canonical runner；`build_video.py`、`generate_metadata.py` 不能作为正式交付链。
- `manifest`、`cards.json`、`segment_motion_evidence.json` 只能作为证据载体，不能替代最终 MP4 抽帧和真实 renderer evidence。
- 只有存在可见、主题匹配、独立绑定的背景 provenance，封面才允许进入 release gate。
- 视觉门禁必须至少覆盖：背景可见性、语义匹配、文字/主体碰撞、安全区、场景复杂度、局部 motion、最终 MP4 抽帧；任何一项缺证据均阻断。
- 本修复阻断了“旁路伪成功”，但不会把任意 AI/stock 背景自动判定为语义合格；正式发布前仍需要对最终封面和关键帧进行目视复核。

## 异步专项审计后的第二轮加固

专项审计进一步发现 canonical runner 内部仍存在降级和真实文件证据缺口，已继续修复：

- `douyin_ai` 的 Cinema 自动路由失败不再静默 fallback；只有显式允许 fallback 的任务才可降级，并且会记录 `degraded` 与 `fallback_reason`。
- production runner 对 `douyin_ai` 强制 `FILM_QUALITY_PROFILE=high`、`FILM_MOTION_MODE=cinematic`、`FILM_ALLOW_DEGRADED=0`，禁止继承 preview/degraded/safe 环境。
- `pre_render_gate` 现在解码每个背景文件并检查最小尺寸，损坏文件不能仅凭文件名和数量通过。
- unified D8 对缺失 backgrounds、缺失 motion evidence、缺失 final.mp4 一律失败。
- `validate_video_runtime` 现在要求真实 `final.mp4` 存在并通过 ffprobe，manifest output 必须指向同一文件，cover 文件也必须存在。
- `verify_artifact` 不再接受外部 probe 或 `render_manifest.motion_score` 覆盖真实媒体事实，始终对实际 MP4 执行 ffprobe 和 motion 测量。

第二轮定向回归：

```text
真实媒体 / 最终 gate / adapter：15 passed
开发目录与 production release 关键文件 py_compile：PASS
```

当前仍明确保留的边界：最终语义、构图和品牌级视觉仍必须对最终 PNG/MP4 抽帧目视复核；技术 gate 不能自动证明任意背景与主题匹配。
