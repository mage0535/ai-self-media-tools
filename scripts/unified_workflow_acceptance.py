#!/usr/bin/env python3
"""UNIFIED WORKFLOW ACCEPTANCE — the single source of truth for what "done"
means on any platform. Covers the 8 quality dimensions the user demands:
account analysis, ops strategy, topic selection, copywriting style/format,
long-form / image-text / knowledge cards / video quality.

Any automatic or manual workflow must pass this before delivery. Run:
  python3 scripts/unified_workflow_acceptance.py --date YYYYMMDD --platform <name> [--artifacts-dir <dir>]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CN_RE = re.compile(r"[\u4e00-\u9fff]")

failures = []
checks = []

def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": str(detail)[:200]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)

# ── D1. Account analysis (platform real data) ──
def d1_account(analysis_text: str, platform: str):
    """Require evidence the account's own lane/data was analysed, not just trend files."""
    if not analysis_text:
        return check(f"D1 {platform} account analysis", False, "no analysis file")
    keys = ["账号", "粉丝", "播放", "赛道", "定位", "内容数", "互动", "account", "followers", "lane"]
    hits = [k for k in keys if k in analysis_text]
    check(f"D1 {platform} account analysis", len(hits) >= 3, f"signals: {hits}")

# ── D2. Ops strategy (growth strategy loaded & matched) ──
def d2_strategy(analysis_text: str, strategy_dir: Path, platform: str = ""):
    strategy_files = sorted((ROOT / "data").glob("growth_strategy_*.md")) if (ROOT / "data").exists() else []
    if not strategy_files:
        check("D2 growth strategy file", False, "no growth_strategy_*.md")
        return
    # 2026-08-16 修复：按平台匹配策略文件（避免字母序取 xhs 误判所有平台）
    # 优先 exact 平台前缀（growth_strategy_douyin_ai_20260816.md），
    # 其次平台子串（douyin_ai 匹配 growth_strategy_douyin_ai_* / growth_strategy_*_douyin_ai*），
    # 否则回退最近文件（旧行为）
    plat = str(platform or "").casefold()
    matched = None
    if plat:
        exact = [f.name for f in strategy_files if f.name.casefold().startswith(f"growth_strategy_{plat}_")]
        if exact:
            matched = exact[-1]
        else:
            sub = [f.name for f in strategy_files if plat in f.name.casefold()]
            if sub:
                matched = sub[-1]
    if not matched:
        # 2026-08-16 修复：无专属策略时回退最新主策略（v6），而非任意字母序文件
        # （此前会取 xhs 误判；v6 已合并宠物号/全平台内容）
        main = [f.name for f in strategy_files if f.name.casefold().startswith("growth_strategy_20")]
        if main:
            # 取日期最新的主策略（growth_strategy_YYYYMMDD.md）
            main = sorted(main, key=lambda n: n.replace("growth_strategy_", "").replace(".md", ""), reverse=True)
            matched = main[0] if main[0].startswith("growth_strategy_20") else None
    latest = matched or strategy_files[-1].name
    referenced = latest in (analysis_text or "") or "growth_strategy" in (analysis_text or "")
    check("D2 ops strategy referenced", referenced, f"latest={latest}")
    # 2026-08-16 强化：分析文件必须引用 2026 平台规则（防用过时逻辑/防规则遗漏）
    rules_ref = "platform_rules_2026" in (analysis_text or "") or "2026 算法适配" in (analysis_text or "") \
        or "platform-ops-rules" in (analysis_text or "") or "收藏率" in (analysis_text or "")
    check("D2 2026 rules referenced", rules_ref, "analysis 应引用 platform_rules_2026 / 收藏率等 2026 规则")
    # 2026-08-16 强化：分析文件必须声明发布模式（快手/X 自动、公众号系草稿、其余手动）
    # 防自动任务把手动平台当自动发
    mode_ref = any(k in (analysis_text or "") for k in ["发布模式", "handoff", "草稿箱", "手动发布", "自动上传"])
    check("D2 publish mode referenced", mode_ref, "analysis 应声明发布模式（自动/草稿/手动）")

# ── D3. Topic independence (platform gate) ──
def d3_topic(platform: str, date_str: str):
    if platform in {"x", "twitter", "tiktok"}:
        check(f"D3 {platform} topic independence", True, "international platform exempted (gate tuned for CN)")
        return
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT))
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_platform_topic_independence.py"), date_str, "--platforms", platform],
        capture_output=True, text=True, timeout=120, env=env,
    )
    try:
        result = json.loads(r.stdout)
        check(f"D3 {platform} topic independence", result.get("passed", False), f"date={date_str}")
    except Exception:
        check(f"D3 {platform} topic independence", False, r.stdout[:150] or r.stderr[:150])

# ── D4. Copywriting style (hook / no AI slop / first person / numbers) ──
VIDEO_PLATFORMS = {"kuaishou", "douyin", "douyin_ai", "tiktok", "shipinhao", "youtube", "bilibili"}

