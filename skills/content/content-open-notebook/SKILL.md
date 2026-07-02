---
name: content-open-notebook
description: Open Notebook 素材消化 — 将 NotebokLM 式深度研究集成到内容管线
trigger_keywords: [open-notebook, 素材消化, deep research, 研究助手, 笔记分析]
category: content
---

# Open Notebook 素材消化模块

## 功能
将 Open Notebook (lfnovo/open-notebook, 33.7k⭐) 的深度研究能力集成到 ai-self-media-tools 内容管线：
- **素材消化**: URL/文本 → Notebook 创建 → 搜索分析 → 结构化摘要
- **多素材研究**: 同一主题的多个来源联合分析
- **管线集成**: `build_generation_context()` 中 `deep_research=True` 时自动调用

## 前提条件
Open Notebook 服务运行中（部署见 `scripts/open_notebook_integrator.py` 或 Docker Compose）
```bash
cd /root/.open-notebook && docker compose ps
# 应显示 open_notebook 和 surrealdb 两个容器运行中
```

## 用法

### CLI
```bash
# 健康检查
python3 -m scripts.open_notebook_integrator health

# 消化 URL 素材
python3 -m scripts.open_notebook_integrator digest \
  --url https://example.com/article \
  --title "文章标题" \
  --topic "主题标签"

# 消化文本内容
python3 -m scripts.open_notebook_integrator digest \
  --text "这里是要分析的内容..." \
  --topic "text-analysis"

# 多素材研究
python3 -m scripts.open_notebook_integrator research \
  --topic "AI Agents" \
  --urls "https://a.com" "https://b.com"
```

### Python API
```python
from scripts.open_notebook_integrator import digest_source, research_topic

# 消化 URL
result = digest_source(
    url="https://example.com/article",
    title="Article Title",
    topic="tech"
)

# 多素材研究
result = research_topic(
    topic="AI Agents",
    urls=["https://a.com", "https://b.com"],
    texts=["一些补充文本"]
)
```

### 管线集成（自动）
在 `content_platform/intelligence.py` 的 `build_generation_context()` 中：
```python
brief = {
    "deep_research": True,              # 启用深度研究
    "deep_research_urls": [...],         # 可选 URL 列表
    "deep_research_texts": [...],        # 可选文本列表
}
context = build_generation_context("主题", brief)
# context 中自动包含 open_notebook_research 字段
```

## API
Open Notebook REST API 在 `http://<open-notebook-host>`。

| 端点 | 方法 | 用途 |
|------|:----:|------|
| `/health` | GET | 健康检查 |
| `/api/notebooks` | POST | 创建 Notebook |
| `/api/sources` | POST | 添加素材 (multipart) |
| `/api/search` | POST | 全文/向量搜索 |
| `/api/search/ask` | POST | 提问（需配置 AI provider） |
| `/api/notes` | GET | 获取笔记 |

## 质量门
- 自动检测 Open Notebook 服务健康状态
- 非致命错误不阻断管线（graceful degradation）
- `ToolRegistry.probe()` 包含 `open_notebook` 探测项

## 依赖
- Python: `requests`
- 服务: Docker (lfnovo/open-notebook + SurrealDB)
- 不在 `requirements.txt` 中？（`requests` 是常见依赖，已在标准环境中）
