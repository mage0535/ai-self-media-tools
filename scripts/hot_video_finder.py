#!/usr/bin/env python3
"""热门视频搜索器 — TikTok/抖音热门发现 + 去重过滤。"""
import json
import os
import random
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# 加载去重DB
sys.path.insert(0, str(Path(__file__).parent))
from source_dedup_db import SourceDedupDB

CN_PROXY = os.environ.get("CN_PROXY", "socks5://127.0.0.1:1080")

# TikTok 搜索关键词（AI/效率类）
TIKTOK_TREND_QUERIES = [
    "aitools", "productivity", "coding", "python",
    "automation", "aicode", "workflow", "techtok",
    "machinelearning", "developer", "freelancetips",
    "aitutorial", "nocode", "chatgpt", "copilot",
]

# 抖音搜索关键词
DOUYIN_HOT_QUERIES = [
    "AI工具", "效率神器", "Python", "代码技巧",
    "自动化办公", "AI编程", "工作流", "效率提升",
    "程序员", "开源项目", "AI教程", "黑科技",
]


def search_tiktok(query, limit=5):
    """搜索TikTok热门视频（通过第三方公开搜索接口）。"""
    results = []
    
    # 方法1: TikTok API 搜索（通过公开接口）
    # 使用 TikTok API endpoint
    encoded = urllib.request.quote(query)
    url = f"https://api.tikapi.io/search/video?keyword={encoded}&count={limit}"
    
    # 这是个示例接口，实际生产环境需要替换为真实 API
    # 先返回模拟搜索结果来测试管线
    results = [
        {"platform": "tiktok", "url": f"https://www.tiktok.com/@demo/video/{random.randint(1000000000000000000, 9999999999999999999)}",
         "title": f"Amazing {query} tip", "views": random.randint(10000, 500000)},
        {"platform": "tiktok", "url": f"https://www.tiktok.com/@demo/video/{random.randint(1000000000000000000, 9999999999999999999)}",
         "title": f"Learn {query} fast", "views": random.randint(5000, 100000)},
    ]
    
    return results


def search_douyin(query, limit=5):
    """搜索抖音热门视频（需要 CN 代理）。"""
    results = []
    
    # 同样先用模拟数据
    results = [
        {"platform": "douyin", "url": f"https://www.douyin.com/video/{random.randint(7000000000000000000, 7999999999999999999)}",
         "title": f"{query} 效率翻倍", "views": random.randint(10000, 500000)},
    ]
    
    return results


def find_hot_videos(platform="tiktok", keywords=None, limit=5):
    """发现热门视频，自动去重。"""
    db = SourceDedupDB()
    queries = keywords or (TIKTOK_TREND_QUERIES if platform == "tiktok" else DOUYIN_HOT_QUERIES)
    
    # 随机选几个关键词搜索
    selected = random.sample(queries, min(3, len(queries)))
    all_results = []
    
    for q in selected:
        if platform == "tiktok":
            results = search_tiktok(q, limit)
        else:
            results = search_douyin(q, limit)
        
        for r in results:
            if not db.is_duplicate(r["url"]):
                all_results.append(r)
    
    # 按热度排序
    all_results.sort(key=lambda x: x.get("views", 0), reverse=True)
    
    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["tiktok", "douyin"], default="tiktok")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    
    print(f"🔍 搜索 {args.platform} 热门视频...")
    videos = find_hot_videos(args.platform, limit=args.limit)
    
    db = SourceDedupDB()
    print(f"\n找到 {len(videos)} 个未搬运的视频：")
    for v in videos[:5]:
        print(f"  {v['title'][:40]:40s} 👁{v.get('views',0):>8}  {v['url'][:50]}")
    
    print(f"\n去重数据库累计: {db.count()} 条")
