# 2026-09-19 douyin_pet 工作流审计与修复归档

## 最终决议

- 选题《猫咪不同睡姿代表什么？什么时候不要打扰它》作废。
- attempt-31 至 attempt-35 永久不可作为正式交付物。
- 未发布、未上传；视频附件未形成可靠送达闭环。
- 作废证据：`data/runs/douyin_pet/20260918_pet_quality_probe_r1/TOPIC_VOID.json`。

## 已确认根因

1. 抖音宠物扩大后的 4 条内容线存在于配置，但旧 run 没有强制绑定 `account_key + lane + content_line`。
2. `hot_viral_intelligence` 正确返回 blocked，但 generation contract 的 degraded bypass 可将无 native、无 topic signal、strategy unavailable 改写为 degraded candidate。
3. preflight 曾将 `degraded_source=true` 当成继续渲染许可，而不是阻断证据。
4. `semantic_content_visual_gate` 仅存在于配置，没有接入 runner。
5. beat、scene、asset、TTS、subtitle 多处依赖列表位置，素材缺失或过滤后会整体提前/延后一拍。
6. 研究门禁未前置，导致单次正式渲染约 839 秒后才发现语义错误，进而重复返工。
7. attempt identity、旧 output/evidence 隔离、后处理旁路、Telegram 附件送达状态机仍需后续 P0/P1 修复。

## 已实施代码修复

- 修改 `content_platform/video_preflight.py`
  - native research 缺失默认 fail-closed。
  - 只有明确 `allow_degraded_render=true` 的降级草稿才能继续。
- 修改 `content_platform/video_generation_contract.py`
  - degraded candidate 额外要求 `topic_signal_count > 0`。
  - `strategy_context.mode` 不得为 `unavailable`。
  - 必须显式允许 degraded render。
- 新增 `content_platform/account_lane_gate.py`
  - `douyin_pet` 必须绑定 `pet_healing` 和 4 条合法内容线之一。
- 新增 `content_platform/beat_asset_semantic_gate.py`
  - beat 必须显式对应 required semantic tag 和素材 semantic tags。
- 修改 `scripts/video_toolchain_runner.py`
  - 正式运行前执行 account/lane/content-line gate。
  - 正式运行前执行 beat/asset semantic gate。
  - visual assignments 按 `beat_id` 排序，旧式缺 beat_id 映射被阻断。
- 测试更新：`tests/test_video_preflight.py`、`tests/test_video_generation_contract.py`。

## 验证结果

- 相关回归：`59 passed`。
- Python 编译通过。
- 旧 attempt-32 语义映射被新 gate 阻断。
- 旧缺少 `account_key/content_line` 的计划在渲染前返回 `account_key_required`。
- `graphify update .` 完成。

## 下一会话 P0

1. 建立唯一 `RunIdentity(job_id, run_id, revision, attempt_id, output_namespace)`，所有 manifest/evidence 共用。
2. 每个 attempt 使用不可复用目录；renderer 非零且旧 final 存在时必须失败。
3. 去除生产链中的位置 join：cards、renderer、scene manifest、TTS、subtitle 全部改为 `beat_id` 显式双射。
4. 禁止后处理修改已验收 OUTPUT；任何字节变化必须新 revision/attempt 并重新 ReleaseGate。
5. 最终 MP4 加真实像素/OCR/字幕/主体/语义 evidence，绑定 candidate SHA。
6. Telegram 附件交付增加 send accepted、message ID、remote file ID、回读及幂等状态机。
7. 新选题前必须完成：扩大赛道内容线决策、账号自身数据、抖音原生同赛道热度/爆款、多平台趋势交叉、七日去重；不满足则 BLOCKED。
