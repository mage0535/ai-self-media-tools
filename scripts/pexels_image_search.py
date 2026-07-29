#!/usr/bin/env python3
"""Pexels 图片搜索 — 根据关键词获取内容相关配图."""
import json, urllib.request, os

API_KEY = os.environ.get("PEXELS_API_KEY", "")
if not API_KEY:
    # 从配置文件读取
    env_file = os.path.expanduser("~/.ai-self-media-tools/secrets/channel_matrix.env")
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("PEXELS_API_KEY"):
                API_KEY = line.split("=", 1)[1].strip().strip("'\"")

BASE_URL = "https://api.pexels.com/v1/search"


def search_images(query, count=3, min_width=800, min_height=400):
    """Search Pexels for images matching the query."""
    if not API_KEY:
        print("⚠️ PEXELS_API_KEY 未配置")
        return []
    
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}?query={encoded}&per_page={count}"
    
    req = urllib.request.Request(url, headers={
        "Authorization": API_KEY,
        "User-Agent": "HermesContentBot/1.0",
    })
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        photos = resp.get("photos", [])
        results = []
        for p in photos:
            src = p.get("src", {})
            medium = src.get("medium", "")
            original = src.get("original", "")
            alt = p.get("alt", "")
            photographer = p.get("photographer", "")
            results.append({
                "url": medium or original,
                "original_url": original,
                "alt": alt,
                "photographer": photographer,
                "width": p.get("width", 0),
                "height": p.get("height", 0),
            })
        return results
    except Exception as e:
        print(f"  ⚠️ Pexels搜索失败: {e}")
        return []


def get_images_for_article(topic, keywords=None):
    """根据文章话题和关键词返回配图列表."""
    all_keywords = keywords or []
    # 从话题中提取关键词
    topic_keywords = [w for w in topic.split() if len(w) > 1]
    all_keywords.extend(topic_keywords[:3])
    
    # 技术文章的默认关键词映射
    topic_mapping = {
        "n8n": ["automation", "workflow", "server", "technology"],
        "docker": ["server", "technology", "code", "container"],
        "python": ["code", "programming", "developer", "computer"],
        "ai": ["artificial intelligence", "technology", "robot", "digital"],
        "工具": ["tool", "workspace", "technology"],
        "自动化": ["automation", "robot", "factory", "machine"],
        "代码": ["code", "programming", "developer"],
        "部署": ["server", "technology", "network", "datacenter"],
    }
    
    # 合并关键词
    search_terms = []
    for kw in all_keywords:
        for key, terms in topic_mapping.items():
            if key.lower() in kw.lower():
                search_terms.extend(terms)
    
    if not search_terms:
        search_terms = ["technology", "workspace", "code"]
    
    # 搜索第一组关键词
    query = "+".join(search_terms[:3])
    return search_images(query, count=2)


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "n8n自动化工作流"
    print(f"🔍 搜索: {topic}")
    images = get_images_for_article(topic)
    for img in images:
        print(f"  📷 {img['alt'][:50]}")
        print(f"     {img['url']}")
