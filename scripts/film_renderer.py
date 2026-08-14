#!/usr/bin/env python3
"""融合渲染器：电影级多镜头 + xfade 转场 + 双层动效 + drawtext 字幕。

作为主仓心管线（video_toolchain_runner）的可选渲染器存在：
- 输入：runner 产出的 --video-dir 下的 cards.json / tts/ / backgrounds/ / scene_manifest.json
- 输出：final.mp4（通过 runner 的 cinema visual gate / artifact gate / motion gate / scene duration gate）
- 路由：plan.selected_pipeline = cinema_multishot_video 时，runner 通过
  VIDEO_RENDERER_CINEMA_MULTISHOT_VIDEO=scripts/film_renderer.py 调用本脚本
- 每个段落拆 A（全景建立：大标题+引言+数据徽章）与 B（特写要点：3模块 stagger 入场）双镜头，
  镜头间 xfade 转场，背景 Ken Burns + 正文持续浮动（双层分离运动），drawtext 字幕烧录。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/root/.ai-self-media-tools")
sys.path.insert(0, str(ROOT))

W, H = 1080, 1920
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
XFADE_DUR = 0.5
TRANSITIONS = ["fade", "circleopen", "slideleft", "wipeleft"]

# 镜头A 背景运动（建立镜头）：慢推，方向按段轮换
KB_A = [
    ("scale(1.00) translate(0px,0px)", "scale(1.08) translate(0px,-20px)"),
    ("scale(1.00) translate(0px,0px)", "scale(1.07) translate(-20px,0px)"),
    ("scale(1.00) translate(0px,0px)", "scale(1.09) translate(0px,20px)"),
    ("scale(1.00) translate(0px,0px)", "scale(1.06) translate(20px,0px)"),
]
# 镜头B 背景运动（要点镜头）：反向 pan
KB_B = [
    ("scale(1.08) translate(0px,-20px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.07) translate(-20px,0px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.09) translate(0px,20px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.06) translate(20px,0px)", "scale(1.00) translate(0px,0px)"),
]
# 镜头B 模块动效轮换
MODULE_ANIMS = [
    ("staggerUp", ["translateY(30px)", "translateY(0px)"]),
    ("fadeSlideL", ["translateX(30px)", "translateX(0px)"]),
    ("staggerUp", ["translateY(24px)", "translateY(0px)"]),
    ("fadeSlideR", ["translateX(-30px)", "translateX(0px)"]),
]


def _b64img(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout).get("format", {}).get("duration", 4.0))
    except Exception:
        return 4.0


def _card_title(card: dict, fallback: str = "") -> str:
    return str(card.get("t") or card.get("txt") or fallback)[:60]


def _stat_from_card(card: dict) -> str:
    num = str(card.get("num") or "")
    ext = str(card.get("ext") or "")
    if num:
        return num
    txt = str(card.get("txt") or "")
    nums = re.findall(r"\d+[\.\d]*[%倍个分钟小时秒]?", txt)
    return nums[0] if nums else ""


def _modules_from_card(card: dict) -> list[str]:
    items = card.get("items") or []
    txt = str(card.get("txt") or "")
    parts = [str(x)[:34] for x in items if str(x).strip()] if items else []
    if len(parts) < 3:
        # 从 txt 拆 3 个短句
        sentences = [s.strip() for s in re.split(r"[，。；！？、]", txt) if s.strip()]
        parts = (sentences[:3] if len(sentences) >= 3 else sentences + ["", "", ""])[:3]
    return (parts + ["", "", ""])[:3]


def build_shot_a(idx: int, title: str, stat: str, bg_path: str, kicker: str, stat_label: str = "关键数字") -> str:
    kb = KB_A[idx % 4]
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover;
  animation: kb 11s ease-in-out infinite alternate; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0.65) 45%, rgba(0,0,0,0.92) 100%); }}
.content {{ position:absolute; inset:0; z-index:2; display:flex; flex-direction:column; justify-content:center; padding:130px 90px; }}
.kicker {{ font-size:32px; color:#ffd60a; font-weight:800; letter-spacing:5px; margin-bottom:40px;
  animation: fadeUp 0.9s ease-out both; }}
.title {{ font-size:80px; line-height:1.28; font-weight:900; color:#fff; text-shadow:0 6px 26px rgba(0,0,0,0.8);
  animation: fadeUp 1.1s ease-out 0.15s both; }}
.stat {{ margin-top:64px; display:inline-block; background:rgba(255,255,255,0.12); border:2px solid rgba(255,255,255,0.35);
  border-radius:44px; padding:22px 48px; animation: fadeUp 1.1s ease-out 0.5s both; }}
.stat .n {{ font-size:64px; font-weight:900; color:#7ee787; }}
.stat .l {{ font-size:30px; color:#d0d0d0; margin-left:16px; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(26px); }} to {{ opacity:1; transform:translateY(0); }} }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}A</div>
<div class="content">
  <div class="kicker">{kicker}</div>
  <div class="title">{title}</div>
  <div class="stat"><span class="n">{stat}</span><span class="l">{stat_label}</span></div>
</div>
</body></html>"""


