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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VISION_CIRCUIT_REASON = ""

# Pexels key 多源读取
def _pexels_key() -> str:
    from content_platform.image_provider import load_secret

    return load_secret("PEXELS_API_KEY")


def _semantic_queries(text: str, count: int = 8) -> list[str]:
    """从脚本/标题提取语义关键词生成 Pexels 查询词"""
    lowered = str(text or "").casefold()
    beats = [part.strip().casefold() for part in __import__("re").split(r"\n\s*\n|(?<=[。！？!?])\s*", str(text or "")) if part.strip()]
    beat_queries = []
    for beat in beats:
        query = _query_for_beat(beat)
        if query and query not in beat_queries:
            beat_queries.append(query)
        if len(beat_queries) >= count:
            return beat_queries[:count]
    base_queries = list(beat_queries)
    # 平台/领域关键词映射
    domain_map = {
        "ai": ["artificial intelligence creative workstation", "person using AI software laptop", "human reviewing AI assistant output"],
        "automation": ["digital workflow automation team", "human checking automated process", "connected task workflow screen"],
        "邮件": ["professional email communication laptop", "person sorting email inbox"],
        "表格": ["analyst reviewing spreadsheet data", "organized data table workstation"],
        "编程": ["software developer coding laptop", "programmer reviewing code screen"],
        "效率": ["focused productive creative workspace", "organized desk single laptop", "person completing task checklist"],
        "猫咪": ["playful kitten home office", "curious cat beside laptop"],
        "猫": ["playful cat home office", "curious cat beside laptop"],
        "工作流": ["digital workflow process diagram", "team following task process", "connected workflow steps screen"],
        "视频": ["video editor camera workstation", "content creator editing footage"],
    }
    for key, qs in domain_map.items():
        if key in lowered:
            base_queries.extend(qs)
    if not base_queries:
        base_queries = ["productivity", "technology", "workspace", "office", "digital"]
    # 去重 + 补足到 count
    seen = []
    for q in base_queries:
        if q not in seen:
            seen.append(q)
    base_queries = seen
    seeds = list(base_queries)
    variants = ["portrait closeup", "workspace wide shot", "hands at work", "screen detail"]
    while len(base_queries) < count:
        seed = seeds[len(base_queries) % len(seeds)]
        candidate = f"{seed} {variants[(len(base_queries) // len(seeds)) % len(variants)]}"
        if candidate not in base_queries:
            base_queries.append(candidate)
    return base_queries[:count]


def _query_for_beat(beat: str) -> str:
    rules = [
        (("claude", "search box", "chat interface"), "person using AI chat interface laptop"),
        (("goal", "audience", "constraints"), "person writing project brief on laptop"),
        (("compare choices", "inspect the result", "review pass"), "person reviewing AI assistant output laptop"),
        (("project files", "verify the final", "workflow output"), "developer reviewing project files checklist"),
        (("工具越来越多", "装得越多", "工具太多", "too many tools"), "overwhelmed creator multiple computer screens"),
        (("资料散", "注意力", "切得稀碎", "来回切换", "switching"), "overwhelmed worker switching multiple screens"),
        (("做减法", "重复的工具", "只留一个"), "person organizing apps single laptop"),
        (("明确分工", "写初稿", "查资料", "做图"), "content creator planning tasks workstation"),
        (("固定的工作流", "固定工作流", "每一步对应"), "team following documented workflow steps"),
        (("别再装", "别装新工具", "反复用熟"), "focused worker using single laptop"),
        (("主力入口", "一个入口"), "organized workspace one central computer"),
        (("复盘", "实际产出", "决定保留"), "person reviewing completed task checklist"),
        (("api", "接口", "控制台", "dashboard", "developer"), "software developer API dashboard laptop"),
        (("文案", "文本", "图片", "图像", "语音", "content creator"), "content creator editing workstation"),
        (("工作流", "workflow", "automation", "自动化"), "digital workflow automation team"),
        (("视频", "剪辑", "camera"), "video editor camera workstation"),
        (("效率", "productivity", "省时间"), "focused productive creative workspace"),
        (("团队", "协作", "team"), "creative team collaboration office"),
        (("ai", "人工智能", "robot"), "artificial intelligence technology interface"),
    ]
    for tokens, query in rules:
        if any(token in beat for token in tokens):
            return query
    return "modern digital workspace"


