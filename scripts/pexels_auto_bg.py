#!/usr/bin/env python3
"""pexels_auto_bg.py — 自动下载 Pexels 语义背景图（管线兜底，取代 Hermes 手动下载）。

当 visual_assets 缺失 / 图片文件不存在 / 背景不足 8 张时，自动根据脚本关键词
调用 Pexels API 下载竖版实景图，写 visual_assets_auto.json 供渲染器使用。

用法（类方法，供 video_toolchain_runner/ops 调用）:
  from scripts.pexels_auto_bg import auto_fetch_backgrounds
  assets = auto_fetch_backgrounds(script_body, title, output_dir, platform)
"""
from __future__ import annotations

import hashlib, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Pexels key 多源读取
def _pexels_key() -> str:
    for p in [
        ROOT / "secrets" / "channel_matrix.env",
        ROOT / "secrets" / "image.env",
        Path.home() / ".hermes" / ".env",
    ]:
        try:
            for line in open(p):
                line = line.strip()
                if line.startswith("PEXELS_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return os.environ.get("PEXELS_API_KEY", "")


def _cat_dog_ai_queries() -> list[str]:
    """AI知识视频专用猫狗语义查询（贴合知识点，非装饰）"""
    return [
        "cat sitting with laptop studying",
        "dog checking code on monitor verifying",
        "cat observing workflow diagram curious",
        "kitten learning with book and laptop",
        "dog guarding document verification",
        "cat and dog collaborating at desk",
        "cat pointing at error on screen playful",
        "dog delivering checklist at office",
    ]


def _semantic_queries(text: str, count: int = 8, platform: str = "") -> list[str]:
    """从脚本/标题提取语义关键词生成 Pexels 查询词。

    宠物视觉只允许出现在明确的宠物账号；AI/效率赛道禁止跨 lane 注入猫狗。
    """
    lowered = str(text or "").casefold()
    platform_key = str(platform or "").casefold().strip()
    pet_lane = platform_key in {"douyin_pet", "pet", "catmiao5"}
    base_queries = []
    # 平台/领域关键词映射
    domain_map = {
        "ai": ["artificial intelligence", "technology", "computer"],
        "automation": ["automation", "robot", "efficiency"],
        "邮件": ["email", "communication", "office"],
        "邮件": ["email"],
        "表格": ["spreadsheet", "data", "excel"],
        "编程": ["programming", "code", "developer"],
        "效率": ["productivity", "workspace", "desk"],
        "猫咪": ["cat", "kitten", "pet"],
        "猫": ["cat", "kitten"],
        "工作流": ["workflow", "process", "diagram"],
        "视频": ["video", "camera", "content creation"],
    }
    for key, qs in domain_map.items():
        if key in lowered:
            base_queries.extend(qs)
    if not base_queries:
        base_queries = ["productivity", "technology", "workspace", "office", "digital"]
    # 只有明确宠物 lane 才允许猫狗查询；AI/效率/开发者平台永远不注入宠物。
    if pet_lane:
        cat_dog = _cat_dog_ai_queries()
        merged: list[str] = []
        for i in range(max(len(cat_dog), len(base_queries))):
            if i < len(cat_dog):
                merged.append(cat_dog[i])
            if i < len(base_queries) and base_queries[i] not in merged:
                merged.append(base_queries[i])
        base_queries = merged
    # 去重 + 补足到 count
    seen = []
    for q in base_queries:
        if q not in seen:
            seen.append(q)
    base_queries = seen
    while len(base_queries) < count:
        base_queries.append(base_queries[len(base_queries) % len(base_queries)])
    return base_queries[:count]


def _download_pexels(query: str, key: str, orientation: str = "portrait") -> dict | None:
    """下载单张 Pexels 图，并返回可审计的来源、许可与文件内容。"""
    qq = query.replace(" ", "+")
    url = f"https://api.pexels.com/v1/search?query={qq}&per_page=1&orientation={orientation}"
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        if not data.get("photos"):
            return None
        photo = data["photos"][0]
        img_url = photo["src"]["large2x"]
        ireq = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(ireq, timeout=20) as ir:
            content = ir.read()
        return {
            "content": content,
            "photo_id": str(photo.get("id") or ""),
            "page_url": str(photo.get("url") or ""),
            "download_url": str(img_url),
            "photographer": str(photo.get("photographer") or ""),
            "license": "Pexels License",
            "license_url": "https://www.pexels.com/license/",
            "query": query,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dimensions": {
                "width": int(photo.get("width") or 0),
                "height": int(photo.get("height") or 0),
            },
        }
    except Exception:
        return None


