# AI Self-Media Tools

[English](README.en.md) | 当前版本：`1.0.0`

AI Self-Media Tools 是一个面向自媒体运营者和 AI Agent 的多平台内容运营工具箱。它把账号数据复盘、运营策略、选题、图文/视频生成、素材授权、质量门禁、草稿/交接/发布和发布后复盘串成一条可检查、可追踪、可复用的工作流。

这个仓库只包含公开源码、规则、示例配置和工具脚本，不包含作者个人 cookie、浏览器状态、API Key、代理节点、账号数据、作品、截图、日志或数据库。朋友通过 GitHub 使用时，需要绑定自己的账号和私有运行数据。

## 适合解决什么问题

- 多平台运营时，容易把同一主题、同一模板、同一视频反复套用。
- 内容缺少钩子、干货、真实素材和明确 CTA，导致阅读、完播、收藏和涨粉低。
- 视频容易出现无 BGM、人声被 BGM 压住、字幕遮挡、画面和文案不匹配。
- 发布器显示成功，但后台没有真实草稿或作品。
- 项目目录混入 cookie、账号数据、作品和运行记录，无法安全分享给他人。

本项目的核心目标不是“一键乱发”，而是“运营先行 + 内容生成 + 可执行门禁 + 可回查证据”。

## 核心工作流

1. 账号与赛道分析：读取账号定位、历史表现、平台状态和增长策略。
2. 趋势与选题：结合平台内数据、同赛道账号、多平台热榜、搜索趋势和历史去重。
3. 内容规划：确定数量、内容形式、标题、hook、脚本、素材、封面、发布时间。
4. 内容生成：生成长文、图文、知识卡、短视频脚本、标题、正文、标签、SEO/GEO。
5. 媒体制作：匹配真实素材或合规生成素材，制作图片、知识卡、配音、字幕、BGM、视频。
6. 质量门禁：检查 preflight、recipe、工具调用、素材授权、BGM 指纹、字幕安全区、重复度、平台格式。
7. 发布或交接：自动平台进入草稿/定时/postcheck；手工平台输出完整 handoff 包。
8. 发布后复盘：采集播放、阅读、点赞、评论、收藏、转发、涨粉、完播等数据，反向更新增长策略。

## 新增的强约束层

当前版本已经把“规则写在文档里”升级为“规则必须进入代码门禁”：

- `preflight_manifest`：证明已经读取规则、策略、素材需求和发布约束。
- `content_recipe`：长文、图文和知识图块必须说明结构、模板变化、插图绑定、首屏承诺和 7 天疲劳检查。
- `visual_recipe`：视频必须说明模板族、效果模块、分镜素材匹配、视觉差异化和跨平台防复用。
- `tool_invocation_manifest`：内容包必须记录计划调用和实际调用的工具，避免只靠 Agent 记忆。
- BGM 门禁：必须是真实网络乐器音乐，记录来源、授权和指纹；禁止静音、合成兜底和重复用曲。
- 媒体交付门禁：视频和封面必须独立 `MEDIA:<absolute_path>` 交付，不能塞在长文本尾部。

## 支持的平台

国内平台：

| 平台 | 默认模式 | 内容类型 |
| --- | --- | --- |
| 公众号 | 草稿/API/Hermes adapter | 长文、GitHub 精选、热点文章、知识卡 |
| 快手 | 自动上传 + postcheck | 知识卡视频、真实素材短视频、微案例 |
| B站 | handoff 包 | 16:9 横屏教程、知识视频、案例视频 |
| 知乎 | 草稿/文章包 | 深度回答、观点分析、经验复盘 |
| 掘金 | 草稿/文章包 | 技术文章、开源项目解读、工程经验 |
| 抖音 | handoff 包 | TikTok 本地化搬运、猫咪内容、短视频 |
| 视频号 | handoff 包 | 微信生态短视频、知识卡、案例视频 |
| 小红书 | handoff 包 | 图文、知识图块、短视频组合 |