def _download_pexels(
    query: str,
    key: str,
    orientation: str = "portrait",
    exclude_ids: set[str] | None = None,
    exclude_hashes: set[str] | None = None,
) -> dict | None:
    """Download one Pexels photo with source and license evidence."""
    qq = query.replace(" ", "+")
    url = f"https://api.pexels.com/v1/search?query={qq}&per_page=80&orientation={orientation}"
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        if not data.get("photos"):
            return None
        excluded = set(exclude_ids or set())
        for photo in data["photos"]:
            asset_id = str(photo.get("id") or "")
            if not asset_id or asset_id in excluded:
                continue
            img_url = photo["src"]["large2x"]
            ireq = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(ireq, timeout=20) as ir:
                content = ir.read()
            if hashlib.sha256(content).hexdigest() in set(exclude_hashes or set()):
                excluded.add(asset_id)
                continue
            return {
                "content": content,
                "source_url": str(photo.get("url") or ""),
                "alt": str(photo.get("alt") or ""),
                "artist": str(photo.get("photographer") or ""),
                "artist_url": str(photo.get("photographer_url") or ""),
                "asset_id": asset_id,
            }
        return None
    except Exception:
        return None


def auto_fetch_backgrounds(
    script_body: str,
    title: str,
    output_dir: Path,
    platform: str = "",
    *,
    force: bool = False,
    excluded_hashes: set[str] | None = None,
    semantic_required: bool = False,
) -> list[dict]:
    """自动下载 8 张背景图（Pexels 实景优先，AI 生图兜底），返回 visual_assets assignments"""
    output_dir = Path(output_dir)
    bg_dir = output_dir / "backgrounds"
    bg_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否已有足够背景
    existing = sorted(bg_dir.glob("bg_*.*"))
    if len(existing) >= 8 and not force and not semantic_required:
        # 已有 8 张，返回现有
        return [{"background_image": str(p), "rights_cleared": True, "real_scene": True} for p in existing[:8]]

    key = _pexels_key()
    queries = _semantic_queries(f"{script_body} {title}", 8)
    assignments = []
    attempt_evidence = []
    base_existing = [] if force else existing
    needed = max(0, 8 - len(base_existing))

    # 优先 Pexels 实景（带 md5 去重，防同图重复）
    seen_hashes = set(excluded_hashes or set())
    seen_hashes.update(hashlib.sha256(path.read_bytes()).hexdigest() for path in base_existing if path.is_file())
    seen_ids: set[str] = set()
    accepted_queries: set[str] = set()
    orientation = "landscape" if str(platform or "").casefold() in {"youtube", "bilibili"} else "portrait"
    if key:
        for _round in range(3):
            for q in queries:
                # Preserve query diversity for the first two passes. If the
                # remaining queries still cannot satisfy semantic review, the
                # final pass may select another unique asset for a query that
                # already worked instead of leaving the scene pool incomplete.
                if q in accepted_queries and _round < 2:
                    continue
                if len(assignments) >= needed:
                    break
                photo = _download_pexels(
                    q,
                    key,
                    orientation=orientation,
                    exclude_ids=seen_ids,
                    exclude_hashes=seen_hashes,
                )
                if not photo:
                    attempt_evidence.append({"provider": "pexels", "query": q, "status": "no_candidate"})
                    time.sleep(1)
                    continue
                content = bytes(photo["content"])
                h = hashlib.sha256(content).hexdigest()
                seen_ids.add(photo["asset_id"])
                if h in seen_hashes:
                    time.sleep(0.5)
                    continue
                seen_hashes.add(h)
                i = len(base_existing) + len(assignments) + 1
                fp = _next_background_path(bg_dir)
                fp.write_bytes(content)
                semantic = _semantic_evidence(fp, [q], platform, source=photo) if semantic_required else {}
                if semantic_required and not semantic.get("passed"):
                    attempt_evidence.append({"provider": "pexels", "query": q, "status": "semantic_rejected"})
                    fp.unlink(missing_ok=True)
                    continue
                assignments.append({
                    "background_image": str(fp), "rights_cleared": True, "real_scene": True, "source_query": q,
                    "source_url": photo["source_url"], "license": "Pexels Content License",
                    "semantic_match_score": float(semantic.get("semantic_match_score") or (0.8 if not semantic_required else 0)),
                    "match_reason": str(semantic.get("caption") or f"Pexels portrait search matched: {q}"),
                    "semantic_tags": list(semantic.get("labels") or [q, "photo", "portrait"]),
                    "semantic_required": semantic_required, "semantic_evidence": semantic,
                    "generation_evidence": {}, "artist": photo["artist"], "artist_url": photo["artist_url"],
                    "asset_id": photo["asset_id"],
                })
                accepted_queries.add(q)
                attempt_evidence.append({"provider": "pexels", "query": q, "status": "accepted"})
                time.sleep(1.0)
            if len(assignments) >= needed:
                break

    # Pexels 不足 8 张 → AI 生图兜底（Pollinations FLUX 免费）
    if len(assignments) < needed:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from content_platform.image_provider import generate_image
            attempts = 0
            while len(assignments) < needed and attempts < max(3, needed * 3):
                attempts += 1
                i = len(base_existing) + len(assignments) + 1
                # Advance on every attempt, not only after acceptance. A rejected
                # first candidate must not consume the entire recovery budget.
                query = queries[(attempts - 1) % len(queries)]
                prompt = _ai_prompt(query, platform) + f", distinct scene {i}, composition variant {i}, candidate attempt {attempts}"
                fp = _next_background_path(bg_dir)
                try:
                    generated = generate_image(
                        prompt,
                        fp,
                        provider="auto",
                        size="1080x1920",
                        # Stock was already exhausted above. Start with the fast
                        # generated chain rather than repeating the same search.
                        intent="fast_fallback",
                    )
                    if fp.is_file() and fp.stat().st_size > 5000:
                        image_hash = hashlib.sha256(fp.read_bytes()).hexdigest()
                        if image_hash in seen_hashes:
                            fp.unlink(missing_ok=True)
                            continue
                        semantic = _semantic_evidence(fp, [query], platform) if semantic_required else {}
                        if semantic_required and not semantic.get("passed"):
                            attempt_evidence.append({"provider": str(generated.get("provider") or "auto"), "query": query, "status": "semantic_rejected"})
                            fp.unlink(missing_ok=True)
                            continue
                        seen_hashes.add(image_hash)
                        assignments.append({
                            "background_image": str(fp), "rights_cleared": True, "real_scene": False,
                            "source_query": query, "ai_generated": True,
                            "source_url": str(generated.get("source_url") or f"generated:{generated.get('provider') or 'auto'}"),
                            "license": str(generated.get("license") or "generated_for_project"),
                            "semantic_match_score": float(semantic.get("semantic_match_score") or (0.8 if not semantic_required else 0)),
                            "match_reason": str(semantic.get("caption") or f"generated image matched: {query}"),
                            "semantic_tags": list(semantic.get("labels") or [query, "generated", "vertical"]),
                            "semantic_required": semantic_required, "semantic_evidence": semantic,
                            "generation_evidence": {
                                "provider": str(generated.get("provider") or "auto"),
                                "model": str(generated.get("model") or ""),
                                "prompt": prompt,
                                "provenance": dict(generated.get("provenance") or {}),
                            },
                        })
                        attempt_evidence.append({"provider": str(generated.get("provider") or "auto"), "query": query, "status": "accepted"})
                except Exception as exc:
                    attempt_evidence.append({"provider": "auto", "query": query, "status": "failed", "error_type": type(exc).__name__})
                    fp.unlink(missing_ok=True)
                    continue
                time.sleep(0.5)
        except Exception as exc:
            attempt_evidence.append({"provider": "auto", "query": "", "status": "setup_failed", "error_type": type(exc).__name__})

    evidence_path = output_dir / "asset_selection_attempts.json"
    temporary = evidence_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"version": "asset_selection_attempts_v1", "attempts": attempt_evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, evidence_path)
    if not assignments:
        return []
    return assignments


