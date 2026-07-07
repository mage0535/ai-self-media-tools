# AI Self-Media Tools

[中文](README.md) | [English](README.en.md)

当前公开版本：`0.2`

AI Self-Media Tools 是一个面向自媒体内容生产、分析、草稿分发、平台账号管理和自动化运营的跨 agent 工作流项目。

它不是单一“写文案工具”，而是一套围绕：

- 选题
- 趋势分析
- 同赛道参考
- topic clustering
- 历史表现学习
- 内容生成
- 质量门
- 草稿优先分发
- 管理台可视化操作

构建的完整系统。

## 解决的问题

- 热点很多，但不知道先做什么
- 有参考内容，但难以系统化分析
- AI 生成内容容易空、泛、同质化
- 多平台发布和账号管理复杂
- 做了很多内容，但系统不会自动从历史表现中学习

## 已实现的核心能力

- 趋势采集与 topic ranking
- source normalization、账号画像、topic clustering
- viral score 与 strategy routing
- humanize 与 quality gate
- queue-backed draft delivery
- provider abstraction（图像 / 视频 / OCR / transcription / analysis）
- 平台多账号绑定与状态管理
- 一次性访问链接 + 密码登录的内置管理台
- 可发布纯净审计

## 管理页面

管理页通过项目内置服务启动：

```bash
python -m content_platform admin-serve --password "你的密码"
```

启动后会输出一次性访问链接。

特点：

- 链接一次性
- 访问时必须输入密码
- 登录后使用浏览器会话 cookie
- 关闭浏览器后会话自动失效

管理页支持：

- 全平台总览
- 各平台详情页
- 多账号绑定
- 账号状态检测
- 最新 5 个作品统计
- 已发布 / 草稿 / 队列 / 异常情况
- 全平台和各平台图表

## 文档入口

- [项目总览与详细操作说明（中文）](docs/PROJECT_GUIDE.zh.md)
- [Project Guide (English)](docs/PROJECT_GUIDE.en.md)
- [安装指南（中文）](docs/INSTALL.md)
- [Installation Guide (English)](docs/INSTALL.en.md)
- [致谢、借鉴与集成项目](docs/ACKNOWLEDGEMENTS.md)
- [持续开发文档](docs/CONTINUOUS_DEVELOPMENT.md)

## 快速开始

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform analyze-topic --topic "AI workflows" --brief "{\"platforms\":[\"wechat\",\"douyin\"]}"
python -m content_platform admin-serve --password "your-password"
```

## 版本说明

公开发布基线版本统一为 `0.2`。

仓库中连续开发文档保留的 `v3.x` 记录仅代表历史研发波次，不再代表当前公开版本号。