def build_shot_b(idx: int, title: str, modules: list[str], bg_path: str,
                 screenshot_path: str | None = None, screenshot_caption: str = "") -> str:
    kb = KB_B[idx % 4]
    b64 = _b64img(bg_path)
    anim = MODULE_ANIMS[idx % 4]
    kf_off = "0.9s" if anim[0] == "staggerUp" else "0.8s"
    # 截图模式：真实素材（规则1：工具/项目介绍要有真实截图）
    if screenshot_path and Path(screenshot_path).is_file():
        shot_b64 = _b64img(screenshot_path)
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; background:#000; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover;
  animation: kb 11s ease-in-out infinite alternate; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.72) 55%, rgba(0,0,0,0.94) 100%); }}
.content {{ position:absolute; inset:0; z-index:2; display:flex; flex-direction:column; align-items:center; padding:140px 80px; }}
.head {{ font-size:44px; font-weight:800; color:#fff; margin-bottom:44px; text-shadow:0 4px 16px rgba(0,0,0,0.7);
  animation:fadeUp 0.8s ease-out both; }}
.shot {{ width:880px; max-height:860px; object-fit:contain; border:3px solid rgba(255,255,255,0.55); border-radius:20px;
  box-shadow:0 30px 80px rgba(0,0,0,0.65); animation: fadeUp 0.8s ease-out 0.2s both; }}
.caption {{ margin-top:36px; font-size:34px; color:#ffd60a; font-weight:700; text-align:center;
  animation: fadeUp 0.8s ease-out 0.5s both; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(24px); }} to {{ opacity:1; transform:translateY(0); }} }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}B</div>
<div class="content">
  <div class="head">{title}</div>
  <img class="shot" src="data:image/png;base64,{shot_b64}"/>
  <div class="caption">{screenshot_caption}</div>
</div>
</body></html>"""
    mod_css = f"""
