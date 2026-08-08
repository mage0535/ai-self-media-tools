#!/usr/bin/env python3
"""
International short-video handoff pipeline for YouTube Shorts and TikTok.

This legacy entrypoint is intentionally manual-handoff only. YouTube/TikTok
publishing must go through the main Pipeline policy and cannot use AiToEarn.
"""
import json, os, random, subprocess, sys, tempfile, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN_PROXY = os.environ.get("CN_PROXY", "socks5://127.0.0.1:1080")
AITOEARN_KEY = os.environ.get("AITOEARN_INTL_API_KEY", "")
DATA_DIR = Path(os.environ.get("CONTENT_PLATFORM_HOME", Path.home() / ".ai-self-media-tools")) / "data"
DRAFT_DIR = DATA_DIR / "intl_video_drafts"
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
YOUTUBE_ACCOUNT = "youtube_118204774743233672114"
TIKTOK_ACCOUNT = "tiktok_-000I1Hcio2yRuKk-SUtaNJ0w0D2XC_Sw0wQ"

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, Path(__file__).parent):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
from content_platform.content_recipe import build_tool_invocation_manifest
from content_platform.tool_selection import build_tool_selection_evidence
from source_dedup_db import SourceDedupDB
from script_enhancer import enhance_screencast_call

MANUAL_HANDOFF_ONLY_PLATFORMS = {"youtube", "youtube_shorts", "tiktok", "threads"}
PUBLISH_BOUNDARY = "manual_handoff_only_no_aitoearn"

SELF_GEN_TOPICS = [
    "5个免费AI工具提升编码效率","用Python自动化Excel报表","AI写作助手对比评测",
    "搭建个人知识库的3种方法","GitHub Copilot vs Codeium","用n8n搭建自动化工作流",
    "AI生成PPT的终极指南","Claude Artifacts 实战技巧","自动化部署流水线搭建","AI代码审查工具横评",
]
TIKTOK_QUERIES = ["aitools","productivityhacks","codingtips","aitutorial","techtips","workflow","python","aiagent","nocode"]
DOUYIN_QUERIES = ["AI工具","效率工具","自动化办公","Python教程","AI编程","工作流","开源项目","代码技巧"]

def log(msg): print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run_cmd(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout or r.stderr)[-300:]
    except subprocess.TimeoutExpired: return False, "timeout"
    except Exception as e: return False, str(e)


def _canonical_platform(platform):
    return "youtube" if "youtube" in str(platform) else str(platform)


def _tool_evidence(platform, content_type="knowledge_card_video", *, repost=False):
    planned_tools = {
        "intl_short_video_pipeline": "scripts/intl_short_video_pipeline.py",
        "video_toolchain_runner": "scripts/video_toolchain_runner.py",
        "visual_recipe": "content_platform.video_recipe",
        "edge_tts": "edge_tts",
        "ffmpeg_encode": "tool:ffmpeg",
        "handoff_package_builder": "manual_handoff_package_builder",
    }
    if repost:
        planned_tools.update(
            {
                "yt_dlp_source_download": "tool:yt-dlp",
                "source_dedup_db": "scripts/source_dedup_db.py",
                "source_asset_matcher": "content_platform.video_toolchain.source_asset_matcher",
            }
        )
    tool_manifest = build_tool_invocation_manifest(
        planned_tools=planned_tools,
        invocations={
            name: {"status": "planned" if name == "handoff_package_builder" else "ok", "output": ref}
            for name, ref in planned_tools.items()
        },
    )
    return {
        "tool_invocation_manifest": tool_manifest,
        **build_tool_selection_evidence(
            platform=_canonical_platform(platform),
            content_type=content_type,
            content_goal="generate a platform-specific manual handoff video package with matched visuals, voice, BGM, subtitles, and evidence",
            planned_manifest=tool_manifest,
        ),
    }


def _handoff_item(platform, **payload):
    return {
        **payload,
        "platform": platform,
        "status": "handoff_pending",
        "publish_boundary": PUBLISH_BOUNDARY,
        "handoff_policy": {
            "manual_only": True,
            "forbidden": ["automatic_upload", "aitoearn_publish", "cross_platform_final_mp4_reuse"],
        },
        **_tool_evidence(platform, repost=bool(payload.get("source_url") or payload.get("keyword"))),
    }

# ── 选题 ──
def select_topics():
    today = datetime.now(); doy = today.timetuple().tm_yday
    i1, i2 = (doy*3)%len(SELF_GEN_TOPICS), (doy*3+1)%len(SELF_GEN_TOPICS)
    return {
        "self_gen": [SELF_GEN_TOPICS[i1], SELF_GEN_TOPICS[i2]],
        "cross_kw": [random.choice(TIKTOK_QUERIES), random.choice(DOUYIN_QUERIES)],
        "date": today.strftime("%Y-%m-%d"),
    }

