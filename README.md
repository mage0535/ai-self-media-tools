# AI Self-Media Tools

[中文](README.md) | [English](README.en.md)

当前公开版本：`0.1`

AI Self-Media Tools 是一个面向自媒体内容生产、分析、草稿分发和自动化运营的可发布、可持续开发、跨 agent 工作流项目。

它不是单一的“写文案脚本”，而是一套围绕内容选题、同赛道分析、内容生成、媒体产物、草稿分发、任务自动化和历史学习闭环构建的工作流系统。

## 项目定位

这个项目要解决的不是“如何让模型写一篇内容”，而是以下更完整的问题：

- 如何从趋势和同赛道内容中找到值得做的主题
- 如何把选题和平台形态自动匹配起来
- 如何让生成结果带有风格、节奏、质量门，而不是一次性粗生成
- 如何把内容产物以草稿优先的方式稳定分发到多个平台
- 如何在多次运行后让系统逐步利用历史表现修正自己的判断

## 当前已实现的核心能力

- 选题趋势采集与排序
- 同赛道参考内容归一化、账号画像和 topic clustering
- viral score、内容形态路由和策略解释
- 文本 humanize 与质量门
- 图像 / 视频 / OCR / transcription / analysis provider abstraction
- queue-backed 草稿分发
- AiToEarn 任务自动化基础能力
- 可发布纯净审计
- 跨 agent 安装与运行

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
```

## 推荐阅读顺序

1. 先读 [项目总览与详细操作说明（中文）](docs/PROJECT_GUIDE.zh.md)
2. 再读 [安装指南（中文）](docs/INSTALL.md)
3. 安装完成后跑 `health`、`content-readiness`、`project-audit`
4. 用 `analyze-topic` 和 `account-report` 理解项目的 intelligence 层
5. 再跑 `create -> run -> approve -> publish` 完整链路

## 公开发布说明

本仓库默认采用：

- 中文主说明
- 英文说明可切换
- 草稿优先，不默认直接 live publish
- 所有私密信息通过忽略文件或环境变量管理

## 版本说明

公开发布基线版本统一为 `0.1`。

仓库内早期连续开发文档中保留了部分 `v3.x` 内部波次记录，那些是历史研发波次编号，不再代表当前公开版本号。