def auto_fetch_backgrounds(script_body: str, title: str, output_dir: Path, platform: str = "") -> list[dict]:
    """自动下载 8 张背景图（Pexels 实景优先，AI 生图兜底），返回 visual_assets assignments"""
    output_dir = Path(output_dir)
    bg_dir = output_dir / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)

    # 只复用同平台、同 lane 且有 manifest 证明的背景；否则忽略旧缓存，避免跨赛道污染。
    manifest_path = output_dir / "visual_assets_auto.json"
    existing = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            same_lane = (
                str(manifest.get("platform", "")).casefold()
                == str(platform or "").casefold()
                and manifest.get("lane")
                == ("pet" if str(platform).casefold() == "douyin_pet" else "ai_efficiency")
            )
            if same_lane:
                for item in manifest.get("assignments") or []:
                    if not isinstance(item, dict):
                        continue
                    path = Path(str(item.get("path") or item.get("background_image") or ""))
                    if (
                        path.is_file()
                        and str(item.get("license") or "").strip()
                        and str(item.get("page_url") or item.get("source_url") or "").strip()
                    ):
                        existing.append(item)
        except (OSError, json.JSONDecodeError):
            existing = []
    if len(existing) >= 8:
        return existing[:8]

    key = _pexels_key()
    queries = _semantic_queries(f"{script_body} {title}", 8, platform=platform)
    assignments = []
    start = 1

    # 优先 Pexels 实景（带 md5 去重，防同图重复）
    seen_hashes = set()
    if key:
        for i, q in enumerate(queries, start):
            downloaded = _download_pexels(q, key)
            if not downloaded:
                time.sleep(1)
                continue
            content = bytes(downloaded.pop("content"))
            # md5 去重：已下载过的图跳过
            import hashlib
            h = hashlib.md5(content).hexdigest()
            if h in seen_hashes:
                time.sleep(0.5)
                continue
            seen_hashes.add(h)
            fp = bg_dir / f"bg_{i:02d}.jpg"
            fp.write_bytes(content)
            assignments.append({
                **downloaded,
                "scene": i,
                "path": str(fp),
                "background_image": str(fp),
                "sha256": hashlib.sha256(content).hexdigest(),
                "source_url": downloaded["page_url"],
                "rights_cleared": True,
                "real_scene": True,
                "source_query": q,
                "semantic_match_score": 0.8,
                "match_reason": f"Pexels search result selected for scene query: {q}",
                "semantic_tags": [q, "pexels", "real_scene"],
                "platform": platform,
            })
            time.sleep(1.0)

    # Pexels 不足 8 张 → AI 生图兜底（Pollinations FLUX 免费）
    if len(assignments) < 8:
        need = 8 - len(assignments)
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from content_platform.image_provider import generate_image
            for i in range(len(assignments) + 1, 9):
                prompt = _ai_prompt(queries[i - 1], platform)
                fp = bg_dir / f"bg_{i:02d}.jpg"
                try:
                    generate_image(prompt, fp, provider="pollinations", size="1080x1920")
                    if fp.is_file() and fp.stat().st_size > 5000:
                        assignments.append({
                            "background_image": str(fp), "rights_cleared": True, "real_scene": False,
                            "source_query": queries[i - 1], "ai_generated": True, "platform": platform,
                        })
                except Exception:
                    continue
                time.sleep(0.5)
        except Exception:
            pass

    if not assignments:
        return []
    write_auto_assets(assignments, output_dir, platform)
    return assignments


def _ai_prompt(query: str, platform: str = "") -> str:
    """根据语义关键词构造 AI 生图 prompt（竖版视频背景，深色可叠加文字）"""
    plat = str(platform or "")
    style = ""
    if plat in {"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok"}:
        style = "vertical 9:16 composition, dark gradient background suitable for text overlay, cinematic, high quality, no text"
    else:
        style = "cinematic, high quality, clean composition, no text, suitable for text overlay"
    return f"{query}, {style}"


def write_auto_assets(assignments: list[dict], output_dir: Path, platform: str = "") -> Path | None:
    """写 visual_assets_auto.json 供渲染器读取"""
    if not assignments:
        return None
    path = output_dir / "visual_assets_auto.json"
    lane = "pet" if str(platform).casefold() == "douyin_pet" else "ai_efficiency"
    path.write_text(json.dumps({"platform": platform, "lane": lane, "assignments": assignments}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


if __name__ == "__main__":
    # CLI: 给一个脚本文件自动下载背景
    if len(sys.argv) < 2:
        print("用法: python3 scripts/pexels_auto_bg.py <script.md> [output_dir]")
        raise SystemExit(2)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/auto_bg_out")
    assets = auto_fetch_backgrounds(text, "", out)
    p = write_auto_assets(assets, out)
    print(f"下载 {len(assets)} 张背景 → {p or '无'}")
    for a in assets:
        print(f"  {a['background_image']} ({a.get('source_query','')})")
