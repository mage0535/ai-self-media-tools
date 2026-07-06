# Channel Matrix — 运营推广渠道类型参考

## 发布器类型（publisher）

| 类型 | 渠道示例 | 认证方式 | 备注 |
|------|---------|---------|------|
| `file` | 本地草稿箱 | 无 | 最基础的存入文件发布 |
| `devto` | Dev.to | API Key | Draft-first，人工复核后发布 |
| `aitoearn` | AiToEarn | API Key | 任务市场/流量池 |
| `sau` | social-auto-upload | Cookie/Token | 抖音/小红书/B站等国内平台 |
| `crier` | Crier管理渠道 | 混合 | 统一消息队列接口 |
| `email` | Buttondown | API Key | 邮件通讯 |
| `mastodon` | Mastodon ×7 | OAuth Token | 联邦微博 |
| `bluesky` | Bluesky | 用户名+密码, API Key | AT协议社交 |
| `discourse` | 论坛 | 用户名+密码 | 自建/SAAS论坛 |
| `telegraph` | Telegraph | 匿名 | 零认证，即写即发 |

## 内容生成工作流参考（可选增强层）

项目一自有的 `generator.py`/`intelligence.py` 覆盖基础内容生成。以下为 **Hermes Skills 可选增强**，通过 `content_gen_fusion.py` 桥接，按需启用：

**自动识别入口（推荐）**: `python -m content_platform auto-gen <自然语言提示>`
- 自动分析意图 → 路由到正确工作流链 → 联动多 skill 执行
- 示例: `python -m content_platform auto-gen 写一篇AI热点公众号文章`

| 阶段 | 自有方案（默认） | 增强方案（可选，需 Hermes） |
|------|----------------|---------------------------|
| **题材/热点** | `intelligence.py` 内置趋势分析 | AutoCLI 实时热点采集（bilibili/douban） |
| **深度写作** | `generator.py` 自有生成引擎 | khazix-writer 公众号深文 + huashu-article-edit |
| **审校优化** | `humanize.py` 基础改写 | huashu-proofreading 纠错 + huashu-script-polish 口语化 |
| **配图生成** | 无（项目一无配图模块） | canghe-xhs-images/cover-image/infographic |
| **视频脚本** | 无 | huashu-douyin-script + huashu-video-outline |
| **发布** | `publishers.py` + AiToEarn | canghe-post-to-wechat/x（补充路径） |

增强层调用方式: `python -m content_platform gen-content --topic "..." --type [article|video|social|image]`

## 渠道分布（444 注册 / 38 verified）

| 区域 | 平台类型 | 数量 | 状态 |
|------|---------|------|------|
| 国际 | Blog/社交 | ~200 | 38 verified |
| 国内 | 抖音/小红书/B站 | ~30 | 0 active |
| 国际 | Pastebin/沙盒 | ~100 | 零认证 |
| 国际 | Discourse | ~60 | 需注册 |
| 国内 | 技术社区 | ~20 | 待激活 |
| 国际 | 其他 | ~34 | 待探索 |
