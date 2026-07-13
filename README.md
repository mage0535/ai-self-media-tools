# AI Self-Media Tools（AI 自媒体工具包）

超越「写文案」—— **选题分析 → 内容生成 → 去AI优化 → 多平台分发** 全链路智能体工作流。

> 📦 **定位**：面向 Hermes / OpenCode / Claude Code / Codex 等智能体的内容生产工具链。非独立应用，而是智能体编排的内容工厂。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/) [![edge-tts](https://img.shields.io/badge/edge--tts-84%2B%20languages-green)](https://github.com/rany2/edge-tts) [![Version](https://img.shields.io/badge/version-0.2-orange)](.)

**[English](README.en.md)**

---

## 架构总览

```
入方向：素材世界 → 项目
  ┌────────┐  ┌──────────┐  ┌────────┐  ┌─────────────┐
  │RSS/Atom │  │ OpenSERP │  │GitHub  │  │手动Brief    │
  │75+ 源   │  │ 6 搜索引擎│  │Trending│  │+ 深度研究   │
  └────┬───┘  └────┬─────┘  └────┬───┘  └──────┬──────┘
       └──────┬────┴─────────────┴──────────────┘
              │
         intelligence.py
  来源归一化 → 利基分析 → 病毒评分 → 策略路由
       + Open Notebook 深度研究 + 主题聚类
              │
         generator.py — DraftGenerator v5.0
      Hermes CLI / OpenAI / Fallback 三模式
       + 集群记忆 + 历史表现反馈
              │
     ┌────────┴──────────────────┐
     │    pipeline.run()         │
     |    G1:风控 → G2:GEO → G3:去AI  |
     |     |  → humanizer(24规则) → G4:媒体 → G5:格式完整 |
     |  5门质量合约 · auto-rewrite · Humanizer-zh
     └────────┬──────────────────┘
              │
         media.py — 媒体工厂
        ┌──────────┬──────────┬──────────┐
      image.py   video.py   audio.py   illustrator.py
                                    (新增)归藏材质插画
      ComfyUI/   Remotion/  edge-tts/  8 种图解结构
      QwenImage  AutoClip   Kokoro     GPT-Image 2.0
              │
    ┌─────────┴───────────┐
    │    分发展        │
    │ 23+ 发布器 + 内容矩阵   │
    │ + Newsletter 管      │
    └─────────┬───────────┘
              │
    ┌─────────┴────┐
    │ management_console  │
    │ 一次链+密码 · 全平台  │
    │ 日历 · 仪表盘 · MCP  │
    └──────────────────┘
```

---

## 模块组成

| 模块 | 目录 | 功能 |
|------|------|------|
| **管线编排** | `content_platform/pipeline.py` | 创建→生成→风控→合规→GEO→媒体→审查→发布 |
| **内容智能** | `content_platform/intelligence.py` | 趋势分析、利基分析、病毒评分、策略路由 |
| **内容生成** | `content_platform/generator.py` | DraftGenerator（Hermes / OpenAI / Fallback） |
| **SEO/GEO** | `content_platform/seo.py` | GEO 7 维质量检查 + OpenSERP + pyseoanalyzer |
| **去 AI 优化** | `content_platform/humanize.py` | 47 短语目录 + 谄媚/模糊词替换 + 折度 + 术语锁 |
| **多平台发布** | `content_platform/publishers.py` | 23+ 发布器（微信/抖音/YouTube/LinkedIn/B站等） |
| **配音引擎** | `scripts/voice_engine.py` | edge-tts 84 语言 + Kokoro/Piper 离线备选，去 AI 后处理 |
|| **归藏材质插画** | `content_platform/illustrator.py` | 自动提取概念→判断图解结构→生成归藏风格带中文标签提示词（8 种结构） |
|| **Humanizer-zh 写作去痕** | `content_platform/humanizer.py` | 24 条中文 AI 写作检测规则，自动去 AI 痕迹，Hermes LLM 驱动 |
|| **归藏 Logo 生成** | `content_platform/logogen.py` | SVG Logo 生成，6 种视觉方向，零 API 依赖 |
|| **管理控制台** | `content_platform/admin_server.py` | 全平台总览、详情、绑定、任务中心、GEO 趋势、仪表盘 |
| **内容日历** | `content_platform/scheduler.py` | Cron 驱动的内容排期、日历 API |
| **RSS 摄入** | `content_platform/rss_ingest.py` | RSS/Atom 馈送解析、源项归一化 |
| **Newsletter** | `content_platform/newsletter.py` | RSS→策展→HTML 邮件管线 |
| **MCP 接口** | `content_platform/mcp_server.py` | 8 个 MCP 工具（FastMCP, stdio + SSE） |
| **内容矩阵** | `content_platform/copy_manager.py` | 内容轮转调度、多格式适配 |
| **投递队列** | `content_platform/pipeline.py` | 异步投递队列 + 生成/投递 worker |
| **学习排名** | `content_platform/trends.py` | 主题聚类 + 历史表现反馈 → 趋势排名 |

---

## 25+ 发布器全矩阵

### 🔴 国内平台

| 发布器 | 类型 | 认证 | 能力 |
|--------|:----:|------|------|
| **微信** | REST API | app_id+secret | 图文草稿创建（含封面图） |
| **小红书** | 格式化 | draft | 图文笔记排版 |
| **抖音/快手/视频号** | social-auto-upload | cookie | 短视频发布 |

### 国内浏览器发布后端

抖音、B站、小红书、快手等需要浏览器会话的平台，建议统一走 `social-auto-upload` 后端：

1. 将外部工具安装在项目内 `external/social-auto-upload`，或设置 `SOCIAL_AUTO_UPLOAD_HOME` 指向已有安装目录。
2. 使用外部工具登录账号，账号文件保存在该工具自己的 `cookies/` 目录，例如 `douyin_<account>.json`、`bilibili_<account>.json`。
3. 在运行目录的 `config.json` 中把对应平台配置为 `type: "social-auto-upload"`。
4. 用 `python -m content_platform delivery-readiness` 检查项目目录、Python 环境、CLI 可启动性和账号文件数量。

示例：

```json
{
  "publishers": {
    "platforms": {
      "douyin": {
        "type": "fallback",
        "publishers": [
          {
            "type": "social-auto-upload",
            "platform_name": "douyin",
            "account_name": "<account-alias>"
          },
          {
            "type": "file"
          }
        ]
      },
      "bilibili": {
        "type": "fallback",
        "publishers": [
          {
            "type": "social-auto-upload",
            "platform_name": "bilibili",
            "account_name": "<account-alias>",
            "video_extra_args": ["--tid", "171"]
          },
          {
            "type": "aitoearn-draft",
            "env_file": "secrets/aitoearn.env"
          }
        ]
      }
    }
  }
}
```

B站首次恢复或新增账号时运行：

```bash
cd "$SOCIAL_AUTO_UPLOAD_HOME"
./venv/bin/python sau_cli.py bilibili login --account <account-alias>
./venv/bin/python sau_cli.py bilibili check --account <account-alias>
```

新增渠道时优先复用同一模型：外部工具提供 `<platform> check/login/upload-*`，本项目配置 `platform_name`、`account_name` 和必要的 `extra_args`。上线初期可以用 `type: "fallback"` 保留旧后端兜底，不要把 cookie、token 或服务器路径写入仓库。
| **B 站** | REST API | sessdata | 文章草稿 |
| **博客园** | HTTP | 连通性测试 | 连接检测 |

### 🔵 海外平台

| 发布器 | 类型 | 认证 | 能力 |
|--------|:----:|------|------|
| **YouTube** | Data API v3 | OAuth 刷新令牌 | 视频分块上传 |
| **LinkedIn** | v2 API | Access Token | 帖子发布 |
| **Dev.to** | REST API | API Key | 草稿创建 |
| **Telegraph** | REST API | Token | 页面发布 |
| **Mastodon** | ActivityPub | Access Token | 状态发布 |
| **Bluesky** | AT Protocol | 标识符+密码 | 帖子发布 |
| **Nostr** | WebSocket | 私钥签名 | 中继广播 |
| **WriteAs** | REST API | Token | 文章发布 |
| **GitHub Discussions** | GraphQL | Token | 讨论创建 |
| **Buttondown** | REST API | API Key | 邮件草稿 |
| **Ayrshare** | 聚合 API | API Key | 多平台一次分发 |
| **Email (SMTP)** | SMTP | 用户名+密码 | Newsletter 投递 |
| **File** | 本地 | — | JSON 草稿导出 |

### 🟣 AiToEarn

| 发布器 | 类型 | 说明 |
|--------|:----:|------|
| **AiToEarnDraft** | JSON-RPC | 图文/视频草稿创建 |
| **AiToEarnFlow** | JSON-RPC | 发布流编排 |

---

## 能力矩阵

### GEO 质量检查（KDD 2024 / ICLR 2026）

| 检查项 | 权重 | 检测方式 |
|--------|:----:|----------|
| 数值声明 `claims_with_numbers` | 2 | ≥3 个独立数字 |
| 来源标注 `claims_with_sources` | 2 | URL / 引用 / "研究显示" |
| 权威引用 `authority_quotes` | 1 | 引号>40字符 / 引用块 |
| 直接回答 `direct_answer` | 2 | 前200字含问题/回答模式 |
| 短段落 `short_paragraphs` | 1 | 任意段落>4句 → 失败 |
| 结构化列表 `structured_list` | 1 | 表格或有序/无序列表 |
| FAQ 格式 `faq_section` | 1 | Q标记 / A标记 / 问号≥3 |

### 去 AI 化管线（humanize.py）

| 阶段 | 处理 | 方法 |
|:----:|------|------|
| 1 | 30 通用短语替换 | 结论性/过渡性/重要性/谄媚/模糊 5类 |
| 2 | 7 谄媚模式移除 | `I apologize...`, `I understand...` 等 |
| 3 | 6 模糊语言替换 | `Perhaps you might consider...` 等 |
| 4 | 破折号限制 | 超过 4 个 em-dash 自动替换为逗号 |
| 5 | 折度/猝发度注入 | 句子长度方差 + 词汇可预测性 |
| 6 | 术语锁定 | 数字/URL/命名实体 byte-for-byte 保留 |
| 7 | 语义保真 | embedding 相似度门 ≥0.76 |

### 质量门合约（pipeline 5 门）

| 门 | 检查项 | 通过标准 | 失败处理 |
|:--:|--------|:-------:|---------|
| G1 | 风险+合规 | 非 block | 阻塞 |
| G2 | GEO 质量 | ≥40 | 标记+记录 |
| G3 | 反通用改写 | 有改写 | 自动重写 |
| G4 | 媒体资产完整性 | 取决于内容形式 | 不阻断 |
| G5 | 平台格式完整性 | payload 完整 | 不阻断 |

---

## 快速安装

```bash
git clone https://github.com/<github-owner>/<repository>.git
cd ai-self-media-tools

# 运行安装程序
python scripts/install.py
```

安装程序自动完成：
1. 检测 Agent 环境（Hermes / OpenCode / Claude Code / Codex / Qwen）
2. 渲染 `config.json`
3. 写入安装报告到 `~/.ai-self-media-tools/installation-report.json`

---

## 使用指南

### 1. 系统健康检查

```bash
python -m content_platform health
# → {"ok": true, "version": "0.2", "db_state": "initialized"}

python -m content_platform content-readiness
# → {"tools": {"ffmpeg": {...}, "yt-dlp": {...}, ...}}

python -m content_platform project-audit
# → {"ok": true, "scanned_files": 129}
```

### 2. 内容智能分析

```bash
# 选题分析
python -m content_platform analyze-topic \
  --topic "AI agents 2026" \
  --brief '{"platforms":["wechat","douyin"],"reference_posts":[{"title":"标题","body":"正文"}]}'

# 账号分析
python -m content_platform account-report \
  --topic "AI automation" \
  --brief '{"reference_posts":[{"title":"标题","body":"正文","account_handle":"example_creator","platform":"xiaohongshu"}]}'

# 趋势排名
python -m content_platform trends
```

### 3. 内容生成与发布

```bash
# 创建 → 生成 → 审批 → 发布
python -m content_platform health
python -m content_platform create --topic "AI工作流实战" --platform wechat
python -m content_platform run <job_id>
python -m content_platform approve <job_id> --actor "operator"
python -m content_platform publish <job_id>

# 或一条命令演示完整流程
python -m content_platform demo
```

### 4. 管理控制台

```bash
python -m content_platform admin-serve --password "<admin-password>"
# 输出一次性访问链接 → 浏览器打开 → 输入密码
```

控制台功能：
- 全平台概览（发布数/待审/失败）
- 平台详情（账号绑定+状态+作品统计）
- 任务中心（运行/审批/拒绝/发布）
- 草稿历史版本对比（diff）
- GEO 趋势图
- 内容热力图
- 失败分类统计

### 5. SEO / GEO 分析

```bash
# GEO 质量检查（文件）
python -m content_platform seo-geo-check article.md

# GEO 质量检查（管道输入）
echo "你的内容..." | python -m content_platform seo-geo-check -

# OpenSERP 关键词研究
python -m content_platform keyword-research "AI trends" --engine google

# 页面 SEO 分析
python -m content_platform seo-analyze https://example.com
```

### 6. RSS 摄入 + 排期

```bash
# RSS 馈送摄入
python -m content_platform rss-ingest https://hnrss.org/frontpage --topic tech

# 创建定时任务
python -m content_platform schedule-create --topic "AI新闻" --platform wechat --cron "@daily"

# 查看排期
python -m content_platform schedule-list
```

### 7. Newsletter 生成

```bash
python -m content_platform newsletter https://hnrss.org/frontpage \
  --keywords AI agent --max 10
# 输出 HTML 到 data/newsletters/
```

### 8. 配音生成

```python
from scripts.voice_engine import VoiceEngine
engine = VoiceEngine("./output")
result = engine.synthesize("你好，欢迎收看本教程。", lang="zh", genre="tech")
# → {"audio": "./output/narration.mp3", "subtitle": "./output/subtitles.srt"}
```

### 9. MCP 接口（AI 智能体调用）

```bash
# stdio 模式（推荐用于 AI 智能体）
pip install mcp
python -m content_platform.mcp_server --transport stdio

# SSE 模式（HTTP 端口 9600）
python -m content_platform.mcp_server --transport sse --port 9600
```

可用 MCP 工具：`seo_geo_check`, `trends_query`, `create_job`, `run_job`, `approve_job`, `publish_job`, `review_status`, `generate_audio`

---

## API 接口

### intelligence.py

| 函数 | 功能 |
|------|------|
| `collect_reference_posts(brief, limit)` | 采集同赛道参考帖子 |
| `analyze_reference_posts(posts)` | 风格提取（格式/CTA/开放模式） |
| `build_generation_context(topic, brief)` | 构建完整生成上下文 |
| `prompt_brief(topic, brief)` | 序列化为 JSON prompt |

### pipeline.py (Pipeline)

| 方法 | 功能 |
|------|------|
| `create(topic, platforms, brief)` | 创建内容任务 |
| `run(job_id)` | 生成→风控→合规→GEO→媒体 |
| `approve(job_id, actor, note)` | 审查通过 |
| `reject(job_id, actor, note)` | 审查拒绝 |
| `publish(job_id)` | 发布到配置平台 |
| `process_delivery_queue(limit)` | 消费投递队列 |
| `process_generation_queue(limit)` | 消费生成队列 |

### seo.py

| 函数 | 功能 |
|------|------|
| `geo_check(text)` | GEO 7 维质量检查 |
| `openserp_search(query)` | OpenSERP 关键词研究 |
| `seo_analyze(url)` | pyseoanalyzer 页面分析 |
| `format_geo_report(text)` | GEO 报告格式化 |

### voice_engine.py (VoiceEngine)

| 方法 | 功能 |
|------|------|
| `synthesize(script_text, lang, genre)` | 合成配音 |
| `parse_script(raw_text)` | 解析对话/单人脚本 |
| `detect_language(text)` | 语言自动检测 |
| `detect_genre(text, lang)` | 赛道自动检测 |

### admin_data.py

| 函数 | 功能 |
|------|------|
| `build_overview(db_path)` | 控制台概览 |
| `build_platform_detail(db_path, platform)` | 平台详情（含 LLM 分析） |
| `build_task_center(db_path)` | 任务中心 |
| `build_task_detail(db_path, job_id)` | 任务详情（含对比、GEO 评分） |
| `build_dashboard(db_path)` | 运营仪表盘（KPI/GEO趋势/热力图） |

---

## 更新记录

### 0.2 — 2026-07-08

- Phase 1-8 全量实施完成
- GEO 检查集成到 `pipeline.run()` 自动流，5 门质量合约
- 文本去 AI 全面升级（47 短语/谄媚/模糊/折度/术语锁）
- 内容日历 + RSS 摄入 + Newsletter 管线 + MCP Server
- 运营仪表盘（GEO 趋势/热力图/失败分类）
- 多后端 TTS 桩（Piper/Kokoro）
- 管理控制台任务中心 CRUD + 版对比 + diff
- 157/157 测试通过，三端一致

### 0.1 — 2026-07-08

- 公开基线发布
- 内容智能 MVP（利基分析/病毒评分/策略路由）
- 配音引擎（edge-tts 84 语言）
- 23+ 平台发布器
- Open Notebook 深度研究集成
- AiToEarn 任务市场自动化
- 主题聚类 + 历史表现学习 + 投递队列

---

## 相关项目

- **Knowledge-and-Memory-Management** — AI 知识采集与记忆体管理插件。40+ 采集工具、SenseNova 文档引擎、12+ 云盘同步、三层知识召回。
- **[Hermes Agent](https://github.com/nousresearch/hermes)** — Hermes 智能体框架
- **[edge-tts](https://github.com/rany2/edge-tts)** — 84+ 语言 TTS 引擎
- **[Kokoro](https://github.com/hexgrad/kokoro)** — 82M 参数离线 TTS

---

## 许可证

MIT License © 2026