def _semantic_evidence(path: Path, expected: list[str], platform: str, source: dict | None = None) -> dict:
    global _VISION_CIRCUIT_REASON
    try:
        from scripts.image_semantic_analyze import analyze_image
    except ImportError:
        from image_semantic_analyze import analyze_image
    result = None
    if not _VISION_CIRCUIT_REASON:
        try:
            result = analyze_image(path, [item for item in expected if str(item).strip()], role="video_scene", platform=platform)
        except Exception as exc:
            result = {
                "version": "image_semantic_evidence_v1",
                "passed": False,
                "failure": "semantic_analyzer_failed",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                "semantic_match_score": 0.0,
            }
        error = str(result.get("error") or "").casefold()
        if result.get("failure") in {"semantic_analyzer_failed", "semantic_analyzer_unavailable"}:
            _VISION_CIRCUIT_REASON = (
                "provider_quota_exhausted"
                if "http 429" in error or "daily free allocation" in error
                else "semantic_analyzer_unavailable"
            )
    if isinstance(result, dict) and result.get("passed") is True:
        return result
    unavailable = not isinstance(result, dict) or result.get("failure") in {"semantic_analyzer_failed", "semantic_analyzer_unavailable"}
    if unavailable and isinstance(source, dict):
        fallback = _source_metadata_semantic_evidence(path, expected, source)
        if fallback.get("passed") is True:
            fallback["vision_fallback_reason"] = _VISION_CIRCUIT_REASON or str((result or {}).get("failure") or "unavailable")
            return fallback
    return result or {
            "version": "image_semantic_evidence_v1",
            "passed": False,
            "failure": "semantic_analyzer_failed",
            "error": _VISION_CIRCUIT_REASON or "semantic analyzer unavailable",
            "semantic_match_score": 0.0,
        }