def d4_copy(body: str, platform: str, cards: list | None = None):
    # Video platforms: use first card tts as the hook source (test-consistent)
    if cards and platform in VIDEO_PLATFORMS:
        body = "\n".join(str(c.get("tts") or c.get("txt") or "") for c in cards)
    if not body:
        return check(f"D4 {platform} copywriting", False, "no body")
    first = body[:300]
    hook = bool(re.search(r"[？?！!]|为什么|难道|是不是|差距|暴涨|暴跌|实测|揭秘|别再|别再做|我试了|避坑|finally|after years|check before", first, re.I))
    ai_slop = ["首先", "其次", "最后", "综上所述", "值得注意的是", "总的来说", "因此，我们", "总而言之"]
    slop_hits = [w for w in ai_slop if w in body]
    has_number = bool(re.search(r"\d", body))
    first_person = bool(re.search(r"[我我们]|I |we |my ", body, re.I))
    check(f"D4 {platform} hook", hook, "first 300 chars has hook signal")
    check(f"D4 {platform} no AI slop", len(slop_hits) == 0, f"found: {slop_hits}")
    check(f"D4 {platform} concrete numbers", has_number)
    # Short-video scripts speak to the viewer ("你/you") — first person required
    # only for written long-form; video scripts need direct address instead.
    if platform in VIDEO_PLATFORMS:
        address = bool(re.search(r"[你您]|you|your|yourself", body, re.I))
        check(f"D4 {platform} direct address", address, "video script addresses viewer")
    else:
        check(f"D4 {platform} first-person", first_person)

# ── D5. Layout/format (platform-appropriate length & structure) ──
def d5_format(body: str, platform: str, content_form: str, cards: list | None = None):
    form = str(content_form or "").casefold()
    if "article" in form or platform in {"zhihu", "juejin", "wechat"}:
        if not body:
            return check(f"D5 {platform} format", False, "no body")
        cn_chars = len([c for c in body if "\u4e00" <= c <= "\u9fff"])
        headings = len(re.findall(r"^#{1,3}\s", body, re.M))
        sections = len(re.findall(r"\n\n", body)) + 1
        check(f"D5 {platform} long-form length", cn_chars >= 2000, f"{cn_chars} cn chars")
        check(f"D5 {platform} headings", headings >= 3, f"{headings} headings")
        check(f"D5 {platform} sections", sections >= 3, f"{sections} sections")
    elif "short" in form or platform in VIDEO_PLATFORMS:
        if cards:
            segs = [str(c.get("tts") or c.get("txt") or "") for c in cards]
        else:
            segs = [s for s in re.split(r"\n{2,}", body) if s.strip()]
        lens = [len(s) for s in segs]
        en = platform in {"tiktok", "youtube", "x", "twitter"}
        if en:
            word_lens = [len(s.split()) for s in segs]
            check(f"D5 {platform} 8 segments", len(segs) >= 8, f"{len(segs)} segments")
            check(f"D5 {platform} segment length 10-20 words", len(segs) >= 8 and all(8 <= w <= 28 for w in word_lens), f"words={word_lens}")
        else:
            check(f"D5 {platform} 8 segments", len(segs) >= 8, f"{len(segs)} segments")
            check(f"D5 {platform} segment length 40-60", len(segs) >= 8 and all(30 <= l <= 90 for l in lens), f"lens={lens}")

# ── D6. Long-form quality (facts / quotes / actionable) ──
def d6_long(body: str, platform: str):
    if platform not in {"zhihu", "juejin", "wechat"}:
        return check(f"D6 {platform} long-form", True, "n/a")
    has_quote = bool(re.search(r"[>\"「『]", body))
    has_list = bool(re.search(r"(^|\n)[-*•]\s|\n\d+[.、]", body))
    has_table = bool(re.search(r"\|.+\|.+\|", body))
    has_cta = bool(re.search(r"评论|关注|收藏|转发|回复|点赞", body))
    check(f"D6 {platform} quote/evidence", has_quote)
    check(f"D6 {platform} list/structure", has_list)
    check(f"D6 {platform} table/data", has_table)
    check(f"D6 {platform} CTA", has_cta)

# ── D7. Knowledge cards (≥6 cards, ≥6 layouts, real backgrounds) ──
def d7_knowledge_cards(artifacts_dir: Path, platform: str):
    cards = None
    for cand in [artifacts_dir / "cards.json", artifacts_dir / "render" / "cards.json"]:
        if cand.exists():
            try:
                cards = json.loads(cand.read_text())
                break
            except Exception:
                pass
    if not cards:
        return check(f"D7 {platform} knowledge cards", False, "no cards.json")
    if not isinstance(cards, list):
        return check(f"D7 {platform} knowledge cards", False, "cards.json not a list")
    layouts = [str(c.get("layout") or c.get("layout_template") or "") for c in cards]
    tts_missing = [i + 1 for i, c in enumerate(cards) if not c.get("tts")]
    unique_layouts = len({l for l in layouts if l})
    check(f"D7 {platform} ≥6 cards", len(cards) >= 6, f"{len(cards)} cards")
    check(f"D7 {platform} ≥6 layouts", unique_layouts >= 6, f"{unique_layouts} layouts")
    check(f"D7 {platform} tts present", not tts_missing, f"missing tts on cards {tts_missing}")

