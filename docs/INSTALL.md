# 安装指南

[中文](INSTALL.md) | [English](INSTALL.en.md)

版本：`0.1`

## 1. 最短安装路径

```bash
python scripts/install.py
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform project-audit
```

## 2. 安装前准备

建议先确认：

- Python 3.11+
- 是否需要 Hermes CLI
- 是否需要 OpenAI 兼容 API
- 是否已有媒体脚本
- 是否只是本地演练，还是要接真实平台

## 3. 环境变量

- `CONTENT_PLATFORM_HOME`
- `CONTENT_PLATFORM_STYLE_GUIDE`
- `CONTENT_PLATFORM_TREND_CACHE_DIR`
- `SOCIAL_AUTO_UPLOAD_HOME`

## 4. 用户需要确认的选项

### 4.1 安装目录

默认会装到用户目录下的 `.ai-self-media-tools`。

需要确认：

- 是否接受默认目录
- 是否改到独立测试目录
- 是否和服务器运行目录共用

### 4.2 生成 provider

默认配置保留 Hermes CLI 和 fallback。

需要确认：

- 是否使用 Hermes CLI
- 是否有 OpenAI API key
- 是否只走 fallback

### 4.3 媒体脚本

安装脚本会预留这些路径：

- `external/scripts/image_gen.py`
- `external/scripts/video_pipeline.py`
- `external/scripts/ocr_pipeline.py`
- `external/scripts/transcribe_pipeline.py`
- `external/scripts/multimodal_analyze.py`

需要确认：

- 是否已有真实脚本
- 是否先放占位脚本
- 是否先关闭媒体生成

### 4.4 发布方式

默认建议：

- 先 file draft
- 再接真实 publisher

需要确认：

- 是否只做 draft
- 是否接真实平台
- 是否启用 AiToEarn / social-auto-upload

### 4.5 通知方式

需要确认：

- 是否只写本地日志
- 是否启用 Hermes notify
- 是否启用 Telegram / webhook

## 5. 安装后验证

```bash
python -m content_platform health
python -m content_platform content-readiness
python -m content_platform delivery-readiness
python -m content_platform project-audit
```

## 6. 下一步

安装完成后建议继续阅读：

- [项目总览与详细操作说明（中文）](PROJECT_GUIDE.zh.md)
- [致谢、借鉴与集成项目](ACKNOWLEDGEMENTS.md)
