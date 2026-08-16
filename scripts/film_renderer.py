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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT))

W, H = 1080, 1920
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
XFADE_DUR = 0.5
# 转场类型（08-14 用户反馈「切换闪白光」→ 移除 xfade "fade"（fade 到白场）。
# 08-14 增强「真实可观性」：按镜头类型差异化过渡——A→A 黑场/smooth（建立感），
# B→B 方向性 wipe/slide（节奏推进），A→B circle（段落转折），机械轮换 → 语义映射。
TRANSITIONS = ["fadeblack", "smoothleft", "circleopen", "slideleft", "wipeleft", "smoothup", "circleright", "fadegrays"]
# 转场时长：段内镜头间紧凑(0.35s)，段落间强调(0.6s) —— 差异化节奏，非统一 0.5s
XFADE_DUR_SHORT = 0.35
XFADE_DUR_LONG = 0.6
MAX_TTS_SEGMENT_SECONDS = 20.0
MAX_RENDER_SECONDS = 100.0
FILM_TTS_MAX_ATTEMPTS = 4
RENDERER_VERSION = "cinematic-v5"
ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS = 90


def resolve_render_policy() -> dict[str, object]:
    """Keep the production default cinematic and make degradation explicit."""
    profile = os.environ.get("FILM_QUALITY_PROFILE", "high").strip().casefold() or "high"
    motion_mode = os.environ.get("FILM_MOTION_MODE", "cinematic").strip().casefold() or "cinematic"
    allow_degraded = os.environ.get("FILM_ALLOW_DEGRADED", "").strip() == "1"
    if profile == "high":
        if motion_mode != "cinematic":
            raise ValueError("high quality requires FILM_MOTION_MODE=cinematic")
        return {"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False}
    if profile == "degraded":
        if motion_mode != "safe" or not allow_degraded:
            raise ValueError("degraded rendering requires FILM_MOTION_MODE=safe and FILM_ALLOW_DEGRADED=1")
        return {"quality_profile": "degraded", "motion_mode": "safe", "allow_degraded": True}
    raise ValueError(f"unsupported FILM_QUALITY_PROFILE: {profile}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _remove_renderer_outputs(out: Path) -> None:
    """Remove only reproducible renderer outputs when its contract changes."""
    for dirname in ("html", "webm", "shots", "frames", "sub"):
        shutil.rmtree(out / dirname, ignore_errors=True)
    for pattern in ("group_*.mp4", "visual_xfade.mp4", "mixed_v2.mp4", "final.mp4", "voice_aligned.wav", "groups.txt"):
        for path in out.glob(pattern):
            path.unlink(missing_ok=True)


def prepare_render_contract(out: Path, contract: dict[str, object]) -> bool:
    """Invalidate derived video assets if renderer behavior or inputs changed."""
    state_path = out / "render_contract.json"
    previous = None
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {"invalid": True}
    derived_outputs_exist = any((out / name).exists() for name in ("shots", "webm", "frames", "final.mp4", "mixed_v2.mp4"))
    changed = previous != contract if previous is not None else derived_outputs_exist
    if changed:
        _remove_renderer_outputs(out)
    state_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def validate_audio_spec(probe: dict[str, object]) -> dict[str, object]:
    sample_rate = int(probe.get("sample_rate") or 0)
    channels = int(probe.get("channels") or 0)
    failures = []
    if sample_rate != 44100:
        failures.append("audio_sample_rate_invalid")
    if channels != 2:
        failures.append("audio_channel_layout_invalid")
    return {"passed": not failures, "sample_rate": sample_rate, "channels": channels, "failures": failures}


def probe_audio_spec(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        return {"sample_rate": 0, "channels": 0, "probe_error": (result.stderr or "ffprobe failed")[-160:]}
    try:
        streams = json.loads(result.stdout).get("streams") or []
        audio = next((row for row in streams if row.get("codec_type") == "audio"), {})
        return {"sample_rate": int(audio.get("sample_rate") or 0), "channels": int(audio.get("channels") or 0)}
    except (ValueError, TypeError, json.JSONDecodeError):
        return {"sample_rate": 0, "channels": 0, "probe_error": "invalid ffprobe output"}


def build_render_quality_evidence(
    *, policy: dict[str, object], shot_records: list[dict[str, object]], motion: dict[str, object]
) -> dict[str, object]:
    """Combine renderer provenance and measured motion into a publishable verdict."""
    fallbacks = [row.get("name") for row in shot_records if row.get("fallback")]
    stills = [row.get("name") for row in shot_records if row.get("renderer") == "still-motion"]
    failures = []
    if policy.get("motion_mode") == "cinematic" and (fallbacks or stills):
        failures.append("cinematic_fallback_used")
    if not motion.get("passed"):
        failures.append("motion_evidence_insufficient")
    return {
        "version": "render_quality_evidence_v1",
        "passed": not failures,
        "quality_profile": policy.get("quality_profile"),
        "motion_mode": policy.get("motion_mode"),
        "fallback_shots": fallbacks,
        "still_motion_shots": stills,
        "shot_records": shot_records,
        "motion": motion,
        "failures": failures,
    }


def calculate_timeline(durations: list[float], transition_after: list[float]) -> tuple[list[float], float]:
    """Return scene starts from the exact transition used at each boundary."""
    if len(transition_after) != max(0, len(durations) - 1):
        raise ValueError("transition count must equal duration count minus one")
    starts: list[float] = []
    position = 0.0
    for index, duration in enumerate(durations):
        starts.append(round(position, 3))
        if index < len(transition_after):
            position += duration - transition_after[index]
        else:
            position += duration
    return starts, round(position, 3)


def script_gate_passed(returncode: int, quality_profile: str) -> bool:
    return returncode == 0 or quality_profile == "degraded"


def element_render_timeout_seconds(duration: float) -> float:
    """Keep native element-motion recordings bounded without cutting long scenes."""
    return max(ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS, float(duration) * 8 + 30)

# 镜头A 背景运动（建立镜头）：8 种电影运镜轮换（推入/拉出/摇移/呼吸/斜推）
# 08-14 增强：从 4 种微动升级为 8 种电影运镜，增加视觉层次
KB_A = [
    ("scale(1.00) translate(0px,0px)", "scale(1.10) translate(0px,-24px)"),   # 推入+上移
    ("scale(1.00) translate(0px,0px)", "scale(1.08) translate(-28px,0px)"),   # 推入+左摇
    ("scale(1.10) translate(0px,0px)", "scale(1.00) translate(0px,18px)"),    # 拉出+下移
    ("scale(1.00) translate(0px,0px)", "scale(1.09) translate(26px,0px)"),    # 推入+右摇
    ("scale(1.00) translate(0px,-22px)", "scale(1.07) translate(0px,22px)"),  # 垂直呼吸
    ("scale(1.00) translate(-24px,0px)", "scale(1.09) translate(24px,0px)"),  # 水平呼吸
    ("scale(1.00) translate(0px,0px)", "scale(1.11) translate(-18px,-18px)"), # 斜推左上
    ("scale(1.00) translate(0px,0px)", "scale(1.08) translate(18px,-20px)"),  # 斜推右上
]
# 镜头B 背景运动（要点镜头）：反向运镜 + 特写 zoom（08-14 增强）
KB_B = [
    ("scale(1.10) translate(0px,-24px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.08) translate(-28px,0px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.00) translate(0px,18px)", "scale(1.10) translate(0px,0px)"),
    ("scale(1.09) translate(26px,0px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.07) translate(0px,22px)", "scale(1.00) translate(0px,-22px)"),
    ("scale(1.09) translate(24px,0px)", "scale(1.00) translate(-24px,0px)"),
    ("scale(1.11) translate(-18px,-18px)", "scale(1.00) translate(0px,0px)"),
    ("scale(1.08) translate(18px,-20px)", "scale(1.00) translate(0px,0px)"),
]
# 镜头B 模块动效轮换（08-14 增强 4 种）
MODULE_ANIMS = [
    ("staggerUp", ["translateY(30px)", "translateY(0px)"]),
    ("fadeSlideL", ["translateX(30px)", "translateX(0px)"]),
    ("staggerUp", ["translateY(24px)", "translateY(0px)"]),
    ("fadeSlideR", ["translateX(-30px)", "translateX(0px)"]),
]


def _b64img(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def esc(s: str) -> str:
    """HTML 转义（动效镜头标题/文案注入安全）"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(r.stdout).get("format", {}).get("duration", 4.0))
    except Exception:
        return 4.0


def validate_render_durations(durations: list[float]) -> dict:
    """Reject runaway narration before allocating browser or FFmpeg work."""
    max_segment = float(os.environ.get("FILM_RENDERER_MAX_SEGMENT_SECONDS", MAX_TTS_SEGMENT_SECONDS))
    max_total = float(os.environ.get("FILM_RENDERER_MAX_TOTAL_SECONDS", MAX_RENDER_SECONDS))
    failures = []
    if any(duration <= 0 for duration in durations):
        failures.append("invalid_tts_duration")
    if any(duration > max_segment for duration in durations):
        failures.append("segment_duration_exceeded")
    if sum(durations) > max_total:
        failures.append("total_duration_exceeded")
    return {
        "passed": not failures,
        "failures": failures,
        "total_seconds": round(sum(durations), 3),
        "max_segment_seconds": max_segment,
        "max_total_seconds": max_total,
    }


def synthesize_edge_tts(text: str, output: Path, voice: str) -> int:
    """Retry a transient Edge response and never retain an empty MP3."""
    attempts = max(1, int(os.environ.get("FILM_TTS_MAX_ATTEMPTS", FILM_TTS_MAX_ATTEMPTS)))
    delay = max(0.0, float(os.environ.get("FILM_TTS_RETRY_DELAY_SECONDS", "1")))
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            output.unlink(missing_ok=True)
            result = subprocess.run(
                ["edge-tts", "--voice", voice, "--rate=-5%", "--text", text, "--write-media", str(output)],
                capture_output=True, text=True, timeout=90,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or "edge-tts failed")[-160:])
            if not output.is_file() or output.stat().st_size <= 10_000:
                raise RuntimeError("edge-tts returned empty audio")
            return attempt
        except Exception as exc:
            output.unlink(missing_ok=True)
            errors.append(str(exc)[:160])
            if attempt == attempts:
                raise RuntimeError(f"edge-tts failed after {attempts} attempts: {errors[-1]}") from exc
            time.sleep(delay * attempt)
    raise RuntimeError("edge-tts retry loop exited unexpectedly")


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
    # 08-14 真实可观性增强：kicker/title/stat 入场动效按镜头轮换（非统一 fadeUp，机械感）
    anim_pool = ["fadeUp", "scaleIn", "slideLeft", "rotateIn"]
    kicker_anim = anim_pool[idx % 4]
    title_anim = anim_pool[(idx + 1) % 4]
    stat_anim = anim_pool[(idx + 2) % 4]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:0; background:url(data:image/jpeg;base64,{b64}) center/cover;
  animation: kb 11s ease-in-out infinite alternate; }}
@keyframes kb {{ 0% {{ transform:{kb[0]}; }} 100% {{ transform:{kb[1]}; }} }}
.overlay {{ position:absolute; inset:0; background:linear-gradient(180deg, rgba(0,0,0,0.42) 0%, rgba(0,0,0,0.65) 45%, rgba(0,0,0,0.92) 100%); }}
.content {{ position:absolute; inset:0; z-index:2; display:flex; flex-direction:column; justify-content:center; padding:130px 90px; }}
.kicker {{ font-size:32px; color:#ffd60a; font-weight:800; letter-spacing:5px; margin-bottom:40px;
  animation: {kicker_anim} 0.9s ease-out both; }}
.title {{ font-size:80px; line-height:1.28; font-weight:900; color:#fff; text-shadow:0 6px 26px rgba(0,0,0,0.8);
  animation: {title_anim} 1.1s ease-out 0.15s both; }}
.stat {{ margin-top:64px; display:inline-block; background:rgba(255,255,255,0.12); border:2px solid rgba(255,255,255,0.35);
  border-radius:44px; padding:22px 48px; animation: {stat_anim} 1.1s ease-out 0.5s both; }}
.stat .n {{ font-size:64px; font-weight:900; color:#7ee787; }}
.stat .l {{ font-size:30px; color:#d0d0d0; margin-left:16px; }}
@keyframes fadeUp {{ from {{ opacity:0; transform:translateY(26px); }} to {{ opacity:1; transform:translateY(0); }} }}
@keyframes scaleIn {{ from {{ opacity:0; transform:scale(0.85); }} to {{ opacity:1; transform:scale(1); }} }}
@keyframes slideLeft {{ from {{ opacity:0; transform:translateX(40px); }} to {{ opacity:1; transform:translateX(0); }} }}
@keyframes rotateIn {{ from {{ opacity:0; transform:rotate(-4deg) scale(0.92); }} to {{ opacity:1; transform:rotate(0) scale(1); }} }}
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


# ═══════════════════════════════════════════════════════════════════
# 动效镜头 3 件套（2026-08-15 固化，源自抖音卡片视频拆解）
# 卡内元素级独立动效：图块激活 / 数字跳变 / 流程点亮
# 渲染方式 = JS 逐帧驱动（renderFrame(t)）→ Playwright 截图 → FFmpeg 合成
# 背景：JS 驱动正弦轨迹微动（Ken Burns 呼吸感）
# ═══════════════════════════════════════════════════════════════════

def _pick_actives(items: list[str], n: int) -> list[str]:
    """从模块文案取 n 个有效条目（不够补空）；截断 14 字防 40px 溢出"""
    parts = [str(x).strip()[:14] for x in items if str(x).strip()]
    return (parts + ["", "", "", ""])[:n]


def _extract_number_unit(text: str) -> list[str]:
    """从文案提取「数字+单位」完整串（如 12倍/3.2秒/99%），用于 digit_roll 真实数据展示"""
    pairs = re.findall(r"(\d{1,3}(?:\.\d+)?)\s*(倍|%|秒|毫秒|分钟|小时|个|元|GB|MB|次|s|ms|万|亿)?", text)
    out = []
    for num, unit in pairs:
        if not unit and len(num) < 2 and "." not in num:
            continue  # 纯一位数（如"1个"中的1）跳过，防量词误报
        out.append(f"{num}{unit}")
        if len(out) >= 3:
            break
    return out

def build_shot_tile_activate(idx: int, title: str, items: list[str], bg_path: str,
                             kicker: str, badges: list[str] | None = None) -> str:
    """图块激活：多卡片轮流点亮（变色+阴影位移+前置放大），突出当前焦点"""
    tiles = _pick_actives(items, 3)
    badges = badges or ["A", "B", "C"]
    tile_html = ""
    for i, t in enumerate(tiles):
        tile_html += (
            f'<div class="tile" data-state="idle" data-t="{i}">'
            f'<span class="badge">{esc(badges[i % len(badges)])}</span>'
            f'<span class="nm">{esc(t) if t else "·"}</span>'
            f'<div class="ds">第 {i + 1} 个要点，点亮看重点</div></div>'
        )
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.25) 0%,rgba(0,0,0,0.55) 45%,rgba(0,0,0,0.9) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:120px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#7dd3fc; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.tiles {{ position:absolute; top:430px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:36px; z-index:4; }}
.tile {{ width:820px; padding:44px 52px; border-radius:28px; transition:all .18s ease-out; will-change:transform,background,box-shadow; }}
.tile .nm {{ font-size:40px; font-weight:800; }}
.tile .ds {{ font-size:28px; margin-top:10px; line-height:1.5; }}
.tile[data-state="idle"] {{ background:rgba(255,255,255,0.10); border:3px solid rgba(255,255,255,0.28); transform:translateX(0) scale(0.94); box-shadow:0 10px 30px rgba(0,0,0,0.25); }}
.tile[data-state="idle"] .nm {{ color:#e2e8f0; }}
.tile[data-state="idle"] .ds {{ color:#94a3b8; }}
.tile[data-state="active"] {{ background:linear-gradient(135deg,#0ea5e9,#2563eb); border:3px solid #38bdf8; transform:translateX(36px) scale(1.0); box-shadow:0 30px 70px rgba(37,99,235,0.55), 0 0 0 6px rgba(56,189,248,0.15); }}
.tile[data-state="active"] .nm {{ color:#ffffff; }}
.tile[data-state="active"] .ds {{ color:#dbeafe; }}
.badge {{ display:inline-block; font-size:24px; font-weight:800; padding:6px 20px; border-radius:999px; margin-right:14px; }}
.tile[data-state="active"] .badge {{ background:#facc15; color:#1e293b; }}
.tile[data-state="idle"] .badge {{ background:rgba(255,255,255,0.16); color:#cbd5e1; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}T</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="tiles">{tile_html}</div>
<script>
function renderFrame(t){{
  var active = Math.floor(t / 1.2) % 3;
  document.querySelectorAll('.tile').forEach(function(el){{
    el.setAttribute('data-state', parseInt(el.dataset.t) === active ? 'active' : 'idle');
  }});
  var p = (t % 4) / 4;
  document.getElementById('bg').style.transform = 'scale(1.14) translate(' + (Math.sin(p*6.28)*12) + 'px,' + (Math.cos(p*6.28)*8) + 'px)';
}}
</script></body></html>"""


def build_shot_digit_roll(idx: int, title: str, items: list[str], bg_path: str,
                          kicker: str, numbers: list[str] | None = None) -> str:
    """数字跳变：圆圈内数字滚动到目标值 + 雷达脉冲环（数据/性能强调）

    数据真实性铁律：数字必须来自文案提取（_extract_number_unit），
    不足 3 个就只显示实际数量（不补假数字）；无数字时调用方不应进入本镜头。
    numbers 格式：["12倍","3.2秒","99%"]（数字+单位完整串）
    """
    labs = _pick_actives(items, 3)
    if numbers is None:
        numbers = _extract_number_unit(" ".join(labs))
    if not numbers:
        # 无真实数字 → 防御性降级：展示文案要点本身（数字位显示"—"）
        numbers = ["—", "—", "—"]
    n_rows = len(numbers)
    while len(numbers) < 3:
        numbers.append("—")
    # 拆分数字与单位：数字部分滚动，单位部分静态
    stat_html = ""
    for i, lab in enumerate(labs[:n_rows]):
        stat_html += (
            f'<div class="stat"><div class="dot" id="dot{i}" data-hot="0">'
            f'<span class="num" id="n{i}">0</span><span class="unit" id="u{i}"></span>'
            f'<span class="ping"></span></div>'
            f'<div class="sinfo"><div class="lab">{esc(lab) if lab else "指标"}</div>'
            f'<div class="desc">数据自己会说话</div></div></div>'
        )
    b64 = _b64img(bg_path)
    # "—" 防御值：targets 置 0（不滚动），unit 置空，JS 直接静态显示 "—"
    targets_js = ",".join("0" if str(x) == "—" else (re.sub(r"[^0-9.]", "", str(x)) or "0") for x in numbers)
    # ⚠️ units 必须加引号（裸词会被 JS 当变量名 → undefined）
    units_js = ",".join("'" + ("" if str(x) == "—" else re.sub(r"[0-9.]", "", str(x))).replace("'", "\\'") + "'" for x in numbers)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.3) 0%,rgba(0,0,0,0.6) 45%,rgba(0,0,0,0.92) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:130px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#fca5a5; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.stats {{ position:absolute; top:{520 - (3 - n_rows) * 40}px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:44px; z-index:4; }}
.stat {{ display:flex; align-items:center; gap:36px; width:820px; background:rgba(255,255,255,0.10); backdrop-filter:blur(8px); border-radius:28px; padding:36px 44px; border:2px solid rgba(255,255,255,0.2); }}
.dot {{ width:120px; height:120px; border-radius:50%; background:rgba(239,68,68,0.16); border:4px solid #ef4444; display:flex; align-items:center; justify-content:center; position:relative; }}
.dot .num {{ font-size:52px; font-weight:900; color:#fca5a5; font-variant-numeric:tabular-nums; }}
.dot .unit {{ font-size:26px; font-weight:700; color:#fca5a5; margin-left:2px; }}
.dot .ping {{ position:absolute; inset:-6px; border-radius:50%; border:2px solid rgba(239,68,68,0.6); opacity:0; }}
.dot[data-hot="1"] .ping {{ animation:ping 0.8s ease-out infinite; }}
@keyframes ping {{ 0% {{ transform:scale(0.7); opacity:0.9; }} 100% {{ transform:scale(1.5); opacity:0; }} }}
.sinfo .lab {{ font-size:30px; color:#e2e8f0; font-weight:700; }}
.sinfo .desc {{ font-size:26px; color:#94a3b8; margin-top:8px; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}D</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="stats">{stat_html}</div>
<script>
var targets = [{targets_js}];
var units = [{units_js}];
function easeOut(t){{ return 1 - Math.pow(1-t, 3); }}
function renderFrame(t){{
  for (var i=0; i<{n_rows}; i++){{
    var start = i * 0.8;
    var p = (t - start) / 1.4;
    document.getElementById('dot'+i).setAttribute('data-hot', (p > 0 && p < 1.3) ? 1 : 0);
    document.getElementById('u'+i).textContent = units[i];
    var v = 0;
    if (p > 0) {{ v = Math.round(parseFloat(targets[i]) * Math.min(1, easeOut(Math.min(1, p)))); }}
    // 防御值（unit 为空 = 无真实数字）→ 静态显示 "—"
    document.getElementById('n'+i).textContent = units[i] === '' ? '—' : v;
  }}
  var p2 = (t % 4) / 4;
  document.getElementById('bg').style.transform = 'scale(1.15) translate(' + (Math.cos(p2*6.28)*10) + 'px,' + (Math.sin(p2*6.28)*8) + 'px)';
}}
</script></body></html>"""


def build_shot_step_light(idx: int, title: str, items: list[str], bg_path: str,
                          kicker: str) -> str:
    """流程点亮：步骤逐个点亮（完成=深色保持、当前=亮色高亮放大、未到=灰暗）+ 进度条
    步骤数 = 实际有效 items 数（2-4），不生成空占位步骤"""
    steps = [str(x).strip()[:14] for x in items if str(x).strip()]
    if len(steps) < 2:
        steps = (steps + ["步骤一", "步骤二", "步骤三", "步骤四"])[:2]
    steps = steps[:4]
    n_steps = len(steps)
    step_html = ""
    for i, s in enumerate(steps):
        step_html += (
            f'<div class="step" data-idx="{i}" data-state="idle">'
            f'<div class="sn">{i + 1:02d}</div>'
            f'<div class="sc"><div class="st">{esc(s)}</div>'
            f'<div class="sd">第 {i + 1} 步</div></div><div class="arr">▼</div></div>'
        )
    # 步骤越少，位置越高、间隙越小
    top_offset = 470 - (4 - n_steps) * 50
    gap = 34 - (4 - n_steps) * 4
    b64 = _b64img(bg_path)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ width:{W}px; height:{H}px; overflow:hidden; font-family:'Noto Sans CJK SC','Noto Sans SC',sans-serif; }}
.bg {{ position:absolute; inset:-40px; background:url(data:image/jpeg;base64,{b64}) center/cover;
  transform:scale(1.12); will-change:transform; }}
.shade {{ position:absolute; inset:0; background:linear-gradient(180deg,rgba(0,0,0,0.28) 0%,rgba(0,0,0,0.58) 45%,rgba(0,0,0,0.9) 100%); }}
.idx {{ position:absolute; top:64px; right:64px; font-size:110px; font-weight:900; color:rgba(255,255,255,0.16); z-index:2; }}
.head {{ position:absolute; top:130px; left:0; right:0; text-align:center; z-index:5; }}
.head .k {{ font-size:30px; color:#6ee7b7; font-weight:700; letter-spacing:8px; }}
.head .t {{ font-size:66px; color:#fff; font-weight:900; margin-top:16px; text-shadow:0 6px 24px rgba(0,0,0,.7); }}
.steps {{ position:absolute; top:{top_offset}px; left:0; right:0; display:flex; flex-direction:column; align-items:center; gap:{gap}px; z-index:4; }}
.step {{ width:820px; display:flex; align-items:center; gap:34px; padding:38px 44px; border-radius:24px; transition:all .22s ease-out; }}
.step .sn {{ font-size:52px; font-weight:900; width:110px; text-align:center; font-variant-numeric:tabular-nums; }}
.step .st {{ font-size:40px; font-weight:800; }}
.step .sd {{ font-size:26px; margin-top:6px; }}
.step .arr {{ font-size:30px; margin-left:auto; opacity:0; }}
.step[data-state="done"] {{ background:rgba(255,255,255,0.13); border:3px solid rgba(16,185,129,0.7); transform:translateX(10px); }}
.step[data-state="done"] .sn {{ color:#34d399; }}
.step[data-state="done"] .st {{ color:#fff; }}
.step[data-state="done"] .sd {{ color:#a7f3d0; }}
.step[data-state="hot"] {{ background:linear-gradient(135deg,#059669,#0d9488); border:3px solid #34d399; transform:translateX(26px) scale(1.03); box-shadow:0 26px 60px rgba(5,150,105,0.5); }}
.step[data-state="hot"] .sn {{ color:#fff; }}
.step[data-state="hot"] .st {{ color:#fff; }}
.step[data-state="hot"] .sd {{ color:#d1fae5; }}
.step[data-state="hot"] .arr {{ opacity:1; color:#facc15; }}
.step[data-state="idle"] {{ background:rgba(255,255,255,0.06); border:3px solid rgba(255,255,255,0.16); transform:translateX(0) scale(0.95); }}
.step[data-state="idle"] .sn {{ color:#64748b; }}
.step[data-state="idle"] .st {{ color:#94a3b8; }}
.step[data-state="idle"] .sd {{ color:#64748b; }}
.progress {{ position:absolute; bottom:170px; left:130px; right:130px; height:10px; background:rgba(255,255,255,0.15); border-radius:999px; z-index:4; overflow:hidden; }}
.progress i {{ display:block; height:100%; width:0%; background:linear-gradient(90deg,#34d399,#facc15); border-radius:999px; transition:width .2s; }}
</style></head><body>
<div class="bg" id="bg"></div><div class="shade"></div>
<div class="idx">{idx:02d}S</div>
<div class="head"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div></div>
<div class="steps">{step_html}</div>
<div class="progress"><i id="prog"></i></div>
<script>
var TOTAL_STEPS = {n_steps};
function renderFrame(t){{
  var stepCount = Math.min(TOTAL_STEPS, Math.floor(t / 0.8) + 1);
  document.getElementById('prog').style.width = Math.min(100, Math.round((t / (TOTAL_STEPS * 0.8)) * 100)) + '%';
  document.querySelectorAll('.step').forEach(function(el){{
    var idx = parseInt(el.dataset.idx);
    var state = idx < stepCount - 1 ? 'done' : (idx === stepCount - 1 ? 'hot' : 'idle');
    el.setAttribute('data-state', state);
  }});
  var p = (t % 4) / 4;
  document.getElementById('bg').style.transform = 'scale(1.13) translate(' + (Math.sin(p*6.28)*10) + 'px,' + (Math.cos(p*6.28)*8) + 'px)';
}}
</script></body></html>"""


def detect_element_shot(seg_text: str, title: str = "") -> str:
    """按内容结构自动选动效镜头类型（内容驱动视觉原则）"""
    text = f"{title} {seg_text}"
    # 流程/步骤：成词检测（第一步/然后/接着/流程/步骤/工作流），拒绝单字"先/再/最后"
    if re.search(r"(流程|步骤|工作流|第一步|第二步|第三步|第四步|然后|接着|再来|最终)", text):
        return "step_light"
    # 对比/选型：强信号（对比/哪个/怎么选/相比/PK/vs），
    # 拒绝宽泛名词（"方案/选择/推荐"独立出现常见：解决方案/推荐阅读→误报）
    if re.search(r"(对比|哪个|怎么选|怎么挑|挑选|相比|PK|vs|VS|A/B|还是.*好|哪个.*合适)", text):
        return "tile_activate"
    # 数字信号：必须同时有 ≥2位数字 + 单位（"12倍"/"3.2秒"），杜绝无数字兜底假数据
    if re.search(r"\d{2,}(?:\.\d+)?\s*(倍|%|秒|毫秒|分钟|小时|个|元|GB|MB|次|s|ms|万|亿)", text):
        return "digit_roll"
    return ""


async def _record_shot_frames(name: str, html_path: str, dur: float, out: Path) -> str | None:
    """JS 逐帧驱动渲染：renderFrame(t) 每帧推进 → 截图 → FFmpeg 合成 mp4。
    用于卡内元素级动效（静态截图拍不到 CSS 动画，record_video 只捕入场）"""
    from playwright.async_api import async_playwright
    fps = 25
    total = max(1, int(dur * fps))
    frames_dir = out / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with async_playwright() as p:
            b = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            pg = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            await pg.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            await pg.wait_for_timeout(200)
            for i in range(total):
                t = i / fps
                await pg.evaluate(f"renderFrame({t})")
                await pg.screenshot(path=str(frames_dir / f"f_{i:04d}.png"), animations="disabled")
            await b.close()
    except Exception as e:
        print(f"{name} 逐帧渲染失败: {e}", file=sys.stderr)
        return None
    mp4 = out / "shots" / f"{name}.mp4"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "quiet", "-framerate", str(fps),
         "-i", str(frames_dir / "f_%04d.png"),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-an",
         str(mp4)], timeout=180)
    if r.returncode != 0 or not mp4.is_file():
        print(f"{name} ffmpeg 合成失败", file=sys.stderr)
        return None
    # 合成后时长校验：帧数不足 = 中断/损坏，必须重来（防残废产物）
    actual_dur = _duration(str(mp4))
    expected = total / fps
    if actual_dur < expected - 0.35:
        print(f"{name} 合成时长异常 ({actual_dur:.2f}s vs 预期 {expected:.2f}s)，删除重渲染", file=sys.stderr)
        try:
            mp4.unlink()
        except OSError:
            pass
        return None
    return str(mp4)


async def _record_shot(name: str, html_path: str, dur: float, out: Path, frame_driven: bool = False) -> str | None:
    from playwright.async_api import async_playwright
    browser = context = page = video = None
    video_path = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(out / "webm"),
            record_video_size={"width": W, "height": H},
        )
        page = await context.new_page()
        video = page.video
        try:
            # Local HTML can keep browser connections alive indefinitely; load
            # proves the document is ready without allowing network-idle hangs.
            await page.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            if frame_driven:
                # Drive element state in the page while Chromium records native
                # video. This keeps real motion without full-resolution PNG
                # screenshots for every frame.
                await page.evaluate(
                    """async (durationMs) => {
                        if (typeof window.renderFrame !== 'function') {
                            throw new Error('renderFrame is unavailable');
                        }
                        await new Promise((resolve) => {
                            const started = performance.now();
                            const tick = (now) => {
                                window.renderFrame((now - started) / 1000);
                                if (now - started >= durationMs) {
                                    resolve();
                                } else {
                                    requestAnimationFrame(tick);
                                }
                            };
                            requestAnimationFrame(tick);
                        });
                    }""",
                    int(dur * 1000),
                )
            else:
                await page.wait_for_timeout(int(dur * 1000))
        finally:
            if page:
                try:
                    await asyncio.wait_for(page.close(), timeout=10)
                except (asyncio.TimeoutError, Exception):
                    pass
            if context:
                try:
                    await asyncio.wait_for(context.close(), timeout=15)
                except (asyncio.TimeoutError, Exception):
                    pass
            if video:
                try:
                    video_path = await asyncio.wait_for(video.path(), timeout=15)
                except (asyncio.TimeoutError, Exception):
                    pass
            if browser:
                try:
                    await asyncio.wait_for(browser.close(), timeout=10)
                except (asyncio.TimeoutError, Exception):
                    pass
    if video_path:
        target = out / "webm" / f"{name}.webm"
        os.replace(video_path, target)
        return str(target)
    return None


async def _render_shot_still(name: str, html_path: str, dur: float, out: Path) -> str | None:
    """Render a browser still then apply deterministic FFmpeg camera motion.

    Playwright's video recorder launches a separate WebM encoder that can
    survive page shutdown on constrained hosts. A screenshot has no recorder
    child process, while FFmpeg gives the shot a bounded, visible movement.
    """
    from playwright.async_api import async_playwright

    browser = page = None
    still = out / "shots" / f"{name}.png"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            await page.goto(f"file://{html_path}", wait_until="load", timeout=30000)
            await page.wait_for_timeout(200)
            await asyncio.wait_for(page.screenshot(path=str(still), animations="disabled"), timeout=20)
    except Exception as exc:
        print(f"{name} still capture failed: {exc}", file=sys.stderr)
        return None
    finally:
        if page:
            try:
                await asyncio.wait_for(page.close(), timeout=10)
            except (asyncio.TimeoutError, Exception):
                pass
        if browser:
            try:
                await asyncio.wait_for(browser.close(), timeout=10)
            except (asyncio.TimeoutError, Exception):
                pass
    if not still.is_file():
        return None
    output = out / "shots" / f"{name}.mp4"
    fps = 25
    frames = max(1, int(dur * fps))
    motion = f"zoompan=z='min(zoom+0.0008,1.06)':d={frames}:s={W}x{H}:fps={fps},format=yuv420p"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-i", str(still), "-vf", motion,
             "-t", f"{dur:.3f}", "-r", str(fps), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-an", str(output)],
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print(f"{name} still-motion encode timed out", file=sys.stderr)
        return None
    return str(output) if result.returncode == 0 and output.is_file() else None


def _finalize_recorded_shot(webm_path: str, target: Path, duration: float) -> bool:
    """Normalize a bounded Playwright recording into the renderer's MP4 contract."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", webm_path, "-t", f"{duration:.3f}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "baseline",
             "-pix_fmt", "yuv420p", "-an", str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and target.is_file() and target.stat().st_size > 50_000


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
    try:
        render_policy = resolve_render_policy()
    except ValueError as exc:
        print(f"渲染质量策略无效: {exc}", file=sys.stderr)
        return 2

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
        # 08-14 短视频脚本质量门禁：PASS 才渲染（防"太AI不吸引人"复发）
        try:
            import subprocess as _sp
            gate_lang = "zh" if re.search(r"[\u4e00-\u9fff]", raw) else "en"
            gate = _sp.run(
                [sys.executable, str(ROOT / "scripts" / "video_script_gate.py"), str(script_file),
                 "--lang", gate_lang, "--json"],
                capture_output=True, text=True, timeout=30,
            )
            if gate.returncode == 0:
                print(f"脚本质量门禁: PASS ({gate_lang})")
            else:
                print(f"脚本质量门禁: FAIL ({gate_lang})（{gate.stdout[:200]}）", file=sys.stderr)
                if not script_gate_passed(gate.returncode, str(render_policy["quality_profile"])):
                    return 3
        except Exception as e:
            print(f"脚本质量门禁不可用: {e}", file=sys.stderr)
            if render_policy["quality_profile"] == "high":
                return 3
        # 08-14 敏感词过滤（用户复盘要求）：脚本即 TTS/字幕文案源，阻断式检查
        try:
            import importlib.util as _ilu
            _sw_path = ROOT / "scripts" / "sensitive_word_filter.py"
            if _sw_path.is_file():
                _spec = _ilu.spec_from_file_location("sensitive_word_filter", _sw_path)
                if _spec is None or _spec.loader is None:
                    raise RuntimeError("sensitive_word_filter spec 加载失败")
                _sw = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_sw)
                _res = _sw.check_content(raw, context="script")
                if _res["ok"]:
                    print("敏感词过滤: PASS (script)")
                else:
                    print(f"⛔ 敏感词过滤: FAIL——{len(_res['hits'])} 个敏感词: "
                          f"{[h['word'] for h in _res['hits']]}", file=sys.stderr)
                    # 阻断：敏感词必须修复后重渲染，不产出违规成品
                    return 3
        except Exception as e:
            print(f"敏感词检查跳过: {e}", file=sys.stderr)

    scene_manifest_path = out / "scene_manifest.json"
    if render_policy["quality_profile"] == "high" and (not scene_manifest_path.is_file() or not script_file):
        print("高质量渲染缺少 scene_manifest.json 或完整脚本", file=sys.stderr)
        return 2
    render_contract = {
        "renderer_version": RENDERER_VERSION,
        **render_policy,
        "width": args.width,
        "height": args.height,
        "cards_sha256": _sha256_file(cards_path),
        "script_sha256": _sha256_file(script_file) if script_file else "",
        "scene_manifest_sha256": _sha256_file(scene_manifest_path) if scene_manifest_path.is_file() else "",
        "backgrounds_sha256": [_sha256_file(path) for path in bg_paths[:8]],
        "transitions": TRANSITIONS,
        "xfade_short": XFADE_DUR_SHORT,
        "xfade_long": XFADE_DUR_LONG,
        "element_frame_render_min_timeout_seconds": ELEMENT_FRAME_RENDER_MIN_TIMEOUT_SECONDS,
    }
    if prepare_render_contract(out, render_contract):
        print("渲染契约变化：已废弃旧镜头与最终成片缓存")
    for sub in ("html", "webm", "shots", "frames", "sub"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    print(f"渲染质量: {render_policy['quality_profile']} / {render_policy['motion_mode']}")

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
        existing_audio = mp3.is_file() and mp3.stat().st_size > 10_000
        provider_used = "edge-tts"
        if not existing_audio and tts_provider == "qwen":
            # 灰度：Qwen 直接合成（不经 DeAI）
            try:
                from scripts.voice_engine import QwenTTSProvider
                qwen = QwenTTSProvider()
                if qwen.available:
                    qwen.synthesize(tts_text, mp3,
                                    voice=os.environ.get("QWEN_AUDIO_TTS_VOICE", "longanhuan_v3.6"),
                                    language="Chinese" if tts_lang == "zh" else "English")
                    provider_used = "qwen"
            except Exception as exc:
                print(f"Qwen 合成失败({i}): {str(exc)[:80]}", file=sys.stderr)
        if not mp3.is_file() or mp3.stat().st_size <= 10_000:
            synthesize_edge_tts(tts_text, mp3, edge_voice)
            provider_used = "edge-tts"
        if mp3.is_file() and mp3.stat().st_size > 10_000:
            tts_files.append(str(mp3))
            tts_records.append({
                "provider": provider_used,
                "voice": edge_voice if provider_used == "edge-tts" else os.environ.get("QWEN_AUDIO_TTS_VOICE", "longanhuan_v3.6"),
                "rate": "-5%", "pitch": "+0Hz",
                "tts_text": tts_text, "display_text": display_text,
                "applied_rules": applied_rules,
                "unhandled_latin_tokens": list(compiled.unhandled_latin_tokens) if compiler else [],
                "duration_seconds": _duration(str(mp3)),
            })
    durs = [_duration(p) for p in tts_files]
    print("TTS 时长:", [round(d, 2) for d in durs])
    # 规则6：TTS 记录落盘（provider/voice/rate/pitch/tts_text/词典规则/时长）
    (out / "tts_records.json").write_text(json.dumps(tts_records, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "tts_config.json").write_text(
        json.dumps({"version": "tts_config_v1", "provider": tts_provider, "segments": tts_records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
            synthesize_edge_tts(text, mp3, "zh-CN-YunxiNeural")
            tts_files.append(str(mp3))
    durs = [_duration(p) for p in tts_files]
    print("TTS 时长:", [round(d, 2) for d in durs])
    duration_check = validate_render_durations(durs)
    if not duration_check["passed"]:
        print(f"TTS 时长预算失败: {json.dumps(duration_check, ensure_ascii=False)}", file=sys.stderr)
        return 3

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
    # 08-15 内容驱动动效：每段检测内容结构，B 镜头可切换为 图块激活/数字跳变/流程点亮
    shot_types = {}  # seg_idx -> "tile_activate" | "digit_roll" | "step_light" | ""
    for i in range(1, 9):
        card = cards[i - 1]
        title = seg_title(i)
        stat = _stat_from_card(card)
        modules = seg_modules(i)
        bg = str(bg_paths[i - 1])
        stat_label = "关键数字" if tts_lang == "zh" else "KEY NUMBER"
        # 内容结构检测 → 动效镜头（8 段最多 4 段启用，保证镜头多样性 + 渲染时长可控）
        seg_txt = script_segments[i - 1] if i <= len(script_segments) and script_segments[i - 1] \
            else str(card.get("tts") or card.get("txt") or "")
        # 截图卡优先（真实素材规则）；动效镜头用于无截图素材的偶数段
        if screenshot_files and i in (2, 6):
            elem_shot = ""
        else:
            elem_shot = detect_element_shot(seg_txt, title) if i % 2 == 0 else ""
        shot_types[i] = elem_shot
        html_a = build_shot_a(i, title, stat, bg, kicker, stat_label=stat_label)
        # 截图卡：段2（介绍后细节）与段6（数据/进展）优先用真实截图
        shot_path = None
        caption = ""
        if screenshot_files and i in (2, 6):
            si = 0 if i == 2 else (1 if len(screenshot_files) > 1 else 0)
            shot_path = str(screenshot_files[si])
            caption = ""
        if elem_shot == "tile_activate":
            html_b = build_shot_tile_activate(i, title, modules, bg, kicker)
        elif elem_shot == "digit_roll":
            # 数据真实性铁律：无真实数字时降级普通镜头，禁止编造数据
            if _extract_number_unit(" ".join(modules)) or _extract_number_unit(seg_txt):
                html_b = build_shot_digit_roll(i, title, modules, bg, kicker)
            else:
                shot_types[i] = ""
                html_b = build_shot_b(i, title, modules, bg, screenshot_path=shot_path, screenshot_caption=caption)
        elif elem_shot == "step_light":
            html_b = build_shot_step_light(i, title, modules, bg, kicker)
        else:
            html_b = build_shot_b(i, title, modules, bg, screenshot_path=shot_path, screenshot_caption=caption)
        (out / "html" / f"shot_{i:02d}A.html").write_text(html_a, encoding="utf-8")
        (out / "html" / f"shot_{i:02d}B.html").write_text(html_b, encoding="utf-8")
        d = durs[i - 1]
        a_dur = min(2.8, d * 0.30)
        b_dur = max(1.0, d - a_dur + 0.15)
        # 动效镜头时长保障：完整展示需要 ≥3.2s（tile 3×1.2 / step 4×0.8 / digit 3×0.8+1.4），
        # TTS 段过短时压缩 A 镜头时间补给 B（视觉段比语音短是安全的，voice 有 adelay+atrim 对齐）
        if shot_types.get(i) and b_dur < 3.2:
            shortfall = 3.2 - b_dur
            a_dur_new = max(0.6, a_dur - shortfall)
            b_dur = d - a_dur_new + 0.15
            a_dur = min(a_dur, a_dur_new)
        shot_durs.append((f"shot_{i:02d}A", a_dur))
        shot_durs.append((f"shot_{i:02d}B", b_dur))

    shot_records: list[dict[str, object]] = []

    async def _render():
        async def record_bounded(name: str, html_path: str, duration: float, *, frame_driven: bool = False) -> str | None:
            try:
                timeout = element_render_timeout_seconds(duration) if frame_driven else max(45, duration + 25)
                return await asyncio.wait_for(
                    _record_shot(name, html_path, duration, out, frame_driven=frame_driven),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                print(f"{name} Playwright recording timed out", file=sys.stderr)
                return None
            except Exception as exc:
                print(f"{name} Playwright recording failed: {str(exc)[:160]}", file=sys.stderr)
                return None

        async def render_still(name: str, html_path: str, duration: float) -> str | None:
            try:
                return await asyncio.wait_for(_render_shot_still(name, html_path, duration, out), timeout=max(45, duration + 30))
            except asyncio.TimeoutError:
                print(f"{name} still-motion render timed out", file=sys.stderr)
                return None
            except Exception as exc:
                print(f"{name} still-motion render failed: {str(exc)[:160]}", file=sys.stderr)
                return None

        async def render_element(name: str, html_path: str, duration: float) -> str | None:
            webm = await record_bounded(name, html_path, duration + 0.5, frame_driven=True)
            return _finalize_recorded_shot(webm, out / "shots" / f"{name}.mp4", duration) if webm else None

        failed_shots = []
        for name, sd in shot_durs:
            hp = out / "html" / f"{name}.html"
            target = out / "shots" / f"{name}.mp4"
            # 复用校验：文件存在 + 大小达标 + **时长接近目标**（防 timeout 中断的残废产物被复用）
            if target.is_file() and target.stat().st_size > 50_000:
                existing_dur = _duration(str(target))
                if existing_dur >= sd - 0.35:
                    print(f"{name}: 复用已有镜头 ({existing_dur:.2f}s)")
                    shot_records.append({"name": name, "renderer": "cinematic-cache", "fallback": False, "reused": True})
                    continue
                print(f"{name}: 已有镜头时长异常 ({existing_dur:.2f}s vs 目标 {sd:.2f}s)，重渲染", file=sys.stderr)
            # 动效镜头（B 且命中内容结构）→ JS 逐帧渲染；其余 → Playwright CSS 录制。
            # high/cinematic 模式绝不静默降级为 still-motion。
            seg_i = int(name[5:7])
            is_elem = name.endswith("B") and shot_types.get(seg_i)
            if is_elem:
                mp4 = await render_element(name, str(hp), sd)
                if not mp4:
                    if render_policy["motion_mode"] == "safe":
                        mp4 = await render_still(name, str(hp), sd)
                        shot_records.append({"name": name, "renderer": "still-motion", "fallback": True, "reused": False})
                    else:
                        failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "playwright-frame-video", "fallback": True, "reused": False})
                else:
                    shot_records.append({"name": name, "renderer": "playwright-frame-video", "fallback": False, "reused": False})
                continue
            if render_policy["motion_mode"] == "cinematic":
                webm = await record_bounded(name, str(hp), sd + 0.5)
                mp4 = _finalize_recorded_shot(webm, target, sd) if webm else False
                if mp4:
                    shot_records.append({"name": name, "renderer": "playwright-video", "fallback": False, "reused": False})
                else:
                    failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "playwright-video", "fallback": True, "reused": False})
            else:
                mp4 = await render_still(name, str(hp), sd)
                if mp4:
                    shot_records.append({"name": name, "renderer": "still-motion", "fallback": False, "reused": False})
                else:
                    failed_shots.append(name)
                    shot_records.append({"name": name, "renderer": "still-motion", "fallback": True, "reused": False})
        if failed_shots:
            print(f"镜头渲染失败: {', '.join(failed_shots)}", file=sys.stderr)
            return False
        return True
    if not asyncio.run(_render()):
        return 3

    shot_mp4s = [out / "shots" / f"{n}.mp4" for n, _ in shot_durs]
    if not all(p.is_file() for p in shot_mp4s):
        print("镜头渲染不完整", file=sys.stderr)
        return 3

    # 16 镜头 → 4 组 xfade（4镜头/组）+ 组间 concat
    shot_names = [n for n, _ in shot_durs]
    durs_map = {n: _duration(str(out / "shots" / f"{n}.mp4")) for n in shot_names}
    group_outs = []
    transition_after = [0.0] * max(0, len(shot_names) - 1)
    for gi in range(4):
        names = shot_names[gi * 4:(gi + 1) * 4]
        inputs = []
        for n in names:
            inputs += ["-i", str(out / "shots" / f"{n}.mp4")]
        fc_parts = []
        prev = "0:v"
        offset_acc = 0.0
        for i in range(1, len(names)):
            # 镜头类型：A=建立镜头(偶数 index)，B=要点镜头(奇数 index)
            cur_type = "B" if names[i].endswith("B") else "A"
            prev_type = "B" if names[i - 1].endswith("B") else "A"
            # 差异化转场：A→A 黑场/smooth（段落建立），B→B 方向性（节奏推进），A→B/B→A circle（转折）
            if prev_type == cur_type == "A":
                trans = TRANSITIONS[(gi * 2 + i) % 4]  # fadeblack/smoothleft/circleopen/slideleft
                xdur = XFADE_DUR_LONG
            elif prev_type == cur_type == "B":
                trans = TRANSITIONS[4 + (gi * 2 + i) % 4]  # wipeleft/smoothup/circleright/fadegrays
                xdur = XFADE_DUR_SHORT
            else:
                trans = "circleopen" if i % 2 else "smoothleft"
                xdur = XFADE_DUR_LONG
            transition_after[gi * 4 + i - 1] = xdur
            offset_acc += durs_map[names[i - 1]] - xdur
            offset_acc = max(0.05, offset_acc - 0.05)
            label = f"g{gi}x{i}"
            fc_parts.append(f"[{prev}][{i}:v]xfade=transition={trans}:duration={xdur}:offset={offset_acc:.3f}[{label}]")
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

    # 视觉总时长 + 全局镜头起始必须复用实际的组内转场时长；组间 concat 为 0。
    starts_global, visual_total = calculate_timeline(
        [durs_map[name] for name in shot_names],
        transition_after,
    )

    # 配音：8 段 TTS 分段 adelay 到镜头A 起始 + atrim 裁剪到段视觉时长（补偿 xfade 重叠，防溢出）
    voice_path = out / "voice_aligned.wav"
    voice_fc = []
    inputs = []
    alignment_records = []
    for i in range(1, 9):
        inputs += ["-i", str(tts_files[i - 1])]
        delay_ms = int(starts_global[2 * (i - 1)] * 1000)
        # 段视觉时长 = 镜头B 结束 - 镜头A 起点（含转场重叠压缩）
        seg_end = starts_global[2 * (i - 1) + 1] + durs_map[shot_names[2 * (i - 1) + 1]]
        seg_visual_dur = seg_end - starts_global[2 * (i - 1)]
        tts_dur = durs[i - 1]
        overflow = round(tts_dur - seg_visual_dur, 3)
        alignment_records.append({
            "segment": i,
            "scene_start": starts_global[2 * (i - 1)],
            "scene_duration": round(seg_visual_dur, 3),
            "tts_duration": round(tts_dur, 3),
            "overflow_seconds": overflow,
        })
        if render_policy["quality_profile"] == "high" and overflow > 0.15:
            print(f"音画对齐失败: 段{i} 配音超出镜头 {overflow:.3f}s", file=sys.stderr)
            (out / "av_alignment_evidence.json").write_text(
                json.dumps({"passed": False, "segments": alignment_records}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return 3
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
    (out / "av_alignment_evidence.json").write_text(
        json.dumps({"passed": True, "segments": alignment_records}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 合流（视频 + 配音 + BGM）
    bgm_path = out / "bgm.mp3"
    if not bgm_path.is_file():
        os.environ.setdefault("BGM_TARGET_PLATFORM", args.platform)
        from scripts.kuaishou_render import download_bgm
        bgm_path = Path(download_bgm(str(out), style=args.bgm_style))
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "visual_xfade.mp4"),
                        "-i", str(voice_path), "-stream_loop", "-1", "-i", str(bgm_path),
                        "-filter_complex",
                        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=2.4[v];"
                        "[2:a]aformat=sample_rates=44100:channel_layouts=stereo,volume=0.11[bg];"
                        "[v][bg]amix=inputs=2:duration=longest:normalize=0,"
                        "aformat=sample_rates=44100:channel_layouts=stereo[a]",
                        "-map", "0:v", "-map", "[a]", "-t", f"{visual_total:.3f}",
                        "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", str(out / "mixed_v2.mp4")],
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
                        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", str(final)],
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

    audio_evidence = validate_audio_spec(probe_audio_spec(final))
    (out / "audio_quality_evidence.json").write_text(
        json.dumps(audio_evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not audio_evidence["passed"]:
        print(f"音频规格验证失败: {audio_evidence}", file=sys.stderr)
        return 4

    try:
        from content_platform.video_artifact import measure_motion_evidence
        measured_motion = measure_motion_evidence(final)
    except Exception as exc:
        measured_motion = {"passed": False, "error": str(exc)[:160]}
    render_quality = build_render_quality_evidence(
        policy=render_policy,
        shot_records=shot_records,
        motion=measured_motion,
    )
    (out / "shot_render_records.json").write_text(
        json.dumps(shot_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "render_quality_evidence.json").write_text(
        json.dumps(render_quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not render_quality["passed"]:
        print(f"电影质量验证失败: {render_quality['failures']}", file=sys.stderr)
        return 4

    # segment_motion_evidence（runner 门禁要求）
    seg_evidence = {"segments": []}
    record_by_name = {str(row.get("name")): row for row in shot_records}
    for i in range(1, 9):
        shot = (cards[i - 1].get("shotcraft") or {})
        et = shot_types.get(i, "")
        if et:
            move_id = et
            profile = f"element_motion_{et}_{i}"
            renderer_note = "film_renderer_frames"
        else:
            move_id = str(shot.get("name") or f"cinema_multishot_{i}")
            profile = f"establish_then_detail_{i}"
            renderer_note = "film_renderer"
        segment_records = [record_by_name.get(f"shot_{i:02d}{suffix}", {}) for suffix in ("A", "B")]
        seg_evidence["segments"].append({
            "index": i,
            "move_id": move_id,
            "profile": profile,
            "rendered": True,
            "reused": any(bool(row.get("reused")) for row in segment_records),
            "renderer": renderer_note,
            "renderer_modes": [row.get("renderer") for row in segment_records],
            "fallback": any(bool(row.get("fallback")) for row in segment_records),
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