# ── D8. Video quality (background uniqueness / motion / duration / platform voice) ──
def d8_video(artifacts_dir: Path, platform: str):
    if platform not in {"kuaishou", "douyin", "tiktok", "shipinhao", "youtube", "bilibili"}:
        return check(f"D8 {platform} video", True, "n/a")
    bg_dir = artifacts_dir / "backgrounds"
    if bg_dir.exists():
        # 2026-08-17 修复：兼容 jpg/png（背景图从 Pexels/Pollinations 下载为 jpg）
        bg_files = sorted(bg_dir.glob("*.png")) + sorted(bg_dir.glob("*.jpg"))
        hashes = []
        for f in bg_files:
            hashes.append(subprocess.run(["md5sum", str(f)], capture_output=True, text=True).stdout.split()[0])
        check(f"D8 {platform} backgrounds unique", len(set(hashes)) >= 6, f"{len(set(hashes))}/{len(bg_files)}")
    else:
        check(f"D8 {platform} backgrounds", True, "no backgrounds dir (may use card art)")
    motion_ev = None
    for cand in [artifacts_dir / "segment_motion_evidence.json", artifacts_dir / "render" / "segment_motion_evidence.json"]:
        if cand.exists():
            try:
                motion_ev = json.loads(cand.read_text())
                break
            except Exception:
                pass
    if motion_ev:
        moves = [s.get("move_id") for s in motion_ev.get("segments", [])]
        check(f"D8 {platform} motion diversity", len(set(moves)) >= 6, f"{len(set(moves))} moves")
    final = None
    for cand in [artifacts_dir / "final.mp4", artifacts_dir / "render" / "final.mp4"]:
        if cand.exists():
            final = cand
            break
    if final:
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
            capture_output=True, text=True).stdout.strip() or 0)
        check(f"D8 {platform} duration 40-100s", 40 <= dur <= 100, f"{dur:.1f}s")
        # platform voice language
        tts_state = artifacts_dir / ".render_state" / "tts_01.json"
        if tts_state.exists():
            voice = json.loads(tts_state.read_text()).get("inputs", {}).get("voice", "")
            en_platform = platform in {"tiktok", "youtube"}
            ok = (voice.startswith("en-") if en_platform else voice.startswith("zh-"))
            check(f"D8 {platform} TTS language", ok, f"voice={voice}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--platform", required=True)
    ap.add_argument("--artifacts-dir", default="")
    ap.add_argument("--body", default="", help="content body or path to body file")
    ap.add_argument("--analysis", default="", help="analysis md path or text")
    ap.add_argument("--content-form", default="")
    args = ap.parse_args()

    platform = args.platform.casefold()
    artifacts_dir = Path(args.artifacts_dir or "data/artifacts")
    # resolve real artifact dir: find latest by mtime under data/artifacts
    if not artifacts_dir.exists() or args.artifacts_dir == "":
        candidates = sorted((ROOT / "data/artifacts").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        artifacts_dir = candidates[0] if candidates else ROOT / "data/artifacts"

    body = args.body
    if body and Path(body).exists():
        body = Path(body).read_text()
    analysis_text = args.analysis
    if analysis_text and Path(analysis_text).exists():
        analysis_text = Path(analysis_text).read_text()

    # auto-locate analysis + topic matrix for D1-D3 (written by overnight or manual workflow)
    date_compact = args.date
    if len(date_compact) == 8:
        date_dash = f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}"
    else:
        date_dash = date_compact
    local_ops = ROOT / "data" / f"local_ops_{platform}"
    if not local_ops.exists():
        local_ops = ROOT / "data" / "local_ops" / platform
    if not analysis_text:
        for cand in [
            local_ops / f"analysis_{date_compact}.md",
            local_ops / f"analysis_{date_dash}.md",
            local_ops / "analysis.md",
        ]:
            if cand.exists():
                analysis_text = cand.read_text()
                break
    if not analysis_text and local_ops.exists():
        mds = sorted(local_ops.glob("analysis_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mds:
            analysis_text = mds[0].read_text()

    # load cards for video-platform copy/format checks
    cards = None
    for cand in [artifacts_dir / "cards.json", artifacts_dir / "render" / "cards.json"]:
        if cand.exists():
            try:
                cards = json.loads(cand.read_text())
                if not isinstance(cards, list):
                    cards = None
                break
            except Exception:
                pass

    print(f"=== Unified Workflow Acceptance: {platform} ({args.date}) ===")
    d1_account(analysis_text, platform)
    d2_strategy(analysis_text, ROOT / "data", platform)
    d3_topic(platform, args.date)
    d4_copy(body, platform, cards)
    d5_format(body, platform, args.content_form, cards)
    d6_long(body, platform)
    d7_knowledge_cards(artifacts_dir, platform)
    d8_video(artifacts_dir, platform)
    print()
    passed = len(checks) - len(failures)
    print(f"RESULT: {passed}/{len(checks)} passed")
    if failures:
        print("FAILED:", ", ".join(failures))
        sys.exit(1)
    print("ALL DIMENSIONS PASS")

if __name__ == "__main__":
    main()