国际平台：

| 平台 | 默认模式 | 内容类型 |
| --- | --- | --- |
| X/Twitter | 自动/草稿，按配置 | 短帖、链接分享、增长实验 |
| YouTube | handoff 包 | Shorts、横屏教程、知识视频 |
| TikTok | handoff 包 | 热门素材分析、本地化短视频 |
| Dev.to | 草稿/API | 英文技术文章 |
| Bluesky / Mastodon / Nostr | API 或草稿 | 短帖、链接分享 |

百家号和今日头条当前不作为主流程平台。

## 安装

### Windows PowerShell

```powershell
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
.\install.ps1
python scripts\onboard_operator.py
```

### macOS / Linux

```bash
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
./install.sh
python scripts/onboard_operator.py
```

基础验证：

```bash
python -m content_platform.cli project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## 新手绑定账号

安装后运行：

```bash
python scripts/onboard_operator.py
```

只检查当前状态：

```bash
python scripts/onboard_operator.py --check
```

查看单个平台说明：

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform youtube
python scripts/onboard_operator.py --platform tiktok
```

## 常用工具

```bash
# 项目隐私和安全审计
python -m content_platform.cli project-audit

# 渠道规则校验
python scripts/validate_channel_rulebook.py

# 图片提供商 smoke test，不打印密钥
python scripts/smoke_image_provider.py --providers pollinations,cloudflare,auto

# 视频 recipe 校验
python scripts/validate_visual_recipe.py --recipe /path/to/visual_recipe.json

# BGM 指纹去重
python scripts/check_bgm_uniqueness.py /path/to/render_dir --platform kuaishou

# 平台选题独立性检查
python scripts/check_platform_topic_independence.py 20260807 --platforms wechat,kuaishou,bilibili

# 独立发送媒体文件，目标从 HERMES_DELIVERY_TARGET 读取
python scripts/deliver_media.py "视频交付" /path/to/final.mp4 /path/to/cover.jpg
```

## 隐私和公开分享边界

不要提交或分享：

- `config.json`
- `.env`、`secrets/`
- `data/`
- `cookies/`
- `logs/`
- `artifacts/`
- 浏览器 profile
- 账号截图、作品、数据库、发布记录
- cookie、API key、token、代理节点

分享给朋友时，建议只分享 GitHub 仓库或由发布脚本生成的干净包。更多说明见 [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md)。

## Hermes / Agent 使用建议

Hermes 或其他 Agent 执行自动任务前必须先做：

1. 读取固定《账号增长策略》。
2. 运行 `performance-cycle` 刷新真实数据。
3. 调用能力检查或 MCP `capability_status`。
4. 每个平台生成独立 `platform_source_matrix`。
5. 内容包必须包含 `preflight_manifest`、`content_recipe` 或 `visual_recipe`、`tool_invocation_manifest`。
6. 自动发布平台必须 postcheck；手工平台只能输出 `handoff_pending`。

如果任何门禁失败，先修复并重跑；连续失败则标记 `blocked`，禁止绕过。

## 开发验证

```bash
python -m py_compile content_platform/content_recipe.py content_platform/video_recipe.py scripts/mix_bgm_with_gate.py
pytest -q
python -m content_platform.cli project-audit
python scripts/validate_channel_rulebook.py
```

## Trend Intelligence Cache

`overnight-prepare` stores one public-metadata trend snapshot per freshness window and reuses it for later platform selection. The snapshot preserves every source status, including failures and degradation; a cache never turns an unavailable source into a verified signal.

Each candidate now carries a platform-scoped `platform_source_matrix`, a historical-fit calibration score, and an optional breakout marker calculated against the previous snapshot. Downstream quality gates still decide whether evidence is sufficient to generate or publish. The intelligence layer collects and ranks only; it never changes login state or publishes content.

## License

请根据各平台规则和素材授权自行合规使用。本项目不会替你授权第三方素材、音乐、账号或平台接口。
