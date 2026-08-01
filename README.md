# AI Self-Media Tools

[English](README.en.md) | 当前版本：`1.0.0`

AI Self-Media Tools 是一个面向自媒体运营者和 AI Agent 的多平台内容运营工具箱。它把账号分析、选题规划、趋势采集、内容生成、图文/视频制作、质量门禁、草稿/半自动发布、发布后复盘串成一条可检查、可追踪、可复用的工作流。

本仓库只包含公开源码、规则、示例配置和工具脚本，不包含作者的个人账号 Cookie、浏览器状态、API Key、代理节点、作品、日志或数据。朋友通过 GitHub 使用时，必须配置自己的账号和运行数据。

## What This Is

这个项目解决的是“多平台内容生产容易跑偏、质量不稳定、发布状态不可验证”的问题。

它不是一个“一键乱发内容”的脚本，而是一个带规则门禁的运营系统：

1. 先分析平台和账号，再决定内容方向。
2. 先生成可审核的内容包，再进入草稿或发布准备。
3. 先通过质量、素材授权、隐私、重复度和平台规则检查，再允许进入后续步骤。
4. 发布后继续记录数据，用播放、点击、收藏、关注、完播等指标反向优化下一轮选题。

## Why It Was Built

单个平台手工运营已经很容易出错，多平台同时运营时更容易出现这些问题：

- 不同平台用了同一套模板，用户看起来很敷衍。
- 内容没有钩子、没有干货、没有真实素材，互动率低。
- 视频只有字幕没有配音，或者 BGM 压住人声。
- 发布器声称成功，但后台没有真实草稿或作品。
- Cookie、日志、作品和账号数据混进项目，无法安全分享给别人。

本项目把这些经验沉淀成可执行规则和检查脚本，尽量让每次内容生产都从“运营分析”开始，而不是直接生成一段机械文案。

## Design Goals

- 默认草稿/半自动优先，真实公开发布必须有健康检查和回查证据。
- 每个平台一套策略，不把公众号、快手、抖音、小红书等混成同一种内容。
- 图文内容必须有完整展开、钩子、插图/知识卡、SEO/GEO 和平台适配。
- 视频内容必须有清晰人声、合适 BGM、下方字幕、真实素材匹配和发布前门禁。
- 公开仓库必须干净，不携带个人隐私、服务器路径、Cookie、账号数据或生成作品。
- Hermes、Codex、Claude Code、OpenCode 等 Agent 可以通过稳定脚本和规则调用。

## How It Works

核心流程如下：

1. 账号与赛道分析：读取平台规则、历史数据、账号状态和赛道定位。
2. 趋势与选题：结合平台内外趋势、竞品内容、关键词热度和去重记录选题。
3. 内容方案：决定本轮数量、内容类型、标题方向、脚本结构、素材要求和发布时间建议。
4. 内容生成：生成文章、图文、知识卡、短视频脚本、标题、正文、话题、封面和 SEO/GEO。
5. 媒体制作：按文案匹配真实素材、生成知识卡、配音、字幕、BGM、封面和视频文件。
6. 质量门禁：检查字数、图片、素材授权、字幕、人声、BGM、视频清晰度、平台规则和重复度。
7. 草稿/交接：自动草稿、文件包、半自动审核包或人工发布材料。
8. 发布后复盘：记录点击、收藏、评论、关注、完播、3 秒播放率和平均观看时长。

## Public Release Scope

`v1.0.0` 是公开分享版本，适合朋友或团队成员基于自己的账号重新初始化使用。

包含：

- 运营策略、内容生成、媒体质量、渠道规则和发布前检查代码。
- 新手安装脚本和平台绑定向导。
- 国内外平台的配置示例和工作流说明。
- 隐私安全打包脚本，避免把个人数据发给别人。

不包含：

- 作者个人 Cookie、浏览器 profile、API Key、代理节点。
- 真实账号数据、历史作品、日志、截图、数据库、发布记录。
- Hermes 服务器私有运行目录或任何个人运行态。

## Requirements

基础要求：

- Python `3.11+`
- Git
- Windows PowerShell、macOS Terminal 或 Linux shell
- 可联网环境

视频相关建议安装：

- `ffmpeg`：视频合成、字幕、音频混音和检测。
- Playwright 浏览器：网页草稿、登录态检查和半自动发布探针。
- 可选：`yt-dlp`、OCR、TTS、图片生成或素材检索工具。

如果你只做公众号/文章草稿，可以先不配置完整视频工具；如果要做快手、抖音、视频号、B站、YouTube、TikTok 等视频渠道，建议先把 `ffmpeg` 和浏览器环境补齐。

