# AI Self-Media Tools

[English](README.en.md) | 当前版本：`1.0.0`

AI Self-Media Tools 是一个面向 AI 智能体和内容运营者的自媒体工作流工具箱。它把“运营分析、选题、内容生成、图文/视频制作、质量门禁、草稿/发布前验证、数据复盘”串成一条可审计的流程。

这个项目可以给不同操作者使用，但每个人必须使用自己的账号、Cookie、代理、API Key 和运行数据。本仓库只包含公开源码、规则、示例配置和工具，不包含作者个人账号状态或作品数据。

## 核心能力

- 运营策略：账号阶段、赛道定位、同赛道参考、跨平台趋势、历史数据复盘。
- 内容生成：文章、图文、知识卡片、短视频脚本、标题、正文、话题、SEO/GEO。
- 视觉与视频：知识卡片、真实素材匹配、字幕、配音、BGM、竖屏视频质量门禁。
- 平台适配：公众号、快手、抖音、视频号、B站、小红书，以及今日头条、掘金、知乎等扩展渠道。
- 发布安全：默认草稿/半自动优先，自动发布必须经过健康检查、内容质量门禁、素材授权和发布后回查。
- 复盘闭环：记录浏览、互动、收藏、涨粉、完播率、3秒播放率、平均观看时长和平台自定义指标。

## 适合谁

- 想用 AI 辅助多平台内容运营的人。
- 想把自媒体内容生产流程标准化的人。
- 想让 Hermes、Codex、Claude Code、OpenCode 等智能体调用工具完成内容工作的开发者。
- 想先从本地草稿和手工发布开始，逐步打通自动化的人。

## 安装

需要 Python 3.11 或更高版本。

```bash
git clone https://github.com/mage0535/ai-self-media-tools.git
cd ai-self-media-tools
pip install -r requirements.txt
pip install -e .
```

初始化和检查：

```bash
python -m content_platform init
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## 新手逐步向导

电脑小白建议先运行交互式向导。它不会读取或上传你的 Cookie 明文，只会引导你检查 Python、配置文件、运行目录、平台绑定方式和必要工具。

```bash
python scripts/onboard_operator.py
```

只检查当前状态，不写配置：

```bash
python scripts/onboard_operator.py --check
```

生成本地配置文件：

```bash
python scripts/onboard_operator.py --write-config
```

按平台查看绑定步骤：

```bash
python scripts/onboard_operator.py --platform wechat
python scripts/onboard_operator.py --platform kuaishou
python scripts/onboard_operator.py --platform douyin
python scripts/onboard_operator.py --platform shipinhao
python scripts/onboard_operator.py --platform bilibili
python scripts/onboard_operator.py --platform xiaohongshu
python scripts/onboard_operator.py --platform toutiao
python scripts/onboard_operator.py --platform juejin
python scripts/onboard_operator.py --platform zhihu
```

## 平台工作方式

| 平台 | 默认方式 | 说明 |
| --- | --- | --- |
| 公众号 | 草稿/API 或 Hermes 适配器 | 适合长图文、知识卡片、GitHub精选和热门内容 |
| 快手 | 自动工作流 + 上传后回查 | 适合知识卡片视频、真实素材短视频 |
| 抖音 | 半自动审核包 | 当前建议生成完整作品包，由用户手工发布 |
| 视频号 | 半自动审核包 | 生成视频、标题、正文、封面、话题，由用户确认后发布 |
| B站 | 草稿/文件包/扩展上传器 | 适合教程型视频、长一点的知识内容 |
| 小红书 | 半自动审核包 | 图文、知识图块、短视频组合，用户手工发布 |
| 今日头条 | 草稿/文章包 | 适合完整图文内容 |
| 掘金 | 草稿/文章包 | 适合技术文章和开源项目解读 |
| 知乎 | 草稿/文章包 | 适合深度问答、观点分析和经验复盘 |

## 配置原则

复制示例配置：

```bash
cp config.example.json config.json
```

Windows PowerShell：

```powershell
Copy-Item config.example.json config.json
```

然后只填写你自己的信息。不要把下面内容提交或发给别人：

- `config.json`
- `.env`、`.env.*`
- `data/`
- `secrets/`
- `cookies/`
- `logs/`
- `artifacts/`
- `outbox/`
- `.codex-server-runtime/`
- 任何数据库、截图、视频作品、发布记录、平台 Cookie、浏览器 profile、API Key、代理节点

## 安全分享给朋友

不要直接打包你的工作目录。请用发布包脚本生成干净目录：

```bash
python scripts/release_bundle.py --target /tmp/ai-self-media-tools-public
```

Windows PowerShell：

```powershell
python scripts\release_bundle.py --target C:\Temp\ai-self-media-tools-public
```

只分享生成出来的 `ai-self-media-tools-public` 目录。详细说明见 [docs/PUBLIC_DISTRIBUTION.md](docs/PUBLIC_DISTRIBUTION.md)。

## 常用命令

```bash
python -m content_platform health
python -m content_platform delivery-readiness
python -m content_platform health-refresh
python -m content_platform feedback-summary
python -m content_platform admin-serve --password "your-password"
```

## 发布前检查

任何真实发布前都建议执行：

```bash
python -m content_platform project-audit
python scripts/validate_channel_rulebook.py
pytest -q
```

## 许可证

MIT
