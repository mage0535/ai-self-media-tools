# 工业质检视频 attempt24 复盘与快速生产 SOP

## 结论

本次最终成片通过，但过程耗时过长。核心问题不是门禁过多，而是需求没有在渲染前完全形式化、参数传递存在双重默认值、缓存失效粒度过粗、最终像素审查介入太晚。

后续目标：**廉价检查前移，局部 smoke 先行，正式全片通常只渲染一次；最终质量门禁保持不降级。**

## 已发生的问题与根因

1. **正文存在但不可读**：正文容器被当作动效元素整体漂移、下沉或提前消失；“DOM 有内容”被误当作“最终像素可读”。
2. **知识卡替代正文**：画面只有标签和字段，没有独立的场景主张与因果解释。
3. **CTA 只在口播中存在**：脚本有收藏和评论提示，但末镜头没有独立视觉 CTA。
4. **字幕位置计划值未生效**：`subtitle_y_up=270` 曾停在 plan，runner 未显式传递，合成阶段又使用第二套默认值，最终 contract 实际为 300。
5. **单帧白闪与短黑场**：稀疏抽帧和 motion score 无法发现单帧异常；xfade 在高信息密度画面中制造文本叠层和空档。
6. **attempt 身份错误**：plan 为 attempt24，可信 manifest 曾沿用默认 `attempt-1`；目录、revision、attempt_id 三套身份未统一。
7. **重复全量渲染**：任何 render contract 字段变化都会删除全部 HTML、shots、TTS 合成和 final，即使只改字幕位置。
8. **测试结论表达不严谨**：定向测试全绿不能表述为全仓测试全绿。当前全仓基线实测为 1266 passed / 39 failed，失败集中在既有 `audio_plan.missing` 合同变化，必须单独治理。

## 不可再犯规则

- 标题、独立正文、知识卡、字幕、CTA 是五个职责不同的可见对象，禁止互相替代。
- A 镜头负责钩子和证据；B 镜头负责完整场景正文。每段正文必须包含“强主张 + 解释”。
- 阅读容器必须固定：`transform:none`，至少两个时间点 bounding box 漂移不超过 0.5px。
- 动效只能发生在扫描线、状态灯、局部高亮、路径、按钮确认等业务 ROI 内。
- 工业解释、教程、审计类视频默认 hard cut；除非证明 xfade 不会造成文本叠层、白场或黑场。
- 字幕参数只允许一条执行链：`plan → runner → renderer → render_contract → final MP4`；禁止合成阶段保留第二套默认值。
- 单帧闪烁必须扫描最终 MP4 全部帧；联系表只用于人工阅读，不能替代亮度门禁。
- 用户否决、像素失败或 contract 不一致时，旧 attempt 立即 supersede；禁止覆盖旧目录或继承旧 HANDOFF_READY。
- HANDOFF_READY 必须同时绑定 run_id、revision、attempt_id、最终视频 SHA、封面 SHA 和六项 gate evidence。
- 每个用户可见缺陷先增加 RED 回归，再改作品。

## 标准快速生产流程

### G0 需求冻结

一次确定：平台、赛道、主题、8 个 beat、16 个 A/B 镜头职责、正文、字幕带、CTA、BGM、封面、转场、renderer 版本和素材权利。

退出条件：`RunSpec`、script、visual contract 和资产哈希全部冻结，无占位符和待定项。

### G1 秒级预检

程序化检查：

- beat / narration / scene contract / asset / subtitle 数量一致；
- 8 个 B 镜头均有独立正文；
- 末段有可见收藏理由、四类条件和评论问题；
- plan 参数能传到 runner env/args；
- BGM、封面和素材 provenance 完整；
- attempt identity 与输出目录一致。

失败只改输入，不启动 Chromium 或全片 FFmpeg。

### G2 16 镜头浏览器预览

生成 8×A/B 共 16 张实拍预览和 contact sheet；浏览器读取两个时间点的 bounding box、transform、overflow、可见文本和碰撞。

退出条件：16/16 通过，用户可见正文、卡片、字幕预留区和 CTA 均成立。

### G3 高风险单段 smoke

只渲染一个最复杂场景的 A/B、TTS、BGM、字幕和真实编码链，检查字体、字幕位置、白闪、音量、动效和合成参数。

退出条件：实际 render contract 与 plan 一致，短片像素和音频通过。正式生产参数在此冻结。

### G4 单次正式渲染

仅当 G0–G3 全通过且输入哈希未变化时启动。正式视频生成后立即计算 SHA，并停止修改输入。

### G5 集中并行验收

并行执行：

- ffprobe、哈希和媒体参数；
- 全帧白闪/黑场；
- 8 段字幕逐字重建；
- 16 镜头布局证据；
- 音频响度和 True Peak；
- 封面；
- 真实时间线抽帧和人工像素审查。

Package gate 等待其他证据完成后再运行。

### G6 用户确认

只交付一个候选版本。用户反馈先集中整理为一张缺陷表，再决定唯一回退层级，禁止发现一项就立刻全片重渲。

## 分层缓存与失效规则

- 改字幕位置/样式：保留 HTML、shots、visual、mixed audio；只重做字幕和 final。
- 改 BGM：保留视觉镜头；只重混音和 final。
- 改某一段正文 DOM：只失效该段 A/B 镜头，再拼接 final。
- 改某段口播：只失效该段 TTS；若时长变化，重算时间轴和 final。
- 改封面：视频不重渲染。
- 改 renderer、字体、浏览器版本、分辨率或全局 CSS：全量失效。

任何缓存命中必须绑定输入摘要、artifact SHA、ffprobe、renderer/Chromium/font/gate 版本；仅凭文件存在、大小和时长不得复用。

## 已落地修复

- `compile_generation_contract()` 从 plan 的 `attempt` 派生 `attempt-N`，冲突时 fail-closed。
- attempt24 已由可信 Release Runtime 重跑，manifest 与六项 evidence 均为 `attempt-24`，最终视频 SHA 未变化。
- runner 显式传递 `subtitle_y_up`，renderer 合成阶段只读取 render contract。
- `prepare_render_contract()` 支持分层失效：字幕坐标变化只清理字幕/final/release evidence，保留浏览器镜头。
- 任何 final 输入变化先删除旧 trusted manifest 和 checker evidence，避免旧 HANDOFF_READY 暂时可见。
- 视频修复 skill 已加入 16 图前置、局部 smoke、单次正式渲染、分层缓存和参数单源传递规则。

## 下一阶段优化

1. 为每个镜头建立 `scene_key` 内容寻址缓存。
2. TTS 建立 `tts_key` 缓存。
3. Chromium 改为单实例、独立 page/context、2 路有界并行。
4. final 像素审计改为单次解码、多 checker 复用同一证据。
5. 每次运行输出 `performance_manifest.json`，记录阶段耗时、缓存命中、失效原因、Chromium 启动数、FFmpeg 编码/解码次数。

验收指标：字幕或 BGM 调整不得触发 Playwright 镜头重录；单场景修改最多重录该场景 A/B；缓存误命中必须为 0；最终像素审查覆盖不低于当前标准。
