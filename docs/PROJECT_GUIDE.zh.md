# 项目总览与详细操作说明

[中文](PROJECT_GUIDE.zh.md) | [English](PROJECT_GUIDE.en.md)

版本：`0.2`

## 1. 这个项目在做什么

AI Self-Media Tools 是一个自媒体内容工作流系统，目标不是单点生成，而是把“选题、参考、判断、生成、产物、分发、反馈、管理”做成一条可重复、可验证、可持续优化的链路。

## 2. 解决的问题

- 热点和趋势很多，但不知道哪些值得先做
- 参考内容很多，但难以系统化分析
- 生成式内容容易泛、空、同质化
- 多平台分发和账号管理复杂
- 做了很多内容，但系统不会自动从历史表现中学习

## 3. 实现目标

- 把趋势和同赛道内容转成结构化 intelligence
- 自动对 topic 打分、聚类并给出策略建议
- 让内容按平台形态输出长文、图文、短视频脚本等不同形式
- 通过质量门、人审和草稿分发降低风险
- 利用历史表现持续修正 topic ranking 和生成判断
- 给运营者提供一个可视化管理页进行平台、账号、作品和队列管理

## 4. 项目方向

项目分成两层：

1. intelligence layer
- 趋势、参考内容、账号、topic cluster、历史表现

2. execution layer
- 文本生成、媒体产物、草稿分发、任务自动化、管理台

## 5. 核心工作流

### 5.1 选题与分析

1. 收集趋势或输入主题
2. 归一化参考内容
3. 生成同赛道账号画像与 topic cluster
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

```bash
python -m content_platform create --topic "AI 自动化" --platform wechat --platform xiaohongshu
python -m content_platform run <job_id>
```

### 5.3 审批

```bash
python -m content_platform approve <job_id> --actor operator --note "checked"
python -m content_platform reject <job_id> --actor operator --note "rewrite"
```

### 5.4 草稿分发 / 发布

```bash
python -m content_platform publish <job_id>
python -m content_platform status <job_id>
```

### 5.5 反馈学习

```bash
python -m content_platform record-performance <job_id> --platform wechat --views 1200 --likes 90 --comments 25 --shares 12
python -m content_platform feedback-summary
```

### 5.6 管理页面

```bash
python -m content_platform admin-serve --password "<admin-password>"
```

操作流程：

1. 命令返回一次性访问链接
2. 打开链接并输入密码
3. 首页查看全平台总览、图表、最新作品、待审核和异常
4. 点击平台卡片进入平台详情页
5. 在平台详情页新增/更新/启停绑定账号
6. 对账号执行状态检测
7. 查看该平台最新 5 个作品与图表

## 6. 管理页面组成

### 首页

- 全平台 KPI
- 平台概览卡片
- 全平台投递状态图表
- 全平台绑定数图表
- 最新 5 个作品
- 待审核任务
- 最近失败记录

### 平台详情页

- 返回按钮
- 平台基础能力说明
- 绑定账号列表
- 绑定向导
- 账号新增/更新表单
- 平台统计图表
- 最新 5 个作品
- 失败记录与 readiness 数据

## 7. 集成的工具

- `ffmpeg`
- `yt-dlp`
- `playwright`
- `AutoCLI`
- `Open Notebook`
- `AiToEarn`
- `social-auto-upload`
- OCR / transcription / analysis script providers
- 内置管理页服务

详细致谢见：
- [致谢、借鉴与集成项目](ACKNOWLEDGEMENTS.md)

## 8. 每一步的具体操作方法

### 8.1 安装

```bash
python scripts/install.py
```

### 8.2 基础检查

```bash
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform delivery-readiness
python -m content_platform project-audit
```

### 8.3 主题分析

```bash
python -m content_platform analyze-topic --topic "AI 自动化工作流" --brief "{\"platforms\":[\"wechat\",\"douyin\"]}"
python -m content_platform account-report --topic "AI 自动化工作流" --brief "{\"reference_posts\":[]}"
```

### 8.4 生成与审批

```bash
python -m content_platform create --topic "AI 自动化工作流" --platform wechat --platform xiaohongshu
python -m content_platform run <job_id>
python -m content_platform approve <job_id> --actor operator --note "checked"
```

### 8.5 草稿发布

```bash
python -m content_platform publish <job_id>
python -m content_platform status <job_id>
```

### 8.6 管理页启动与操作

```bash
python -m content_platform admin-serve --password "<admin-password>"
```

## 9. 生成的产物

- job 状态
- draft metadata
- topic clusters
- account snapshots
- idea candidates
- media artifacts
- platform draft payloads
- metrics
- notification logs
- 管理台绑定数据与图表数据

## 10. 安装过程中需要用户确认的选项

1. 安装目录  
2. 生成提供方  
3. 媒体脚本路径  
4. 发布方式  
5. 通知方式  
6. 是否接入真实凭据  
7. 管理页密码和访问方式

## 11. 规划

当前 `0.2` 已完成的重点是：

- intelligence 厚化
- topic clustering
- 历史表现回流
- quality gate
- queue-backed delivery
- provider abstraction
- 管理页
- 多账号绑定和平台级图表

后续建议：

- 自动学习权重校准
- 独立 worker 化
- provider 优先级 / fallback 矩阵
- 更强的长期记忆与跨任务 topic ranking 调优