def _source_metadata_semantic_evidence(path: Path, expected: list[str], source: dict) -> dict:
    """Build truthful stock-source evidence from Pexels' asset metadata."""
    from scripts.image_semantic_analyze import score_semantics

    caption = str(source.get("alt") or "").strip()
    source_url = str(source.get("source_url") or "").strip()
    asset_id = str(source.get("asset_id") or "").strip()
    host = (urllib.parse.urlparse(source_url).hostname or "").casefold()
    if not caption or not asset_id or host not in {"pexels.com", "www.pexels.com"}:
        return {"version": "image_semantic_evidence_v1", "passed": False, "failure": "source_metadata_incomplete", "semantic_match_score": 0.0}
    labels = list(dict.fromkeys(__import__("re").findall(r"[a-z0-9]+", caption.casefold())))[:32]
    score, matched = score_semantics(expected, caption, labels)
    threshold = 0.6
    return {
        "version": "image_semantic_evidence_v1",
        "analyzer": "pexels_alt_metadata",
        "provider": "pexels",
        "caption": caption,
        "labels": labels,
        "expected_concepts": list(expected),
        "matched_concepts": matched,
        "semantic_match_score": score,
        "threshold": threshold,
        "passed": score >= threshold,
        "image_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "score_source": "provider_caption_label_recall",
        "evidence_level": "source_verified",
        "source_url": source_url,
        "asset_id": asset_id,
    }


def _ai_prompt(query: str, platform: str = "") -> str:
    """根据语义关键词构造 AI 生图 prompt（竖版视频背景，深色可叠加文字）"""
    plat = str(platform or "")
    style = ""
    if plat in {"douyin", "douyin_ai", "douyin_pet", "kuaishou", "shipinhao", "tiktok"}:
        style = "vertical 9:16 composition, dark gradient background suitable for text overlay, cinematic, high quality, no text"
    else:
        style = "cinematic, high quality, clean composition, no text, suitable for text overlay"
    return f"{query}, {style}"


def _next_background_path(directory: Path, suffix: str = ".jpg") -> Path:
    """Return an unused numbered path without overwriting sparse recovery files."""
    for index in range(1, 1000):
        candidate = Path(directory) / f"bg_{index:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("background filename space exhausted")


def write_auto_assets(assignments: list[dict], output_dir: Path) -> Path | None:
    """写 visual_assets_auto.json 供渲染器读取"""
    if not assignments:
        return None
    path = output_dir / "visual_assets_auto.json"
    path.write_text(json.dumps({"assignments": assignments}, ensure_ascii=False, indent=1), encoding="utf-8")
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