## Before You Start

新手先准备这些东西：

- 一个 GitHub 账号，用来下载项目。
- 自己的各平台账号，不要使用别人的 Cookie。
- 一个本地运行目录，例如 Windows 的 `%USERPROFILE%\.ai-self-media-tools`。
- 一个安全保存密钥的地方，例如 `.env` 或 `secrets/provider.env`，不要放进 Git。
- 国内平台需要可访问国内站点的网络环境；国外平台需要可访问对应国外站点的网络环境。
- 如果使用 Hermes 或服务器，请把 Cookie、代理、浏览器 profile 放在服务器私有目录，不要放进仓库。

不要准备或发送给别人：

- Cookie 明文
- API Key 明文
- 代理节点明文
- 浏览器 profile
- 平台后台截图
- 作品原始数据和账号分析导出

## Quick Start

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

安装完成后做一次基础验证：

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## Install Modes

安装脚本是新手入口，建议优先使用。它会做这些事：

1. 检查 Python、Git、项目目录、可选视频工具。
2. 安装 Python 依赖并把项目注册为本地可运行工具。
3. 创建本地私有运行目录，例如 `~/.ai-self-media-tools`。
4. 生成不含真实密钥的示例运行配置。
5. 输出 `installation-report.json`，方便你或 Agent 判断缺什么。
6. 提醒下一步如何运行平台绑定向导。

常用模式：

```bash
python scripts/install.py --mode full
python scripts/install.py --mode check
python scripts/install.py --mode config-only
```

Windows 等价命令：

```powershell
python scripts\install.py --mode full
python scripts\install.py --mode check
python scripts\install.py --mode config-only
```

模式说明：

| 模式 | 会做什么 | 适合谁 |
| --- | --- | --- |
| `full` | 检查环境、安装依赖、创建本地运行目录和配置 | 第一次安装用户 |
| `check` | 只检查，不写配置、不安装依赖 | 想先确认电脑缺什么 |
| `config-only` | 只创建本地运行目录和示例配置 | 已经装好依赖的用户 |

如果安装依赖失败，不要反复乱点。先运行：

```bash
python scripts/install.py --mode check
```

根据报告补齐 Python、Git、ffmpeg 或网络问题后再重新安装。

## Beginner Onboarding Wizard

安装完成后运行新手向导：

```bash
python scripts/onboard_operator.py
```

它会引导你逐个平台准备账号、配置方式、发布模式和验证步骤。它不会读取、打印或上传 Cookie 明文。

只检查当前状态：

```bash
python scripts/onboard_operator.py --check
```

生成本地 `config.json`：

```bash
python scripts/onboard_operator.py --write-config
```

