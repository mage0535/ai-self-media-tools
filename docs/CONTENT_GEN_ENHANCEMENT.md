# Hermes Skills 增强层 — 项目一可选能力

## 定位

不是独立项目，是 Hermes 运行时可调用的能力层。
项目一的自有 `generator.py`/`intelligence.py`/`humanize.py` 已覆盖基础内容生成。
增强层通过 `content_gen_fusion.py` 桥接，在需要更高生成质量时按需启用。

## 调用方式

```bash
# 基础模式（使用项目一自有引擎）
python -m content_platform trends --limit 5
python -m content_platform analyze-topic --topic "..."

# 增强模式（启用 Hermes Skills）
python /root/.hermes/scripts/content_gen_fusion.py --topic "AI Agent" --type article
python /root/.hermes/scripts/content_gen_fusion.py --topic "大模型落地" --type video-script
python /root/.hermes/scripts/content_gen_fusion.py --list-types
```

## 对应关系

| 增强能力 | 对应 Skills | 补充项目一缺失的 |
|---------|------------|----------------|
| 实时热点采集 | AutoCLI (bilibili/douban) | 项目一无热数据采集 |
| 封面/配图 | canghe-cover-image, canghe-xhs-images | 项目一无配图模块 |
| 视频脚本 | huashu-douyin-script, huashu-video-outline | 项目一无脚本模块 |
| 审校纠错 | huashu-proofreading | 比 humanize.py 更专业的审校 |
| 系列信息图 | canghe-infographic, canghe-slide-deck | 项目一无信息图能力 |

## 前提

- Hermes 运行中（Gateway :8642）
- Hermes skills 目录有对应 skill
- AutoCLI 需要时 Chrome 扩展 + daemon（port 19925）