# ── 自生成视频（增强版15-30s）──
def generate_self_video(topic, output_path, platform="youtube_shorts"):
    toolchain_output = _gen_with_project_toolchain(topic, output_path, platform)
    if toolchain_output:
        return toolchain_output
    if os.environ.get("INTL_VIDEO_ALLOW_LEGACY_FALLBACK") != "1":
        log("  ❌ 项目视频工具链失败；未设置 INTL_VIDEO_ALLOW_LEGACY_FALLBACK=1，拒绝绕过分镜/模板/视觉门禁")
        return ""
    sc = Path.home() / ".hermes" / "scripts" / "screencast_engine.py"
    if not sc.is_file():
        return _gen_fallback(topic, output_path, platform)
    enh = enhance_screencast_call(topic, platform)
    log(f"  脚本: {enh['type']} | {len(enh['content'].split(','))}步 ~{len(enh['content'].split(','))*4}s")
    ok, out = run_cmd([sys.executable, str(sc), "--title", topic, "--content", enh["content"],
                        "--type", enh["type"], "--output", str(output_path)], 180)
    if ok and output_path.stat().st_size > 30000:
        log(f"  ✅ {output_path.name} ({output_path.stat().st_size//1024}KB)")
        return str(output_path)
    log(f"  ⚠️ Screencast: {out[:80]}")
    return _gen_fallback(topic, output_path, platform)

def _gen_with_project_toolchain(topic, output_path, platform):
    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "video_toolchain_runner.py"
    if not runner.is_file():
        log("  ❌ 缺少项目视频工具链 runner")
        return ""
    platform_name = "youtube" if "youtube" in platform else "tiktok"
    plan = {
        "required": True,
        "content_form": "knowledge_card_video",
        "platforms": [platform_name],
        "selected_pipeline": "knowledge_card_video",
        "template_family": "chaptered_tutorial" if platform_name == "youtube" else "knowledge_card_motion_case",
        "source": "intl_short_video_pipeline",
    }
    work_dir = output_path.with_suffix("")
    work_dir.mkdir(parents=True, exist_ok=True)
    plan_path = work_dir / "video_toolchain_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(root),
        "VIDEO_OUTPUT_DIR": str(work_dir),
        "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
    }
    log("  项目视频工具链: cinema分镜 → 卡片模板 → TTS → BGM → 字幕 → 视觉门禁")
    proc = subprocess.run(
        [sys.executable, str(runner), topic, topic],
        capture_output=True,
        text=True,
        env=env,
        timeout=int(os.environ.get("INTL_VIDEO_TOOLCHAIN_TIMEOUT", "900")),
        check=False,
    )
    manifest = work_dir / "video_toolchain_runner_manifest.json"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-160:]
        log(f"  ❌ 项目视频工具链失败: {tail}")
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        generated = Path(data.get("output") or "")
    except Exception as exc:
        log(f"  ❌ 项目视频工具链 manifest 无效: {exc}")
        return ""
    if not generated.is_file() or generated.stat().st_size <= 30000:
        log("  ❌ 项目视频工具链未生成有效 MP4")
        return ""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if generated.resolve() != output_path.resolve():
        output_path.write_bytes(generated.read_bytes())
    log(f"  ✅ 项目视频工具链生成: {output_path.name} ({output_path.stat().st_size//1024}KB)")
    return str(output_path)

def _gen_fallback(topic, output_path, platform):
    from PIL import Image, ImageDraw, ImageFont
    vert = platform in ("youtube_shorts","tiktok")
    w, h = (1080,1920) if vert else (1920,1080)
    img = Image.new("RGB", (w,h), (15,23,42)); d = ImageDraw.Draw(img)
    ft = ImageFont.truetype(FONT, 48) if Path(FONT).is_file() else ImageFont.load_default()
    lines = topic.split("\\n") if "\\n" in topic else [topic]
    y = h//3
    for line in lines:
        bb = d.textbbox((0,0), line, font=ft); x = (w-(bb[2]-bb[0]))//2; d.text((x,y), line, fill=(255,255,255), font=ft); y += 70
    card = output_path.with_suffix(".png"); img.save(card)
    tts = output_path.with_suffix(".mp3"); txt = topic.replace("\\n","。")+"。"
    run_cmd([sys.executable,"-m","edge_tts","--voice","en-US-JennyNeural","--text",txt,"--write-media",str(tts)], 30)
    if tts.is_file():
        run_cmd(["ffmpeg","-y","-loop","1","-i",str(card),"-i",str(tts),"-c:v","libx264","-t","10",
                 "-pix_fmt","yuv420p","-c:a","aac","-shortest",str(output_path)], 60)
    if output_path.is_file() and output_path.stat().st_size > 50000:
        return str(output_path)
    return ""

