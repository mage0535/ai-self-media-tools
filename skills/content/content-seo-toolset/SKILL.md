---
name: content-seo-toolset
description: "SEO 工具集 — OpenSERP 实时 SERP 数据 (6引擎) + pyseoanalyzer 技术 SEO 爬虫 + GEO 检查清单 (KDD 2024/ICLR 2026)"
triggers:
  - SEO analysis, SERP research, keyword research, rank tracking
  - technical seo audit, site crawl, on-page analysis
  - content optimization, GEO, generative engine optimization
  - openserp, seo-analyze, pyseoanalyzer
  - SERP数据, SEO分析, 关键词研究, 搜索引擎优化
tools:
  - content-platform seo-search --query <q> [--engine duck|google|bing|baidu]
  - content-platform seo-analyze <url>
  - content-platform seo-geo-check <job_id>
---

## OpenAI SERP Data (OpenSERP)

VPS 自托管 Docker: `{{OPENSERP_HOST}}`, 无需 API key, 6 引擎

```bash
content-platform seo-search --query "AI 工具" --engine duck --limit 5
```

返回: 标题/URL/摘要 + People Also Ask + 相关搜索

## 技术 SEO (pyseoanalyzer)

```bash
content-platform seo-analyze https://example.com
```

返回: 标题/字数/链接数/技术警告列表

## GEO 7 项检查清单

每次内容发布前检查（KDD 2024 论文验证：可提升 AI 回答引用率 40%）:

1. ✅ 声明附数字（"60+ 渠道"替代"很多渠道"）
2. ✅ 声明带来源（附研究/报告来源）
3. ✅ FAQ 块在前段（AI 偏好问答格式）
4. ✅ 对比表（Markdown 表格，LLM 偏好）
5. ✅ 开头有摘要（前 100 字概述）
6. ✅ 结构化列表（- / * / 编号列表）
7. ✅ 引述数据（引用数字/统计）

```bash
content-platform seo-geo-check <job_id>
```