查看单个平台绑定说明：

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform douyin
python scripts/onboard_operator.py --platform shipinhao
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform youtube
python scripts/onboard_operator.py --platform tiktok
python scripts/onboard_operator.py --platform reddit
```

## Platform Matrix

国内平台：

| 平台 | 默认模式 | 内容类型 | 说明 |
| --- | --- | --- | --- |
| 公众号 | 草稿/API 或 Hermes 适配器 | 长图文、GitHub 精选、热点文章、知识卡 | 需要 AppID/AppSecret 或已验证适配器 |
| 快手 | 自动上传 + 发布后回查 | 知识卡视频、真实素材短视频、微案例 | 必须通过 preflight、质量门禁和 postcheck |
| 抖音 | 半自动审核包 | TikTok 热门中文化搬运、猫咪知识、短视频 | 默认只生成完整包，由用户手工发布 |
| 视频号 | 半自动审核包 | 微信生态短视频、知识卡、案例视频 | 默认生成标题、正文、封面、话题和视频包 |
| B站 | 文件包/草稿/扩展上传器 | 教程视频、知识视频、长一点的案例内容 | 需要分区、封面、标签和字幕检查 |
| 小红书 | 半自动审核包 | 图文、知识图块、短视频组合 | 强调真实感、收藏价值和手工发布 |
| 今日头条 | 草稿/文章包 | 长图文、热点分析、经验总结 | 下一步接入重点平台 |
| 掘金 | 自动文章工作流 + 草稿/发布准备 | 技术文章、开源项目解读、工程经验 | 已接入发布器；需使用个人凭据并通过文章质量门禁 |
| 知乎 | 自动文章工作流 + 草稿/发布准备 | 深度回答、观点分析、经验复盘 | 已接入发布器；需使用个人登录态并通过文章质量门禁 |

国外平台：

| 平台 | 默认模式 | 内容类型 | 说明 |
| --- | --- | --- | --- |
| YouTube / Shorts | 半自动或验证上传器 | Shorts、教程、知识视频 | 需要频道登录、标题、描述、标签、封面和字幕 |
| TikTok | 素材采集/半自动包 | 热门素材分析、短视频、本地化改编 | 国外访问环境，必须保留来源证据和合规检查 |
| Reddit | 趋势采集 + 草稿包 | 社区帖子、讨论草稿、选题验证 | 默认不自动发帖，必须检查 subreddit 规则 |
| Dev.to | 草稿/API | 英文技术文章 | 适合开源项目、教程和技术复盘 |
| Telegraph | API/文件发布 | 轻量长文 | 适合外链文章和快速页面 |
| Mastodon | API 发布器 | 短帖、链接分发 | 需要实例地址和 access token |
| Bluesky | API 发布器 | 短帖、链接分发 | 需要账号凭据或应用密码 |
| Nostr | 签名发布器 | 去中心化短帖 | 需要私钥，必须放在私有环境 |
| Write.as | API 发布器 | 轻博客文章 | 需要 API Key |
| Buttondown | API 发布器 | Newsletter | 需要 API Key |
| LinkedIn / X | 手工或扩展发布器 | 职业内容、短帖、链接分发 | 默认建议手工发布，避免账号风控 |

## Recommended First Week

新手不要第一天就绑定所有平台。建议按这个顺序：

1. 第一天：完成安装、运行检查、生成本地配置。
2. 第二天：先做一个手工平台，例如小红书或抖音审核包，只验证内容生成质量。
3. 第三天：配置公众号草稿，验证图文、插图和知识卡。
4. 第四天：配置快手或 B站视频链路，验证 `ffmpeg`、配音、BGM、字幕和封面。
5. 第五天：开启发布后复盘，录入播放、收藏、关注、完播数据。
6. 第六天后：再逐步接入国外平台或更多自动化发布。

## Configuration Rules

复制示例配置：

```bash
cp config.example.json config.json
```

Windows PowerShell：

```powershell
Copy-Item config.example.json config.json
```

只填写你自己的配置。不要提交或分享：

- `config.json`
- `.env`、`.env.*`
- `data/`
- `secrets/`
- `cookies/`
- `logs/`
- `artifacts/`
- `outbox/`
- `.codex-server-runtime/`
- 任意数据库、截图、视频作品、发布记录、平台 Cookie、浏览器 profile、API Key、代理节点

## Sharing With Friends

不要直接压缩自己的工作目录。请用发布包脚本生成干净目录：

```bash
python scripts/release_bundle.py --target /tmp/ai-self-media-tools-public
```

Windows PowerShell：

```powershell
python scripts\release_bundle.py --target C:\Temp\ai-self-media-tools-public
```

只分享生成出来的 `ai-self-media-tools-public` 目录或 GitHub Release 包。详细说明见 [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md)。

## Validation

真实发布前至少运行：

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

常用运行检查：

```bash
python -m content_platform health
python -m content_platform delivery-readiness
python -m content_platform health-refresh
python -m content_platform feedback-summary
```

管理员控制台：

```bash
python -m content_platform admin-serve --password "your-password"
```

## Troubleshooting

| 问题 | 处理方式 |
| --- | --- |
| Python 找不到 | 安装 Python 3.11+，重新打开终端 |
| 依赖安装失败 | 先运行 `python scripts/install.py --mode check` 看缺什么 |
| 视频没有声音或字幕 | 检查 `ffmpeg`，再跑对应视频质量门禁 |
| 平台草稿看不到 | 不要只看接口返回，必须到后台草稿箱或管理页回查 |
| Cookie 失效 | 重新登录自己的账号，并把状态保存在私有运行目录 |
| 担心泄露隐私 | 先运行 `project-audit`，再用 `release_bundle.py` 生成公开包 |

## Repository Structure

- `content_platform/`：核心策略、生成、门禁、发布器和复盘逻辑。
- `scripts/`：安装、平台验证、媒体制作、质量检查和发布辅助脚本。
- `config/`：规则、质量门禁、增长策略和安全配置。
- `docs/`：运营规则、发布说明、公开分享和持续开发文档。
- `skills/`：内容、视觉、运营等可复用技能说明。
- `tests/`：单元测试和回归测试。

## Release

- 当前版本：[v1.0.0](https://github.com/mage0535/ai-self-media-tools/releases/tag/v1.0.0)
- 发布说明：[RELEASE_NOTES_1.0.0.md](RELEASE_NOTES_1.0.0.md)
- 公开分享说明：[docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md)

## License

MIT.