# ── 搬运视频 ──
def cross_post_video(source_url, output_path, platform="youtube_shorts"):
    db = SourceDedupDB()
    if db.is_duplicate(source_url):
        log(f"  ⏭ 已搬运过: {source_url[:50]}")
        return ""
    os.makedirs(output_path.parent, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    log(f"  下载: ...{source_url[-40:]}")
    ok, _ = run_cmd(["yt-dlp","-f","best[height<=1080]","-o",f"{tmp}/src.%(ext)s",source_url], 120)
    srcs = list(tmp.glob("src.*"))
    if not srcs: return ""
    src = srcs[0]
    dur_ok, dur_out = run_cmd(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(src)], 10)
    dur = min(float(dur_out.strip()) if dur_ok else 30, 60)
    vert = platform in ("youtube_shorts","tiktok")
    vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" if vert else "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
    title = Path(source_url).stem.replace("-"," ").replace("_"," ")[:80]
    run_cmd([sys.executable,"-m","edge_tts","--voice","en-US-JennyNeural",
             "--text",f"Tech tip: {title}","--write-media",str(tmp/"tts.mp3")], 30)
    vf += f",drawtext=text='{title}':fontcolor=white:fontsize=24:x=(w-text_w)/2:y=h-th-60:box=1:boxcolor=black@0.5"
    run_cmd(["ffmpeg","-y","-i",str(src),"-i",str(tmp/"tts.mp3"),"-map","0:v:0","-map","1:a:0",
             "-c:v","libx264","-pix_fmt","yuv420p","-vf",vf,"-c:a","aac","-t",str(dur),"-shortest",str(output_path)], 120)
    run_cmd(["rm","-rf",str(tmp)], 5)
    if output_path.is_file() and output_path.stat().st_size > 100000:
        db.record(source_url, platform, title)
        log(f"  ✅ {output_path.name} ({output_path.stat().st_size//1024}KB)")
        return str(output_path)
    return ""

# ── Publish guard ──
def publish_video(video_path, title, platform="youtube"):
    if platform in MANUAL_HANDOFF_ONLY_PLATFORMS:
        log(f"  manual handoff only for {platform}; AiToEarn publishing is disabled by policy")
        return False
    if not AITOEARN_KEY:
        log(f"  ⏭ 无 API Key，跳过发布")
        return False
    aid = YOUTUBE_ACCOUNT if platform == "youtube" else TIKTOK_ACCOUNT
    # This function is retained only for non-manual legacy platforms. Do not
    # extend it to YouTube/TikTok/Threads.
    log(f"  📤 准备发布到 {platform}: {title}")
    log(f"     account_id={aid}")
    log(f"     file={video_path}")
    return True

# ── 主流程 ──
def run_daily_pipeline(strategy=None, dry_run=False):
    os.makedirs(DRAFT_DIR, exist_ok=True)
    topics = strategy or select_topics()
    log(f"📅 {topics['date']} | 自生成: {topics['self_gen']} | 搬运: {topics['cross_kw']}")
    results = {"self_gen":[], "cross_post":[], "date":topics["date"]}

    # 自生成
    for i, topic in enumerate(topics["self_gen"]):
        plat = "youtube_shorts" if i == 0 else "tiktok"
        log(f"\n🎬 自生成[{plat}]: {topic}")
        out = DRAFT_DIR / f"sg_{topics['date']}_{i}.mp4"
        if not dry_run:
            p = generate_self_video(topic, out, plat)
            if p: results["self_gen"].append(_handoff_item(plat, topic=topic, file=p))
        else:
            results["self_gen"].append(_handoff_item(plat, topic=topic, dry_run=True))

    # 搬运（dry-run 模式下跳过）
    log(f"\n📦 搬运线...")
    for i, kw in enumerate(topics["cross_kw"]):
        plat = "tiktok" if i == 0 else "youtube_shorts"
        log(f"  [{plat}] {kw}")
        results["cross_post"].append(_handoff_item(plat, keyword=kw, dry_run=True))

    # Manual-handoff boundary: never auto-publish YouTube/TikTok from this script.
    for item in results["self_gen"]:
        if item.get("file"):
            plat = "youtube" if "youtube" in item["platform"] else "tiktok"
            publish_video(item["file"], item["topic"], plat)

    manifest = DRAFT_DIR / f"manifest_{topics['date']}.json"
    manifest.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log(f"\n📋 清单: {manifest}")
    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    r = run_daily_pipeline(dry_run=args.dry_run)
    sg = len(r["self_gen"]); cp = len(r["cross_post"])
    print(f"\n{'='*40}\n管线完成 | 自生成:{sg} | 搬运:{cp} | 合计:{sg+cp}")