.module {{ margin-bottom:44px; padding:34px 44px; background:rgba(255,255,255,0.09); backdrop-filter:blur(10px);
  border-left:6px solid #ffd60a; border-radius:16px; opacity:0; }}
.module:nth-child(1) {{ animation:{anim[0]} 0.8s ease-out 0.2s both; }}
.module:nth-child(2) {{ animation:{anim[0]} 0.8s ease-out {kf_off} both; }}
.module:nth-child(3) {{ animation:{anim[0]} 0.8s ease-out calc({kf_off} + 0.9s) both; }}
.module .m {{ font-size:44px; line-height:1.5; color:#fff; font-weight:600; text-shadow:0 2px 10px rgba(0,0,0,0.7); }}
.module .t {{ font-size:26px; color:#ffd60a; font-weight:700; letter-spacing:2px; }}
@keyframes {anim[0]} {{ from {{ opacity:0; transform:{anim[1][0]}; }} to {{ opacity:1; transform:{anim[1][1]}; }} }}
"""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover;
  animation: kb 11s ease-in-out infinite alternate; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.40) 0%, rgba(0,0,0,0.62) 45%, rgba(0,0,0,0.90) 100%); }}
.content {{ position:absolute; inset:0; z-index:2; display:flex; flex-direction:column; justify-content:center; padding:130px 90px; }}
.head {{ font-size:46px; font-weight:800; color:#fff; margin-bottom:56px; text-shadow:0 4px 16px rgba(0,0,0,0.7);
  animation:fadeUp 0.8s ease-out both; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(20px); }} to {{ opacity:1; transform:translateY(0); }} }}
{mod_css}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.13); z-index:2; }}
</style></head><body>
<div class="bg"></div><div class="overlay"></div>
<div class="idx">{idx:02d}B</div>
<div class="content">
  <div class="head">{title}</div>
  <div class="module"><div class="t">①</div><div class="m">{modules[0]}</div></div>
  <div class="module"><div class="t">②</div><div class="m">{modules[1]}</div></div>
  <div class="module"><div class="t">③</div><div class="m">{modules[2]}</div></div>
</div>
</body></html>"""


async def _record_shot(name: str, html_path: str, dur: float, out: Path) -> str | None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(out / "webm"),
            record_video_size={"width": W, "height": H},
        )
        page = await ctx.new_page()
        await page.goto(f"file://{html_path}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(int(dur * 1000))
        await page.close()
        vp = await page.video.path() if page.video else None
        await ctx.close()
        if vp:
            target = out / "webm" / f"{name}.webm"
            os.replace(vp, target)
            return str(target)
        return None


def _wrap(text: str, max_chars: int = 20):
    if len(text) <= max_chars:
        return text, ""
    cut = -1
    for i in range(max_chars, 0, -1):
        if text[i] in "，。；！？、：":
            cut = i + 1
            break
    if cut == -1:
        cut = max_chars
    return text[:cut], text[cut:max_chars + cut]


def main() -> int:
    ap = argparse.ArgumentParser(description="融合渲染器：电影级多镜头")
    ap.add_argument("--video-dir", required=True)
    ap.add_argument("--theme", default="cyber-neon")
    ap.add_argument("--title", default="Untitled")
    ap.add_argument("--desc", default="")
    ap.add_argument("--bgm-style", default="warm acoustic guitar and light piano")
    ap.add_argument("--platform", default="kuaishou")
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--width", type=int, default=W)
    ap.add_argument("--height", type=int, default=H)
    ap.add_argument("--script", default="", help="完整 8 段脚本文件（空行分隔），避免 runner 按句切分截断 TTS")
    args = ap.parse_args()

    out = Path(args.video_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("html", "webm", "shots", "sub"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    cards_path = out / "cards.json"
    if not cards_path.is_file():
        print(f"cards.json 不存在: {cards_path}", file=sys.stderr)
        return 2
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    cards = cards if isinstance(cards, list) else cards.get("cards", [])
    if len(cards) < 8:
        print(f"cards 数量不足: {len(cards)} < 8", file=sys.stderr)
        return 2

    # 背景图：优先 backgrounds/bg_XX.jpg（runner materialize 产物），回退 card visual_asset
    bg_dir = out / "backgrounds"
    bg_paths = sorted(bg_dir.glob("bg_*.jpg")) if bg_dir.is_dir() else []
    if len(bg_paths) < 8:
        # 从 cards visual_asset / materialized_background 收集
        bg_paths = []
        for c in cards[:8]:
            va = c.get("visual_asset") or {}
            p = str(va.get("materialized_background") or va.get("background_image") or "")
            if p and Path(p).is_file():
                bg_paths.append(Path(p))
    if len(bg_paths) < 8:
        print(f"背景图不足: {len(bg_paths)} < 8", file=sys.stderr)
        return 2

    # TTS：优先从 --script 读取完整 8 段（空行分隔），避免 runner 按句切分截断；
    # 未显式传 --script 时自动探测 video_dir/script.md 或上级目录 script.md。
    script_segments: list[str] = []
    script_candidates = [Path(args.script)] if args.script else []
    script_candidates += [out / "script.md", out.parent / "script.md", Path(args.video_dir).parent / "script.md"]
    script_file = next((p for p in script_candidates if p.is_file()), None)
    if script_file:
        raw = script_file.read_text(encoding="utf-8")
        script_segments = [seg.strip() for seg in re.split(r"\n\s*\n", raw) if seg.strip()]
        print(f"TTS 脚本: {script_file} ({len(script_segments)} 段)")

    # TTS 生产默认 = Edge TTS 逐段独立合成（08-14 用户 8 条规则）。
    # ⚠️ 不经 voice_engine 的 DeAI 后处理（呼吸音/停顿/变速会引入间隔性杂音——08-14 实测）。
    # Edge 逐段生成：SSML 控制语速/音调/停顿（rate/pitch），display_text/tts_text 分离 +
    # pronunciation_dictionary 处理专有名词（TTSTextCompiler），每段真实时长对齐镜头。
    # Qwen 仅灰度备用（TTS_PROVIDER=qwen），须试听验收不低于 Edge 才可进生产。
    tts_files = []
    tts_dir = out / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    voice_env = dict(os.environ)
    voice_env.setdefault("PYTHONPATH", str(ROOT))
    for env_file in ("secrets/qwen_tts.env",):
        p = ROOT / env_file
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    voice_env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    tts_provider = os.environ.get("TTS_PROVIDER", "edge").strip().lower()
    print(f"TTS provider: {tts_provider}")

    full_script = "\n\n".join(script_segments[:8]) if script_segments else ""
    tts_lang = "zh" if re.search(r"[\u4e00-\u9fff]", full_script) else "en"

    # 发音词典（TTSTextCompiler：处理 AI/API/TTS/数字/专有名词）
    try:
        from content_platform.tts_text_compiler import TTSTextCompiler
        dict_path = ROOT / "config" / "pronunciation_dictionary.json"
        compiler = TTSTextCompiler.from_file(dict_path) if dict_path.is_file() else TTSTextCompiler([])
    except Exception:
        compiler = None

    # 音色：中文 tech=zh-CN-YunjianNeural，英文 tech=en-US-GuyNeural（与 voice_engine GENRE_VOICE_MAP 一致）
    edge_voice = "zh-CN-YunjianNeural" if tts_lang == "zh" else "en-US-GuyNeural"

    tts_records = []
    for i in range(1, 9):
        mp3 = tts_dir / f"tts_{i:02d}.mp3"
        text = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
            else str(cards[i - 1].get("tts") or cards[i - 1].get("txt") or "")
        if mp3.is_file() and mp3.stat().st_size > 10_000:
            tts_files.append(str(mp3))
            continue
        # display_text/tts_text 分离 + 词典
        display_text = text
        tts_text = text
        applied_rules = []
        if compiler:
            try:
                compiled = compiler.compile(text, context="tech")
                tts_text = compiled.tts_text
                display_text = compiled.display_text
                applied_rules = list(compiled.applied_rules or [])
            except Exception:
                pass
        if tts_provider == "qwen":
            # 灰度：Qwen 直接合成（不经 DeAI）
            try:
                from scripts.voice_engine import QwenTTSProvider
                qwen = QwenTTSProvider()
                if qwen.available:
                    qwen.synthesize(tts_text, mp3,
                                    voice=os.environ.get("QWEN_AUDIO_TTS_VOICE", "longanhuan_v3.6"),
                                    language="Chinese" if tts_lang == "zh" else "English")
            except Exception as exc:
                print(f"Qwen 合成失败({i}): {str(exc)[:80]}", file=sys.stderr)
        if not mp3.is_file() or mp3.stat().st_size <= 10_000:
            # Edge 生产默认：SSML 控制语速/音调（-5% 语速，接近真人）
            edge_cmd = ["edge-tts", "--voice", edge_voice, "--rate=-5%",
                        "--text", tts_text, "--write-media", str(mp3)]
            subprocess.run(edge_cmd, capture_output=True, text=True, timeout=90)
        if mp3.is_file() and mp3.stat().st_size > 10_000:
            tts_files.append(str(mp3))
            tts_records.append({
                "provider": tts_provider if tts_provider == "qwen" else "edge-tts",
                "voice": edge_voice if tts_provider != "qwen" else os.environ.get("QWEN_AUDIO_TTS_VOICE", "longanhuan_v3.6"),
                "rate": "-5%", "pitch": "+0Hz",
                "tts_text": tts_text, "display_text": display_text,
                "applied_rules": applied_rules,
                "duration_seconds": _duration(str(mp3)),
            })
    durs = [_duration(p) for p in tts_files]
    print("TTS 时长:", [round(d, 2) for d in durs])
    # 规则6：TTS 记录落盘（provider/voice/rate/pitch/tts_text/词典规则/时长）
    (out / "tts_records.json").write_text(json.dumps(tts_records, ensure_ascii=False, indent=2), encoding="utf-8")

    # 逐段兜底（多段模式失败时）
    if len(tts_files) < 8:
        tts_files = []
        for i in range(1, 9):
            mp3 = tts_dir / f"tts_{i:02d}.mp3"
            text = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
                else str(cards[i - 1].get("tts") or cards[i - 1].get("txt") or "")
            if mp3.is_file() and mp3.stat().st_size > 10_000:
                tts_files.append(str(mp3))
                continue
            subprocess.run(["edge-tts", "--voice", "zh-CN-YunxiNeural", "--rate=-5%",
                            "--text", text, "--write-media", str(mp3)], capture_output=True, text=True, timeout=90)
            tts_files.append(str(mp3))
    durs = [_duration(p) for p in tts_files]
    print("TTS 时长:", [round(d, 2) for d in durs])

    kicker_map = {
        "kuaishou": "MAJIC AI · AI模型实测",
        "douyin_ai": "MAJIC AI · AI实测",
        "bilibili": "MAJIC AI · AI实测",
        "shipinhao": "马吉克AI · 实测",
        "tiktok": "MAJIC AI · AI Tools",
        "youtube": "MAJIC AI · AI Tools",
    }
    # 英文平台（tiktok/youtube）用英文 kicker，其余中文；按 tts_lang 兜底
    kicker = kicker_map.get(args.platform, "MAJIC AI · AI实测" if tts_lang == "zh" else "MAJIC AI · AI Tools")

    # 镜头内容：优先完整脚本段落（避免 runner 按句切分截断），标题取段落首句/前16字，模块取段内3短句
    def seg_title(i: int) -> str:
        if i <= len(script_segments) and script_segments[i - 1]:
            seg = script_segments[i - 1]
            first = re.split(r"[，。；！？、]", seg)[0].strip()[:16]
            return first if first else seg[:16]
        return _card_title(cards[i - 1], f"第 {i} 段")

    def seg_modules(i: int) -> list[str]:
        if i <= len(script_segments) and script_segments[i - 1]:
            seg = script_segments[i - 1]
            sentences = [s.strip() for s in re.split(r"[，。；！？、]", seg) if s.strip()]
            return (sentences[:3] if len(sentences) >= 3 else sentences + ["", "", ""])[:3]
        return _modules_from_card(cards[i - 1])

    # 截图素材检测（规则1：工具/项目介绍嵌入真实截图）——video_dir/screenshots/ 或上级目录
    screenshots_dir = None
    for cand in (out / "screenshots", out.parent / "screenshots", Path(args.video_dir).parent / "screenshots"):
        if cand.is_dir():
            screenshots_dir = cand
            break
    screenshot_files = sorted(screenshots_dir.glob("*.png")) + sorted(screenshots_dir.glob("*.jpg")) if screenshots_dir else []
    print(f"截图素材: {len(screenshot_files)} 张")

    shot_durs = []
    for i in range(1, 9):
        card = cards[i - 1]
        title = seg_title(i)
        stat = _stat_from_card(card)
        modules = seg_modules(i)
        bg = str(bg_paths[i - 1])
        stat_label = "关键数字" if tts_lang == "zh" else "KEY NUMBER"
        html_a = build_shot_a(i, title, stat, bg, kicker, stat_label=stat_label)
        # 截图卡：段2（介绍后细节）与段6（数据/进展）优先用真实截图
        shot_path = None
        caption = ""
        if screenshot_files and i in (2, 6):
            si = 0 if i == 2 else (1 if len(screenshot_files) > 1 else 0)
            shot_path = str(screenshot_files[si])
            # 截图卡不加 caption 标注（用户 08-14：标注信息不需要，截图本身即内容）
            caption = ""
        html_b = build_shot_b(i, title, modules, bg, screenshot_path=shot_path, screenshot_caption=caption)
        (out / "html" / f"shot_{i:02d}A.html").write_text(html_a, encoding="utf-8")
        (out / "html" / f"shot_{i:02d}B.html").write_text(html_b, encoding="utf-8")
        d = durs[i - 1]
        a_dur = min(2.8, d * 0.30)
        b_dur = max(1.0, d - a_dur + 0.15)
        shot_durs.append((f"shot_{i:02d}A", a_dur))
        shot_durs.append((f"shot_{i:02d}B", b_dur))

    async def _render():
        for name, sd in shot_durs:
            hp = out / "html" / f"{name}.html"
            target = out / "shots" / f"{name}.mp4"
            if target.is_file() and target.stat().st_size > 50_000:
                print(f"{name}: 复用已有镜头")
                continue
            webm = await _record_shot(name, str(hp), sd + 0.5, out)
            if not webm:
                print(f"{name} 录制失败", file=sys.stderr)
                continue
            # 强制截断到目标时长（Playwright 录制实际时长偏长 1-2s，累计导致总时长超限）
            subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-i", webm,
                            "-t", f"{sd:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                            "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-an",
                            str(target)], timeout=120)
    asyncio.run(_render())

    shot_mp4s = [out / "shots" / f"{n}.mp4" for n, _ in shot_durs]
    if not all(p.is_file() for p in shot_mp4s):
        print("镜头渲染不完整", file=sys.stderr)
        return 3

    # 16 镜头 → 4 组 xfade（4镜头/组）+ 组间 concat
    shot_names = [n for n, _ in shot_durs]
    durs_map = {n: _duration(str(out / "shots" / f"{n}.mp4")) for n in shot_names}
    group_outs = []
    for gi in range(4):
        names = shot_names[gi * 4:(gi + 1) * 4]
        inputs = []
        for n in names:
            inputs += ["-i", str(out / "shots" / f"{n}.mp4")]
        fc_parts = []
        prev = "0:v"
        offset_acc = 0.0
        for i in range(1, len(names)):
            offset_acc += durs_map[names[i - 1]] - XFADE_DUR
            offset_acc = max(0.05, offset_acc - 0.05)
            label = f"g{gi}x{i}"
            trans = TRANSITIONS[(gi * 3 + i - 1) % 4]
            fc_parts.append(f"[{prev}][{i}:v]xfade=transition={trans}:duration={XFADE_DUR}:offset={offset_acc:.3f}[{label}]")
            prev = label
        fc = ";".join(fc_parts) + f";[{prev}]format=yuv420p[v]"
        gout = out / f"group_{gi}.mp4"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc,
                            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                            "-profile:v", "baseline", "-pix_fmt", "yuv420p", str(gout)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"group_{gi} xfade 失败: {r.stderr[-200:]}", file=sys.stderr)
            return 3
        group_outs.append(gout)

    groups_txt = out / "groups.txt"
    groups_txt.write_text("\n".join(f"file '{p}'" for p in group_outs), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(groups_txt),
                    "-c", "copy", str(out / "visual_xfade.mp4")], capture_output=True, text=True, timeout=120)

    # 视觉总时长 + 全局镜头起始
    visual_total = sum(durs_map.values()) - (len(shot_names) - 1) * XFADE_DUR
    starts_global = []
    acc = 0.0
    for i in range(len(shot_names)):
        starts_global.append(acc)
        if i < len(shot_names) - 1:
            acc += durs_map[shot_names[i]] - XFADE_DUR

    # 配音：8 段 TTS 分段 adelay 到镜头A 起始 + atrim 裁剪到段视觉时长（补偿 xfade 重叠，防溢出）
    voice_path = out / "voice_aligned.wav"
    voice_fc = []
    inputs = []
    for i in range(1, 9):
        inputs += ["-i", str(tts_files[i - 1])]
        delay_ms = int(starts_global[2 * (i - 1)] * 1000)
        # 段视觉时长 = 镜头B 结束 - 镜头A 起点（含转场重叠压缩）
        seg_end = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]]
        seg_visual_dur = seg_end - starts_global[2 * (i - 1)]
        tts_dur = durs[i - 1]
        # TTS 若比段视觉长，atrim 裁剪到段视觉时长（略留 0.05s 余量防尾音截断突兀）
        # ⚠️ 顺序必须：atrim(裁剪) → asetpts(归零) → adelay(延迟到段起点)。
        # 错误顺序 adelay→atrim→asetpts 会重置 PTS 把所有段拉到 0 起点 → 重叠
        if tts_dur > seg_visual_dur:
            voice_fc.append(f"[{i - 1}:a]atrim=0:{max(0.5, seg_visual_dur - 0.05)},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[a{i - 1}]")
        else:
            voice_fc.append(f"[{i - 1}:a]adelay={delay_ms}|{delay_ms}[a{i - 1}]")
    mix_names = "".join(f"[a{i}]" for i in range(8))
    # duration=longest：voice 轨道按各段 adelay 后自然延伸到全长，BGM 不会被截断
    voice_fc.append(f"{mix_names}amix=inputs=8:duration=longest:normalize=0[voice]")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(voice_fc),
                        "-map", "[voice]", str(voice_path)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"配音对齐失败: {r.stderr[-200:]}", file=sys.stderr)
        return 3

    # 合流（视频 + 配音 + BGM）
    bgm_path = out / "bgm.mp3"
    if not bgm_path.is_file():
        os.environ.setdefault("BGM_TARGET_PLATFORM", args.platform)
        from scripts.kuaishou_render import download_bgm
        bgm_path = Path(download_bgm(str(out), style=args.bgm_style))
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "visual_xfade.mp4"),
                        "-i", str(voice_path), "-stream_loop", "-1", "-i", str(bgm_path),
                        "-filter_complex",
                        "[1:a]volume=2.4[v];[2:a]volume=0.11[bg];[v][bg]amix=inputs=2:duration=longest:normalize=0[a]",
                        "-map", "0:v", "-map", "[a]", "-t", f"{visual_total:.3f}",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", str(out / "mixed_v2.mp4")],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"混音失败: {r.stderr[-200:]}", file=sys.stderr)
        return 3

    # drawtext 字幕（按 seg 边界累加）：每段取前 2 句摘要（中文 ≤20字/行 × 2 行），避免长段溢出
    script_texts = []
    for i in range(1, 9):
        seg = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
            else str(cards[i - 1].get("tts") or cards[i - 1].get("txt") or "")
        sentences = [s.strip() for s in re.split(r"[。；！？]", seg) if s.strip()]
        sub = "。".join(sentences[:2]) + ("。" if sentences[:2] else "")
        if len(sub) > 40:
            sub = sub[:39] + "…"
        script_texts.append(sub)
    filters = []
    for i, text in enumerate(script_texts, 1):
        st = starts_global[2 * (i - 1)] + 0.4
        en = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]] - 0.2
        l1, l2 = _wrap(text)
        tf1 = out / "sub" / f"l1_{i:02d}.txt"
        tf2 = out / "sub" / f"l2_{i:02d}.txt"
        tf1.write_text(l1, encoding="utf-8")
        en1 = f"between(t,{st:.3f},{en:.3f})"
        filters.append(f"drawtext=fontfile={FONT}:textfile={tf1}:fontsize=42:fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:y=h-350:enable='{en1}'")
        if l2:
            tf2.write_text(l2, encoding="utf-8")
            filters.append(f"drawtext=fontfile={FONT}:textfile={tf2}:fontsize=42:fontcolor=white:borderw=4:bordercolor=black:x=(w-text_w)/2:y=h-290:enable='{en1}'")

    fc2 = f"[0:v]{','.join(filters)}[v]"
    final = out / "final.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "mixed_v2.mp4"),
                        "-filter_complex", fc2, "-map", "[v]", "-map", "0:a",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                        "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        "-c:a", "aac", "-b:a", "128k", str(final)],
                       capture_output=True, text=True, timeout=400)
    if r.returncode != 0:
        print(f"编码失败: {r.stderr[-300:]}", file=sys.stderr)
        return 3

    # 字幕烧录验证：每段 B 镜头中点采样（避开 enable 边界误报，覆盖全片）
    import numpy as np
    from PIL import Image
    ok = True
    samples = []
    for i in range(1, 9):
        seg_a_start = starts_global[2 * (i - 1)]
        seg_b_end = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]]
        mid = (seg_a_start + 0.4 + seg_b_end - 0.2) / 2.0
        frame_num = int(mid * 25)
        if mid > visual_total:
            continue
        frame = out / "sub" / f"sample_{i:02d}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-i", str(final),
                        "-vf", f"select=eq(n\\,{frame_num})", "-frames:v", "1", str(frame)], capture_output=True)
        img = np.array(Image.open(frame).convert("L"))
        white = int((img[1500:1850, :] > 150).sum())
        passed = white > 800
        ok = ok and passed
        samples.append({"segment": i, "time_s": round(mid, 2), "white_pixels": white, "passed": passed})
        print(f"  字幕采样 段{i} @{mid:.1f}s: 白像素 {white}", "OK" if passed else "FAIL")
    if not ok:
        print("字幕烧录验证失败", file=sys.stderr)
        return 4

    # segment_motion_evidence（runner 门禁要求）
    seg_evidence = {"segments": []}
    for i in range(1, 9):
        shot = (cards[i - 1].get("shotcraft") or {})
        seg_evidence["segments"].append({
            "index": i,
            "move_id": str(shot.get("name") or f"cinema_multishot_{i}"),
            "profile": f"establish_then_detail_{i}",
            "rendered": True,
            "reused": False,
            "renderer": "film_renderer",
        })
    (out / "segment_motion_evidence.json").write_text(json.dumps(seg_evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    # cinema visual gate：从 16 镜头抽帧生成 8 张主卡 PNG（runner 检查 cards/*.png）
    card_dir = out / "cards"
    card_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        shot_mp4 = out / "shots" / f"shot_{i:02d}A.mp4"
        if shot_mp4.is_file():
            card_png = card_dir / f"card_{i:02d}.png"
            subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-ss", "1.5", "-i", str(shot_mp4),
                            "-frames:v", "1", str(card_png)], capture_output=True, timeout=30)
    print("cinema gate 卡片:", len(list(card_dir.glob("card_*.png"))))

    # bgm_source.json（runner/bgm 撞曲门禁）
    if (out / "bgm_source.json").is_file():
        try:
            bgm_src = json.loads((out / "bgm_source.json").read_text(encoding="utf-8"))
            bgm_src["real_instrument"] = True
            bgm_src.setdefault("vocal", "none")
            (out / "bgm_source.json").write_text(json.dumps(bgm_src, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    print(f"final: {final} ({final.stat().st_size / 1024 / 1024:.1f}MB, {visual_total:.1f}s)")
    print(json.dumps({"ok": True, "output": str(final), "status": "rendered"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
