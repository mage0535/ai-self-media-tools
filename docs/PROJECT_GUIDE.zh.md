# 项目总览与详细操作说明

[中文](PROJECT_GUIDE.zh.md) | [English](PROJECT_GUIDE.en.md)

版本：`0.1`

## 1. 这个项目在做什么

AI Self-Media Tools 是一个自媒体内容工作流系统，目标不是单点生成，而是把“选题、参考、判断、生成、产物、分发、反馈”做成一条可重复、可验证、可持续优化的链路。

## 2. 解决的问题

项目重点解决以下问题：

- 热点和趋势很多，但不知道哪些值得做
- 参考内容很多，但难以系统化分析
- 生成式内容容易泛、空、同质化
- 多平台分发容易出错，且发布风险高
- 产出做了很多，但系统不会从历史表现中学习

## 3. 实现目标

- 把趋势和同赛道内容转成结构化 intelligence
- 自动给 topic 打分、聚类、生成策略建议
- 让内容按平台形态输出长文、图文、短视频脚本等不同形式
- 通过质量门、人审和草稿分发降低风险
- 利用历史表现持续修正 topic ranking 和生成判断

## 4. 项目方向

项目分成两层：

1. intelligence layer
- 趋势、参考内容、账号、topic cluster、历史表现

2. execution layer
- 文本生成、媒体产物、草稿分发、任务自动化

## 5. 核心工作流

### 5.1 选题与分析

1. 收集趋势或输入主题
2. 归一化参考内容
3. 生成同赛道账号与 topic cluster 画像
4. 计算 viral score
5. 生成 strategy route

相关命令：

```bash
python -m content_platform trends --limit 10
python -m content_platform analyze-topic --topic "AI 自动化"
python -m content_platform account-report --topic "AI 自动化"
```

### 5.2 生成

1. 创建 job
2. 运行 generator
3. 生成 draft_meta、quality gate、media prompts
4. 根据风险与质量门进入 review

相关命令：

```bash
python -m content_platform create --topic "AI 自动化" --platform wechat --platform xiaohongshu
python -m content_platform run <job_id>
```

### 5.3 审批

1. 人工查看 draft 与 artifacts
2. approve 或 reject

```bash
python -m content_platform approve <job_id> --actor operator --note "checked"
python -m content_platform reject <job_id> --actor operator --note "rewrite"
```

### 5.4 草稿分发 / 发布

1. queue-backed delivery 入队
2. 平台 publisher 执行
3. 默认优先输出 draft / handoff

```bash
python -m content_platform publish <job_id>
python -m content_platform status <job_id>
```

### 5.5 反馈学习

1. 记录平台表现
2. 聚合历史表现
3. 下次生成前自动注入 historical feedback 和 cluster memory

```bash
python -m content_platform record-performance <job_id> --platform wechat --views 1000 --likes 80 --comments 20 --shares 10
python -m content_platform feedback-summary
```

## 6. 集成的工具

当前已集成或可探测的工具方向包括：

- `ffmpeg`
- `yt-dlp`
- `playwright`
- `AutoCLI`
- `Open Notebook`
- `AiToEarn`
- `social-auto-upload`
- OCR / transcription / analysis script providers

以及能力层面整合的项目/参考：

- html-anything
- last30days-skill
- alphacouncil-agent
- claude-obsidian
- translate-book
- AutoClip
- GitHub Star Explorer
- OpenSERP / pyseoanalyzer / GEO checklist

详细致谢见：
- [致谢、借鉴与集成项目](ACKNOWLEDGEMENTS.md)

## 7. 每一步的具体操作方法

### 7.1 安装

```bash
python scripts/install.py
```

### 7.2 基础检查

```bash
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform delivery-readiness
python -m content_platform project-audit
```

### 7.3 主题分析

```bash
python -m content_platform analyze-topic --topic "AI 自动化工作流" --brief "{\"platforms\":[\"wechat\",\"douyin\"]}"
python -m content_platform account-report --topic "AI 自动化工作流" --brief "{\"reference_posts\":[]}"
```

### 7.4 生成与审批

```bash
python -m content_platform create --topic "AI 自动化工作流" --platform wechat --platform xiaohongshu
python -m content_platform run <job_id>
python -m content_platform approve <job_id> --actor operator --note "checked"
```

### 7.5 草稿发布

```bash
python -m content_platform publish <job_id>
python -m content_platform status <job_id>
```

### 7.6 反馈回写

```bash
python -m content_platform record-performance <job_id> --platform wechat --views 1200 --likes 90 --comments 25 --shares 12
python -m content_platform feedback-summary
```

## 8. 生成的产物

项目会产出：

- 结构化 job 状态
- `draft_meta`
- topic cluster memory
- account snapshot
- idea candidate
- media artifacts
- platform draft payload
- metrics 文件
- notifications 日志

## 9. 下一步对应选项

如果你已经完成基础安装，通常会进入以下选择之一：

1. 只做 topic 分析
2. 生成单个平台内容
3. 生成多平台草稿
4. 接入真实媒体工具链
5. 接入真实发布凭据
6. 继续做策略学习和自动调优

## 10. 安装步骤详解

### 步骤 1：确定安装根目录

默认使用：

- `CONTENT_PLATFORM_HOME`
- 如果未设置，则使用用户目录下的 `.ai-self-media-tools`

用户需要确认的选项：

- 是否使用默认安装目录
- 是否改为独立测试目录
- 是否与现有运行目录共用

建议：

- 开发/测试：使用独立目录
- 生产运行：使用明确的专用目录

### 步骤 2：确认生成 provider

默认配置会保留：

- `hermes-cli` provider
- fallback generator
- 可选 OpenAI 兼容 provider

用户需要确认：

- 是否有可用 Hermes CLI
- 是否有 OpenAI API key
- 是否只走 fallback

### 步骤 3：确认媒体脚本

安装脚本会为以下脚本预留路径：

- `image_gen.py`
- `video_pipeline.py`
- `ocr_pipeline.py`
- `transcribe_pipeline.py`
- `multimodal_analyze.py`

用户需要确认：

- 是否已经有可运行脚本
- 是否先用占位脚本
- 是否暂时关闭媒体产物生成

### 步骤 4：确认发布模式

默认推荐：

- draft-first
- network-disabled notifications
- 不直接 live publish

用户需要确认：

- 是否只输出 file drafts
- 是否启用真实平台 publisher
- 是否配置 AiToEarn / social-auto-upload

### 步骤 5：确认通知方式

用户需要确认：

- 是否只写本地日志
- 是否启用 Hermes notify
- 是否启用 Telegram / webhook

## 11. 安装过程中需要用户确认的每个选项

1. 安装目录  
影响：数据、配置、运行态文件放在哪里。

2. 生成提供方  
影响：生成质量、成本、可用性。

3. 媒体脚本路径  
影响：是否能生成图像、视频、OCR、转写等产物。

4. 发布方式  
影响：只输出草稿，还是尝试真实平台分发。

5. 通知方式  
影响：review / publish / blocked 状态如何回传。

6. 是否接入真实凭据  
影响：是否只是演练工作流，还是进入真实交付。

## 12. 规划

当前 `0.1` 已完成的重点是：

- intelligence 厚化
- topic clustering
- 历史表现回流
- quality gate
- queue-backed delivery
- provider abstraction

后续建议：

- 自动学习权重校准
- 独立 worker 化
- provider 优先级 / fallback 矩阵
- 长期 memory 与跨任务 topic ranking 调优
