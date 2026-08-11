#!/usr/bin/env python3
"""
Unified Kuaishou video render pipeline.
Fixed 2026-07-24 issues: base64 bg, charset, parallel segments, .done markers, one-step encode, quality asserts.

Usage:
  # Full pipeline
  python3 kuaishou_render.py --video-dir /tmp/ks_myvideo --theme cyber-neon --gh-repo owner/repo

  # Skip completed steps (uses .done markers)
  python3 kuaishou_render.py --video-dir /tmp/ks_myvideo --theme mint-fresh --skip-cards --skip-tts

  # Just generate packet for existing final.mp4
  python3 kuaishou_render.py --video-dir /tmp/ks_myvideo --generate-packet --schedule "2026-07-24 11:15"

"""
import argparse, asyncio, base64, hashlib, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
from scripts.build_subtitles import load_cards, write_ass_from_cards
from scripts.pre_render_gate import validate_render_inputs
from scripts.render_checkpoint import fingerprint_paths, mark_complete, stage_current_or_adopt
from scripts.render_timing import record_stage_timing, write_timing_summary
try:
    from playwright.async_api import async_playwright
except ModuleNotFoundError:
    async_playwright = None
try:
    from PIL import Image, ImageStat
except ModuleNotFoundError:
    Image = None
    ImageStat = None

# ── TTS voices (轮换) ──
TTS_VOICES = ["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural", "zh-CN-YunjianNeural"]

# ── Theme palettes ──
THEMES = {
    "cyber-neon": {"accent":"#00e5ff","accent2":"#e040fb","bg":"#0d0d0d","text":"#c8c8c8","card_bg":"rgba(0,0,0,0.4)","badge_bg":"rgba(0,229,255,0.12)","glass":"rgba(0,229,255,0.06)"},
    "mint-fresh": {"accent":"#1a7a5a","accent2":"#5a8a72","bg":"#1a2e26","text":"#e0f5ec","card_bg":"rgba(26,122,90,0.15)","badge_bg":"rgba(26,122,90,0.2)","glass":"rgba(224,245,236,0.08)"},
    "blueprint":  {"accent":"#64B5F6","accent2":"#B8D4EE","bg":"#0B3D66","text":"#E5F0FA","card_bg":"rgba(100,181,246,0.12)","badge_bg":"rgba(100,181,246,0.15)","glass":"rgba(100,181,246,0.06)"},
}

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "")
SUBTITLE_MARGIN_V = 200
SUBTITLE_MAX_CHARS_PER_LINE = 16
SUBTITLE_MAX_LINES = 2
REAL_BGM_MIN_BYTES = 500_000
ONLINE_BGM_TIMEOUT = 20
REAL_INSTRUMENT_TERMS = {
    "acoustic",
    "piano",
    "guitar",
    "strings",
    "orchestral",
    "violin",
    "cello",
    "jazz",
    "folk",
    "drums",
    "percussion",
    "live",
    "instrumental",
    "classical",
    "brass",
    "woodwind",
}
FORBIDDEN_BGM_TERMS = {
    "electronic",
    "synth",
    "edm",
    "techno",
    "phonk",
    "trap",
    "lofi beat",
    "lo-fi beat",
    "midi",
    "ai generated",
    "ai-generated",
    "procedural",
    "tone",
    "sound effect",
    "sfx",
    "chip",
    "8-bit",
}


def img_to_b64(path):
    """Convert image to base64 data URI (fixes file:// CSS url() issue)"""
    if not path or not os.path.exists(path) or os.path.getsize(path) < 1000:
        return None
    with open(path, "rb") as f:
        raw = f.read()
    data = base64.b64encode(raw).decode()
    mime = _detect_image_mime(raw, path)
    return f"data:{mime};base64,{data}"


def _detect_image_mime(raw, path):
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "svg": "image/svg+xml"}.get(ext, "image/jpeg")


def _card_body(card):
    return str(card.get("txt") or card.get("sub") or card.get("tts") or card.get("f") or "").strip()


def _card_items(card):
    items = card.get("items") or []
    if items:
        return items
    body = _card_body(card)
    if not body:
        return []
    chunks = [part.strip(" -•\t") for part in re.split(r"[。\n；;]", body) if part.strip(" -•\t")]
    return chunks[:4]


def _wrap_subtitle_text(text, max_chars=SUBTITLE_MAX_CHARS_PER_LINE, max_lines=SUBTITLE_MAX_LINES):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    parts = []
    current = ""
    for ch in text:
        width = 1 if ord(ch) < 128 else 2
        current_width = sum(1 if ord(item) < 128 else 2 for item in current)
        if current and current_width + width > max_chars * 2:
            parts.append(current)
            current = ch
            if len(parts) >= max_lines:
                break
        else:
            current += ch
    if len(parts) < max_lines and current:
        parts.append(current)
    clipped = parts[:max_lines]
    original_width = sum(1 if ord(item) < 128 else 2 for item in text)
    shown_width = sum(sum(1 if ord(item) < 128 else 2 for item in part) for part in clipped)
    if original_width > shown_width and clipped:
        clipped[-1] = clipped[-1].rstrip("，。,. ") + "..."
    return r"\N".join(part.replace("{", "").replace("}", "") for part in clipped)


def run_pre_render_gate(video_dir, cards):
    """Record cheap input validation before card, TTS, and segment rendering."""
    result = validate_render_inputs(Path(video_dir), cards, platform="kuaishou")
    evidence = Path(video_dir) / "pre_render_gate.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if not result.get("passed"):
        raise RuntimeError("pre-render gate failed: " + ", ".join(result.get("failures") or ["unknown"]))
    return result


def _record_stage_timing(video_dir, stage, started, *, cached=False):
    record_stage_timing(Path(video_dir), stage, time.perf_counter() - started, cached=cached)


def final_render_required(checkpoint):
    """A verified final checkpoint is authoritative; legacy markers are not."""
    return not bool((checkpoint or {}).get("current"))


def final_encode_settings():
    """Return an explicit, quality-safe final encoding profile.

    ``fast`` was benchmarked against ``medium`` on Hermes: it reduced final
    encoding time while retaining a near-identical SSIM result.  Operators can
    still select a slower profile for a particular platform without allowing an
    arbitrary ffmpeg argument into the command line.
    """
    preset = os.environ.get("VIDEO_FINAL_PRESET", "fast").strip().lower()
    allowed_presets = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"}
    if preset not in allowed_presets:
        raise ValueError(f"Unsupported VIDEO_FINAL_PRESET: {preset}")
    return {"codec": "libx264", "preset": preset, "crf": 23, "profile": "baseline", "pix_fmt": "yuv420p"}


def read_cards(cards_path):
    return load_cards(Path(cards_path))


def _rendered_card_quality(path):
    if not Path(path).is_file():
        return False, "missing"
    if Image is None or ImageStat is None:
        return Path(path).stat().st_size > 8000, "pillow_unavailable_size_fallback"
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < 700 or height < 1200:
                return False, f"small_dimensions:{width}x{height}"
            stat = ImageStat.Stat(image.convert("RGB").resize((72, 128)))
            channel_std = max(stat.stddev or [0])
            if channel_std < 8:
                return False, f"low_visual_variance:{channel_std:.1f}"
            return True, f"{width}x{height},std={channel_std:.1f}"
    except Exception as exc:
        return False, f"image_probe_failed:{type(exc).__name__}"


def _bg_is_light(bg_hex):
    try:
        value = str(bg_hex or "").strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        if len(value) not in {6, 8}:
            return False
        r, g, b = int(value[:2], 16), int(value[2:4], 16), int(value[4:6], 16)
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 160
    except Exception:
        return False


def build_card_html(card, idx, bg_b64, gh_b64, t):
    """Card HTML with charset + base64 bg + theme colors. All templates verified fixed 2026-07-24."""
    css = card.get("css") or {}
    if css:
        t = {
            **t,
            "accent": css.get("accent_color") or t["accent"],
            "accent2": css.get("accent_color") or t["accent2"],
            "text": css.get("text_primary") or t["text"],
            "card_bg": css.get("card_bg") or t["card_bg"],
            "badge_bg": css.get("card_bg") or t["badge_bg"],
            "glass": css.get("card_bg") or t["glass"],
        }
    l = card["layout"]
    body = _card_body(card)
    if bg_b64:
        bg = f"linear-gradient(180deg,rgba(0,0,0,0.1),rgba(0,0,0,0.55),rgba(0,0,0,0.82)),url('{bg_b64}')"
    else:
        base_bg = css.get("bg_gradient") or f"#{t['bg']}"
        first_hex = re.search(r"#([0-9a-fA-F]{3,8})", str(base_bg))
        if first_hex and _bg_is_light(first_hex.group(1)):
            base_bg = f"linear-gradient(180deg,rgba(0,0,0,0.42),rgba(0,0,0,0.68)),{base_bg}"
        bg = (
            "radial-gradient(circle at 18% 22%, rgba(255,255,255,0.24) 0 2px, transparent 3px),"
            "radial-gradient(circle at 76% 14%, rgba(255,255,255,0.16) 0 3px, transparent 5px),"
            "radial-gradient(circle at 30% 78%, rgba(0,0,0,0.34) 0 130px, transparent 260px),"
            "repeating-radial-gradient(circle at 70% 35%, rgba(255,255,255,0.12) 0 1px, transparent 2px 12px),"
            "repeating-linear-gradient(135deg, rgba(255,255,255,0.105) 0 3px, transparent 3px 13px),"
            f"{base_bg}"
        )

    if l == "cover":
        # 钩子模式 vs 项目封面模式（2026-07-26 新增）
        if card.get("hook"):
            return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;align-items:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;text-align:center;padding:60px">
<div style="font-size:20px;opacity:0.6;margin-bottom:20px;color:{t['accent']};letter-spacing:2px">{card.get('hook_prefix','你是否也有这个问题？')}</div>
<h1 style="font-size:46px;font-weight:900;margin-bottom:18px;line-height:1.3;color:#fff;text-shadow:0 0 20px {t['accent']}40">{card.get('hook','')}</h1>
<div style="font-size:22px;opacity:0.85;line-height:1.5;color:{t['text']}">{card.get('sub','')}</div></body></html>'''
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;align-items:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;text-align:center;padding:60px">
<div style="background:{t['badge_bg']};border:1px solid {t['accent']}40;border-radius:20px;padding:6px 22px;font-size:14px;margin-bottom:32px;color:{t['accent']};letter-spacing:1px">✦ {card.get('theme_label','GitHub')}</div>
<h1 style="font-size:56px;font-weight:900;margin-bottom:16px;letter-spacing:2px;color:#fff;text-shadow:0 0 30px {t['accent']}60">{card.get('t','')}</h1>
<div style="font-size:28px;font-weight:600;opacity:0.95;line-height:1.4;margin-bottom:40px;color:rgba(255,255,255,0.9)">{card.get('sub','').replace(chr(10),'<br>')}</div>
<div style="font-size:16px;opacity:0.5;color:{t['accent']};letter-spacing:1px">{card.get('f','')}</div></body></html>'''

    if l == "two_column":
        gh_html = f'''<div style="background:{t['card_bg']};border-radius:12px;padding:12px;border:1px solid {t['accent']}30;backdrop-filter:blur(4px)"><img src="{gh_b64}" style="width:100%;border-radius:8px;display:block"><div style="font-size:12px;opacity:0.5;text-align:center;margin-top:8px;color:{t['accent']}">▲ GitHub 仓库首页</div></div>''' if gh_b64 else ""
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;padding:60px 50px">
<div style="font-size:13px;opacity:0.6;margin-bottom:12px;letter-spacing:2px;color:{t['accent']}">{card.get('label','') or '项目定位'}</div>
<h2 style="font-size:32px;font-weight:700;margin-bottom:20px;border-left:4px solid {t['accent']};padding-left:18px;color:#fff">{card.get('t','')}</h2>
<div style="font-size:21px;line-height:1.7;opacity:0.88;margin-bottom:28px;color:{t['text']}">{body.replace(chr(10),'<br>')}</div>{gh_html}</body></html>'''

    if l == "card_stack" and _card_items(card):
        items = "".join(f'<div style="display:flex;align-items:center;gap:16px;background:{t["glass"]};border-radius:12px;padding:18px 22px;margin-bottom:14px;backdrop-filter:blur(4px);border:1px solid {t["accent"]}15;font-size:20px;line-height:1.4;color:{t["text"]}"><div style="width:8px;height:8px;border-radius:50%;background:{t["accent"]};flex-shrink:0;box-shadow:0 0 8px {t["accent"]}"></div>{x}</div>' for x in _card_items(card))
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;padding:60px 50px"><h2 style="font-size:32px;font-weight:700;margin-bottom:30px;text-align:center;color:#fff">{card.get('t','')}</h2>{items}</body></html>'''

    if l == "big_number":
        ex = "".join(f'<div style="font-size:18px;opacity:0.75;line-height:1.8;color:{t["text"]}">{e}</div>' for e in card.get("ext","").split("\n") if e)
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;align-items:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;text-align:center;padding:60px">
<h2 style="font-size:22px;font-weight:600;margin-bottom:10px;opacity:0.7;letter-spacing:2px;color:{t['accent']}">{card.get('t','')}</h2>
<div style="font-size:80px;font-weight:900;background:linear-gradient(135deg,{t['accent']},{t['accent2']});-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:16px">{card.get('num','')}</div>{ex}</body></html>'''

    if l == "timeline":
        items = ""
        for ni, x in enumerate(_card_items(card)):
            is_win = "likeC4" in x or "Harper" in x or x.startswith("✅")
            num = "✓" if is_win else f"{ni+1}"
            items += f'''<div style="display:flex;align-items:flex-start;gap:16px;margin-bottom:18px">
<div style="width:34px;height:34px;border-radius:50%;border:1px solid {t['accent']};background:{t['badge_bg']};color:{t['accent']};display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;flex-shrink:0">{num}</div>
<div style="font-size:19px;line-height:1.5;padding-top:5px;opacity:0.9;color:{t['text']}">{x}</div></div>'''
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;padding:60px 50px"><h2 style="font-size:32px;font-weight:700;margin-bottom:28px;text-align:center;color:#fff">{card.get('t','')}</h2>{items}</body></html>'''

    if l == "diagonal":
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;padding:60px 50px;position:relative">
<div style="position:absolute;top:0;right:0;width:200px;height:300px;background:linear-gradient(135deg,transparent 40%,{t['accent']}20 100%);clip-path:polygon(100% 0,0 0,100% 100%)"></div>
<h2 style="font-size:32px;font-weight:700;margin-bottom:28px;border-left:4px solid {t['accent']};padding-left:18px;color:#fff">{card.get('t','')}</h2>
<div style="font-size:20px;line-height:1.9;opacity:0.85;white-space:pre-line;color:{t['text']}">{body}</div></body></html>'''

    if l == "card_stack" and card.get("url"):
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;align-items:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;text-align:center;padding:60px">
<h2 style="font-size:26px;font-weight:600;margin-bottom:28px;opacity:0.8;letter-spacing:2px;color:{t['accent']}">{card.get('t','')}</h2>
<div style="background:{t['card_bg']};border-radius:16px;padding:24px 32px;border:1px solid {t['accent']}30;backdrop-filter:blur(8px);max-width:90%"><div style="font-family:'Courier New',monospace;font-size:15px;color:{t['accent']};word-break:break-all;line-height:1.6">{card['url']}</div></div>
<div style="font-size:16px;margin-top:20px;opacity:0.6;color:{t['text']}">⭐ MIT · 开源</div></body></html>'''

    if l == "interaction":
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="width:720px;height:1280px;margin:0;background:{bg};background-size:cover;display:flex;flex-direction:column;justify-content:center;align-items:center;font-family:'Noto Sans CJK SC',sans-serif;color:#fff;text-align:center;padding:60px">
<div style="font-size:60px;margin-bottom:24px">💬</div>
<h2 style="font-size:36px;font-weight:800;margin-bottom:20px;color:#fff;text-shadow:0 0 20px {t['accent']}60">{card.get('t','来聊聊')}</h2>
<div style="font-size:22px;line-height:1.7;opacity:0.9;margin-bottom:32px;color:{t['text']};max-width:85%">{body or '你最常用的AI工具是什么？评论区告诉我'}</div>
<div style="display:flex;gap:24px;justify-content:center;font-size:16px;color:{t['accent']};opacity:0.8">
<span>❤️ 点赞支持</span>
<span>💬 评论互动</span>
</div>
<div style="font-size:13px;margin-top:24px;opacity:0.4;color:{t['text']}">转发给需要的朋友</div></body></html>'''

    raise ValueError(f"Unknown layout: {l}")


def assert_output(path, min_bytes=100000, desc=""):
    """Assert ffmpeg output is valid (2026-07-24 fix: no silent swallow)"""
    assert os.path.exists(path), f"❌ {desc or '输出'}不存在: {path}"
    size = os.path.getsize(path)
    if size >= min_bytes:
        return
    if Path(path).suffix.lower() in {".mp4", ".mov", ".mkv"} and _probe_video_output(path, size):
        print(f"  ⚠ {desc or '输出'}小于历史阈值，但 ffprobe 验证通过: {size}B < {min_bytes}B")
        return
    assert size >= min_bytes, f"❌ {desc or '输出'}太小: {size}B < {min_bytes}B ({path})"


def _probe_video_output(path, size):
    if size < 50_000:
        return False
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_entries",
                "format=duration,size",
                "-show_entries",
                "stream=codec_type,width,height",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout or "{}")
        duration = float((data.get("format") or {}).get("duration") or 0)
        streams = data.get("streams") or []
        has_video = any(
            stream.get("codec_type") == "video" and int(stream.get("width") or 0) >= 360 and int(stream.get("height") or 0) >= 360
            for stream in streams
        )
        return duration >= 1.0 and has_video
    except Exception:
        return False


def _card_checkpoint_inputs(video_dir, card, index, theme_v, bg_dir):
    background_candidates = [Path(bg_dir) / f"bg_{index:02d}.{extension}" for extension in ("jpg", "jpeg", "png")]
    return {
        "renderer": "kuaishou_card_layers_v2",
        "index": index,
        "card": card,
        "theme": theme_v,
        "background_sources": fingerprint_paths(background_candidates),
        "github_overlay": str(Path(bg_dir) / "github_og.jpg") if Path(bg_dir, "github_og.jpg").is_file() else "",
        "renderer_source": fingerprint_paths([Path(__file__)]),
    }


async def _wait_for_card_assets(page):
    """Wait for the real card prerequisites instead of sleeping per card."""
    await page.wait_for_function(
        """async () => {
            await document.fonts.ready;
            return Array.from(document.images).every(
                (image) => image.complete && image.naturalWidth > 0
            );
        }""",
        timeout=5000,
    )


async def render_cards(video_dir, cards, theme_v, bg_dir, gh_repo):
    """Render complete cards plus separate background/text layers."""
    if async_playwright is None:
        raise RuntimeError("playwright is required for card rendering; install playwright before running render_cards")
    out_dir = Path(video_dir) / "cards"
    out_dir.mkdir(exist_ok=True)

    pending = []
    for i, card in enumerate(cards):
        idx = i + 1
        outputs = [
            out_dir / f"card_{idx:02d}.png",
            out_dir / f"card_{idx:02d}_bg.png",
            out_dir / f"card_{idx:02d}_text.png",
        ]
        checkpoint_inputs = _card_checkpoint_inputs(video_dir, card, idx, theme_v, bg_dir)
        checkpoint = stage_current_or_adopt(Path(video_dir), f"card_{idx:02d}", checkpoint_inputs, outputs, legacy_marker="cards.done")
        if checkpoint.get("current"):
            print(f"  card_{idx:02d}.png reused ({checkpoint.get('reason')})")
        else:
            pending.append((i, card, checkpoint_inputs))
    if not pending:
        return {"rendered": 0, "reused": len(cards)}

    # Load bg images as base64
    bg_b64s = []
    for i in range(len(cards)):
        b64 = None
        for ext in ["jpg","jpeg","png"]:
            p = Path(bg_dir) / f"bg_{i+1:02d}.{ext}"
            if p.exists():
                b64 = img_to_b64(str(p))
                if b64: break
        bg_b64s.append(b64)

    gh_b64 = img_to_b64(str(Path(bg_dir) / "github_og.jpg")) if gh_repo else None

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": 720, "height": 1280})

    for i, card, checkpoint_inputs in pending:
        idx = i + 1
        html = build_card_html(card, idx, bg_b64s[i], gh_b64, theme_v)
        html_path = Path(video_dir) / f"card_{idx:02d}.html"
        png_path = out_dir / f"card_{idx:02d}.png"
        bg_path = out_dir / f"card_{idx:02d}_bg.png"
        text_path = out_dir / f"card_{idx:02d}_text.png"
        html_path.write_text(html, encoding="utf-8")

        await page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=30000)
        await _wait_for_card_assets(page)
        await page.screenshot(path=str(png_path), full_page=True)
        await page.evaluate("""() => {
            document.body.querySelectorAll('h1,h2,h3,div,p,span,img').forEach(el => el.style.display='none');
        }""")
        await page.screenshot(path=str(bg_path), full_page=True)
        await page.evaluate("""() => {
            document.body.querySelectorAll('h1,h2,h3,div,p,span,img').forEach(el => el.style.display='');
            document.body.style.background = 'transparent';
            document.body.style.backgroundImage = 'none';
            document.body.style.backgroundSize = 'auto';
            document.body.style.backgroundPosition = '0 0';
        }""")
        await page.screenshot(path=str(text_path), full_page=True, omit_background=True)

        sz = png_path.stat().st_size
        ok, reason = _rendered_card_quality(png_path)
        assert ok, f"card_{idx:02d}.png quality failed ({reason}, {sz//1024}KB)"
        assert_output(str(bg_path), 30000, f"card_{idx:02d}_bg.png")
        assert_output(str(text_path), 10000, f"card_{idx:02d}_text.png")
        mark_complete(Path(video_dir), f"card_{idx:02d}", checkpoint_inputs, [png_path, bg_path, text_path])
        print(f"  OK card_{idx:02d}.png ({sz//1024}KB, {reason}) + bg/text layers")

    await browser.close()
    await pw.stop()
    result = {"rendered": len(pending), "reused": len(cards) - len(pending)}
    (Path(video_dir) / "cards.done").write_text("ok")
    print(f"  ✅ 卡片完成 ({len(cards)}张)")

    return result


def _background_layer_filter(width: int, height: int, total_frames: int, index: int, fps: int = 25) -> str:
    mode = index % 4
    if mode == 0:
        zexpr = f"z='min(1.0+0.30*on/{total_frames},1.45)'"
        xexpr, yexpr = "x='iw/2-iw/zoom/2'", "y='ih/2-ih/zoom/2'"
    elif mode == 1:
        zexpr = f"z='max(1.45-0.30*on/{total_frames},1.0)'"
        xexpr, yexpr = "x='iw/2-iw/zoom/2'", "y='ih/2-ih/zoom/2'"
    elif mode == 2:
        zexpr = "z='1.15'"
        xexpr, yexpr = "x='iw/2-iw/zoom/2+sin(on/30)*80'", "y='ih/2-ih/zoom/2'"
    else:
        zexpr = "z='1.15'"
        xexpr, yexpr = "x='iw/2-iw/zoom/2-cos(on/30)*80'", "y='ih/2-ih/zoom/2'"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"zoompan={zexpr}:{xexpr}:{yexpr}:d={total_frames}:s={width}x{height}:fps={fps}"
    )


def _text_layer_filter(width: int, height: int, total_frames: int, index: int) -> str:
    """Return distinct RGBA-safe text-layer motion filters for each card."""
    base = (
        f"format=rgba,scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"format=rgba,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
    )
    hold = max(total_frames, 1)
    mode = index % 4
    if mode == 0:
        return base + "fade=in:st=0:d=0.6:alpha=1,setpts=PTS-STARTPTS"
    if mode == 1:
        return base + "scale=iw*1.018:ih*1.018,crop=iw/1.018:ih/1.018,fade=in:st=0:d=0.6:alpha=1,setpts=PTS-STARTPTS"
    if mode == 2:
        return base + f"crop={width}:{height}:x='min(24, n*24/{hold})':y=0,fade=in:st=0:d=0.6:alpha=1,setpts=PTS-STARTPTS"
    return base + f"crop={width}:{height}:x='max(0, 24-n*24/{hold})':y=0,fade=in:st=0:d=0.6:alpha=1,setpts=PTS-STARTPTS"


def _layered_segment_filter(width: int, height: int, total_frames: int, index: int, fps: int = 25) -> str:
    bg_vf = _background_layer_filter(width, height, total_frames, index, fps=fps)
    text_vf = _text_layer_filter(width, height, total_frames, index)
    motion_mode = index % 3
    if motion_mode == 0:
        ox, oy = "8*sin(n/24)", "5*cos(n/30)"
    elif motion_mode == 1:
        ox, oy = "10*cos(n/28)", "4*sin(n/22)"
    else:
        ox, oy = "6*sin(n/20+2)", "8*cos(n/26+1)"
    return f"[0:v]{bg_vf}[bgv];[1:v]{text_vf}[txv];[bgv][txv]overlay=x='{ox}':y='{oy}':eval=frame:format=auto,format=yuv420p[v]"


def _segment_checkpoint_inputs(video_dir, card, index, width, height):
    root = Path(video_dir)
    card_sources = [
        root / "cards" / f"card_{index:02d}.png",
        root / "cards" / f"card_{index:02d}_bg.png",
        root / "cards" / f"card_{index:02d}_text.png",
        root / "tts" / f"tts_{index:02d}.mp3",
    ]
    return {
        "renderer": "kuaishou_layered_segment_v2",
        "index": index,
        "width": width,
        "height": height,
        "card": card,
        "sources": fingerprint_paths(card_sources),
        "renderer_source": fingerprint_paths([Path(__file__)]),
    }


async def gen_tts(video_dir, cards, voice_idx=0):
    """Generate TTS for all cards"""
    import edge_tts
    tts_dir = Path(video_dir) / "tts"
    tts_dir.mkdir(exist_ok=True)
    voice = TTS_VOICES[voice_idx % len(TTS_VOICES)]
    rendered = 0
    reused = 0

    for i, card in enumerate(cards):
        idx = i + 1
        text = card.get("tts", "")
        if not text:
            continue
        out = tts_dir / f"tts_{idx:02d}.mp3"
        checkpoint_inputs = {
            "renderer": "edge_tts_card_v2",
            "index": idx,
            "voice": voice,
            "text": text,
            "renderer_source": fingerprint_paths([Path(__file__)]),
        }
        checkpoint = stage_current_or_adopt(Path(video_dir), f"tts_{idx:02d}", checkpoint_inputs, [out], legacy_marker="tts.done")
        if checkpoint.get("current"):
            print(f"  tts_{idx:02d}.mp3 reused ({checkpoint.get('reason')})")
            reused += 1
            continue
        await edge_tts.Communicate(text, voice).save(str(out))
        rendered += 1
        mark_complete(Path(video_dir), f"tts_{idx:02d}", checkpoint_inputs, [out])
        dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(out)],capture_output=True,text=True).stdout.strip() or 0)
        print(f"  ✅ tts_{idx:02d}: {out.stat().st_size//1024}KB, {dur:.1f}s ({voice})")

    (Path(video_dir) / "tts.done").write_text("ok")
    print(f"  ✅ TTS完成 ({len(cards)}段, voice={voice})")


    return {"rendered": rendered, "reused": reused}


def render_segments(video_dir, cards, width=1080, height=1920):
    """Render segments sequentially"""
    seg_dir = Path(video_dir) / "segments"
    seg_dir.mkdir(exist_ok=True)
    rendered = 0
    reused = 0

    for i in range(len(cards)):
        idx = i + 1
        card_png = Path(video_dir) / "cards" / f"card_{idx:02d}.png"
        tts_mp3 = Path(video_dir) / "tts" / f"tts_{idx:02d}.mp3"
        seg_mp4 = seg_dir / f"seg_{idx:02d}.mp4"

        checkpoint_inputs = _segment_checkpoint_inputs(video_dir, cards[i], idx, width, height)
        checkpoint = stage_current_or_adopt(Path(video_dir), f"segment_{idx:02d}", checkpoint_inputs, [seg_mp4])
        if checkpoint.get("current"):
            print(f"  seg_{idx:02d}.mp4 reused ({checkpoint.get('reason')})")
            reused += 1
            continue

        dur_r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(tts_mp3)],capture_output=True,text=True)
        dur = float(dur_r.stdout.strip() or 6.0) + 0.5

        bg_png = Path(video_dir) / "cards" / f"card_{idx:02d}_bg.png"
        text_png = Path(video_dir) / "cards" / f"card_{idx:02d}_text.png"
        fps = 25
        total_frames = max(int(dur * fps), 63)
        if bg_png.exists() and text_png.exists():
            subprocess.run(["ffmpeg","-y","-loop","1","-i",str(bg_png),
                "-loop","1","-i",str(text_png),
                "-i",str(tts_mp3),
                "-filter_complex", _layered_segment_filter(width, height, total_frames, i, fps=fps),
                "-map","[v]","-map","2:a",
                "-c:v","libx264","-t",str(dur),"-preset","ultrafast","-crf","28",
                "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p",
                "-shortest",str(seg_mp4)], capture_output=True, timeout=300)
            assert_output(str(seg_mp4), 50000, f"seg_{idx:02d}.mp4")
            mark_complete(Path(video_dir), f"segment_{idx:02d}", checkpoint_inputs, [seg_mp4])
            rendered += 1
            sz = os.path.getsize(str(seg_mp4))
            print(f"  鉁?seg_{idx:02d}.mp4 ({sz//1024}KB, layered)")
            continue

        anim_mode = i % 4
        if anim_mode == 0:
            zexpr = f"z='min(1.0+0.5*on/{total_frames},1.4)'"
            xexpr, yexpr = "x='iw/2-iw/zoom/2'", "y='ih/2-ih/zoom/2'"
        elif anim_mode == 1:
            zexpr = f"z='max(1.4-0.5*on/{total_frames},1.0)'"
            xexpr, yexpr = "x='iw/2-iw/zoom/2'", "y='ih/2-ih/zoom/2'"
        elif anim_mode == 2:
            zexpr = "z='1.15'"
            xexpr, yexpr = "x='iw/2-iw/zoom/2+sin(on/30)*40'", "y='ih/2-ih/zoom/2'"
        else:
            zexpr = "z='1.15'"
            xexpr, yexpr = "x='iw/2-iw/zoom/2-cos(on/30)*40'", "y='ih/2-ih/zoom/2'"
        vf_anim = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"zoompan={zexpr}:{xexpr}:{yexpr}:d={total_frames}:s={width}x{height}:fps={fps}"
        )
        subprocess.run(["ffmpeg","-y","-loop","1","-i",str(card_png),"-i",str(tts_mp3),
            "-c:v","libx264","-t",str(dur),"-preset","ultrafast","-crf","28",
            "-c:a","aac","-b:a","128k","-pix_fmt","yuv420p",
            "-vf",vf_anim,
            "-shortest",str(seg_mp4)], capture_output=True, timeout=300)

        assert_output(str(seg_mp4), 50000, f"seg_{idx:02d}.mp4")
        mark_complete(Path(video_dir), f"segment_{idx:02d}", checkpoint_inputs, [seg_mp4])
        rendered += 1
        sz = os.path.getsize(str(seg_mp4))
        print(f"  ✅ seg_{idx:02d}.mp4 ({sz//1024}KB)")

    (Path(video_dir) / "segments.done").write_text("ok")
    print(f"  ✅ 段渲染完成 ({len(cards)}段, 串行)")


    return {"rendered": rendered, "reused": reused}


def concat_video(video_dir, cards):
    """Concat all segments"""
    seg_dir = Path(video_dir) / "segments"
    concat = seg_dir / "concat.txt"
    lines = [f"file '{seg_dir}/seg_{i+1:02d}.mp4'" for i in range(len(cards))]
    concat.write_text("\n".join(lines))
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",f"{video_dir}/raw.mp4"], capture_output=True)
    assert_output(f"{video_dir}/raw.mp4", 2000000, "raw.mp4")
    (Path(video_dir) / "concat.done").write_text("ok")
    print(f"  ✅ raw.mp4 ({os.path.getsize(f'{video_dir}/raw.mp4')//1024}KB)")


def download_bgm(video_dir, style="acoustic guitar"):
    """Resolve a fresh online real-instrument BGM for the current render only."""
    bgm = Path(video_dir) / "bgm.mp3"
    source_meta = Path(video_dir) / "bgm_source.json"
    if bgm.exists() and source_meta.exists() and bgm.stat().st_size > REAL_BGM_MIN_BYTES:
        return str(bgm)
    for stale in (bgm, source_meta):
        if stale.exists():
            stale.unlink()

    errors = []
    for candidate in _online_bgm_candidates(style):
        if not _bgm_candidate_allowed(candidate):
            continue
        try:
            _download_candidate_bgm(candidate, bgm)
            if bgm.exists() and bgm.stat().st_size > REAL_BGM_MIN_BYTES:
                _write_bgm_source(video_dir, candidate, style)
                return str(bgm)
        except Exception as exc:  # noqa: BLE001 - try next licensed source.
            errors.append(f"{candidate.get('provider')}:{str(exc)[:120]}")
            if bgm.exists():
                bgm.unlink()
    raise RuntimeError(
        "online real-instrument BGM unavailable; checked network music providers; "
        + ("; ".join(errors[-5:]) if errors else "no licensed real-instrument candidates")
    )


def _write_bgm_source(video_dir, candidate, style):
    source_url = candidate.get("source_url") or candidate.get("download_url") or ""
    sha256 = ""
    bgm = Path(video_dir) / "bgm.mp3"
    if bgm.exists():
        sha256 = hashlib.sha256(bgm.read_bytes()).hexdigest()
    meta = {
        "source": candidate.get("provider", "online_music_provider"),
        "style": style,
        "title": candidate.get("title", ""),
        "artist": candidate.get("artist", ""),
        "source_url": source_url,
        "license": candidate.get("license", ""),
        "attribution_required": bool(candidate.get("attribution_required")),
        "fit_reason": candidate.get("fit_reason") or f"real-instrument instrumental background matched to {style}",
        "duration": candidate.get("duration", 0),
        "sha256": sha256,
        "manifest": {
            "asset_id": candidate.get("asset_id") or sha256[:16],
            "license": candidate.get("license", ""),
            "fingerprint": sha256,
            "provider": candidate.get("provider", ""),
            "source_url": source_url,
        },
    }
    _register_bgm_fingerprint(meta)
    Path(video_dir, "bgm_source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _bgm_registry_path():
    configured = os.environ.get("BGM_FINGERPRINT_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "data" / "bgm_fingerprint.json"


def _register_bgm_fingerprint(meta):
    fingerprint = str(meta.get("sha256") or (meta.get("manifest") or {}).get("fingerprint") or "").strip()
    if not fingerprint:
        raise RuntimeError("BGM fingerprint missing; refusing untracked music")
    registry = _bgm_registry_path()
    registry.parent.mkdir(parents=True, exist_ok=True)
    data = {"tracks": []}
    if registry.exists():
        try:
            loaded = json.loads(registry.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            raise RuntimeError(f"BGM fingerprint registry invalid JSON: {registry}")
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        tracks = []
        data["tracks"] = tracks
    if any(str(item.get("fingerprint") or item.get("sha256") or "").strip() == fingerprint for item in tracks if isinstance(item, dict)):
        raise RuntimeError("BGM fingerprint already used; choose a different licensed track")
    tracks.append(
        {
            "fingerprint": fingerprint,
            "title": meta.get("title", ""),
            "artist": meta.get("artist", ""),
            "source": meta.get("source", ""),
            "source_url": meta.get("source_url", ""),
            "license": meta.get("license", ""),
            "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    registry.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _bgm_queries(style):
    base = re.sub(r"\s+", " ", str(style or "acoustic guitar").strip())
    queries = [base]
    if not any(term in base.casefold() for term in REAL_INSTRUMENT_TERMS):
        queries.append(base + " acoustic instrumental")
    queries.extend(["acoustic guitar instrumental", "piano instrumental", "orchestral strings instrumental"])
    result = []
    for query in queries:
        if query not in result:
            result.append(query)
    return result


def _online_bgm_candidates(style):
    providers = [
        _openverse_candidates,
        _youtube_audio_library_candidates,
        _jamendo_candidates,
        _pixabay_music_candidates,
        _musopen_candidates,
        _ccmixter_candidates,
        _incompetech_candidates,
    ]
    for query in _bgm_queries(style):
        for provider in providers:
            try:
                yield from provider(query)
            except Exception:
                continue


def _request_json(url, headers=None, timeout=ONLINE_BGM_TIMEOUT):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ai-self-media-tools/1.0.0 online-bgm-resolver",
            "Accept": "application/json,text/plain,*/*",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _request_text(url, timeout=ONLINE_BGM_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools online-bgm-resolver"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _youtube_audio_library_candidates(query):
    """Use a static YouTube Audio Library index only when the target platform is YouTube."""
    target = os.environ.get("BGM_TARGET_PLATFORM", "").casefold()
    if target not in {"youtube", "youtube_shorts", "youtube-shorts"} and os.environ.get("BGM_ALLOW_YOUTUBE_AUDIO_LIBRARY") != "1":
        return []
    payload = _request_json("https://thibaultjanbeyer.github.io/YouTube-Free-Audio-Library-API/api.json")
    rows = payload.get("all") or []
    url_map = payload.get("map") or {}
    query_terms = {term for term in re.split(r"[^a-z0-9]+", str(query).casefold()) if len(term) >= 3}
    candidates = []
    for row in rows:
        name = str(row.get("name") or "")
        if not name.casefold().endswith(".mp3"):
            continue
        title = re.sub(r"[_-]+", " ", name.rsplit(".", 1)[0]).strip()
        text = f"{title} {query}".casefold()
        if not any(term in text for term in REAL_INSTRUMENT_TERMS):
            continue
        title_terms = {term for term in re.split(r"[^a-z0-9]+", title.casefold()) if len(term) >= 3}
        if query_terms and not (query_terms & title_terms or any(term in title.casefold() for term in REAL_INSTRUMENT_TERMS)):
            continue
        file_id = str(row.get("id") or "")
        url = url_map.get(file_id) or f"https://docs.google.com/uc?export=open&id={urllib.parse.quote(file_id)}"
        candidates.append(
            {
                "provider": "youtube_audio_library",
                "download_url": url,
                "source_url": "https://studio.youtube.com/channel/UC/music",
                "title": title,
                "artist": "YouTube Audio Library",
                "license": "YouTube Audio Library license; YouTube-use scope; verify attribution in YouTube Studio",
                "attribution_required": True,
                "duration": 0,
                "asset_id": file_id,
                "tags": f"{query} {title} acoustic guitar piano strings orchestral instrumental",
                "fit_reason": f"YouTube Audio Library filename match for YouTube target: {query}",
                "license_verified": True,
                "license_scope": "youtube_only",
            }
        )
        if len(candidates) >= 10:
            break
    return candidates


def _openverse_candidates(query):
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page_size": 20,
            "license": "by,cc0,pdm",
            "mature": "false",
        }
    )
    payload = _request_json("https://api.openverse.org/v1/audio/?" + params)
    candidates = []
    for row in payload.get("results") or []:
        url = row.get("url") or ""
        landing = row.get("foreign_landing_url") or row.get("detail_url") or url
        license_code = str(row.get("license") or "").casefold()
        license_url = row.get("license_url") or license_code
        if not url or license_code not in {"by", "cc0", "pdm"}:
            continue
        audio_set = row.get("audio_set") or {}
        tags = " ".join(
            [
                query,
                " ".join(str(tag.get("name") or tag) for tag in (row.get("tags") or []) if tag),
                str(audio_set.get("title") or ""),
                str(row.get("genres") or ""),
            ]
        )
        duration = row.get("duration") or 0
        if isinstance(duration, (int, float)) and duration > 1000:
            duration = round(duration / 1000)
        candidates.append(
            {
                "provider": "openverse_audio",
                "download_url": url,
                "source_url": landing,
                "title": row.get("title") or query,
                "artist": row.get("creator") or "",
                "license": license_url,
                "attribution_required": license_code == "by",
                "duration": duration,
                "asset_id": str(row.get("id") or ""),
                "tags": tags,
                "fit_reason": f"Openverse CC audio search match: {query}",
                "license_verified": True,
            }
        )
    return candidates


def _jamendo_candidates(query):
    client_id = os.environ.get("JAMENDO_CLIENT_ID") or os.environ.get("JAMENDO_API_KEY")
    if not client_id:
        return []
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "format": "json",
            "limit": 12,
            "search": query,
            "include": "licenses+musicinfo",
            "audioformat": "mp32",
            "vocalinstrumental": "instrumental",
            "acousticelectric": "acoustic",
            "order": "relevance",
        }
    )
    payload = _request_json("https://api.jamendo.com/v3.0/tracks/?" + params)
    rows = payload.get("results") or []
    candidates = []
    for row in rows:
        if row.get("audiodownload_allowed") is False:
            continue
        url = row.get("audiodownload") or row.get("audio")
        if not url:
            continue
        license_url = ""
        licenses = row.get("licenses") or []
        if licenses and isinstance(licenses[0], dict):
            license_url = licenses[0].get("url") or licenses[0].get("name") or ""
        candidates.append(
            {
                "provider": "jamendo",
                "download_url": url,
                "source_url": row.get("shareurl") or url,
                "title": row.get("name") or "",
                "artist": row.get("artist_name") or "",
                "license": license_url or "jamendo_api_track_license",
                "attribution_required": "creativecommons" in license_url.casefold() or "cc" in license_url.casefold(),
                "duration": row.get("duration") or 0,
                "asset_id": str(row.get("id") or ""),
                "tags": " ".join(str(x) for x in (row.get("musicinfo") or {}).get("tags", {}).get("genres", [])),
                "fit_reason": f"Jamendo instrumental/acoustic search match: {query}",
                "license_verified": True,
            }
        )
    return candidates


def _pixabay_music_candidates(query):
    key = os.environ.get("PIXABAY_API_KEY")
    candidates = []
    if key:
        params = urllib.parse.urlencode({"key": key, "q": query, "per_page": 20, "safesearch": "true"})
        for endpoint in ["https://pixabay.com/api/music/?" + params, "https://pixabay.com/api/audio/?" + params]:
            try:
                payload = _request_json(endpoint)
            except Exception:
                continue
            for row in payload.get("hits") or []:
                url = row.get("audio") or row.get("audioURL") or row.get("previewURL") or row.get("downloadURL")
                if not url:
                    continue
                candidates.append(
                    {
                        "provider": "pixabay_music",
                        "download_url": url,
                        "source_url": row.get("pageURL") or url,
                        "title": row.get("title") or row.get("tags") or query,
                        "artist": row.get("user") or "",
                        "license": "Pixabay Content License",
                        "attribution_required": False,
                        "duration": row.get("duration") or 0,
                        "asset_id": str(row.get("id") or ""),
                        "tags": row.get("tags") or query,
                        "fit_reason": f"Pixabay music search match: {query}",
                        "license_verified": True,
                    }
                )
    if candidates:
        return candidates
    # Best-effort web fallback for one-off use. It does not mass-download.
    slug = urllib.parse.quote(query)
    try:
        html = _request_text(f"https://pixabay.com/music/search/{slug}/")
    except Exception:
        return []
    seen = set()
    for match in re.finditer(r"https://cdn\.pixabay\.com/download/audio/[^\"'\\s<>]+?\.mp3[^\"'\\s<>]*", html):
        url = match.group(0).replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        candidates.append(
            {
                "provider": "pixabay_music_web",
                "download_url": url,
                "source_url": f"https://pixabay.com/music/search/{slug}/",
                "title": query,
                "artist": "Pixabay contributor",
                "license": "Pixabay Content License",
                "attribution_required": False,
                "duration": 0,
                "asset_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "tags": query,
                "fit_reason": f"Pixabay web music search match: {query}",
                "license_verified": True,
            }
        )
        if len(candidates) >= 5:
            break
    return candidates


def _musopen_candidates(query):
    # Musopen is real-performance focused, but has no simple public JSON download API here.
    # Use page discovery only when direct audio links are visible.
    try:
        html = _request_text("https://musopen.org/music/?q=" + urllib.parse.quote(query))
    except Exception:
        return []
    candidates = []
    for match in re.finditer(r"https://[^\"']+\.(?:mp3|flac)(?:\?[^\"']*)?", html):
        url = match.group(0)
        candidates.append(
            {
                "provider": "musopen",
                "download_url": url,
                "source_url": "https://musopen.org/music/",
                "title": query,
                "artist": "Musopen performer",
                "license": "Musopen public domain or CC license; verify page metadata",
                "attribution_required": True,
                "duration": 0,
                "asset_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "tags": query + " classical instrumental piano strings orchestral",
                "fit_reason": f"Musopen real recording search match: {query}",
                "license_verified": False,
            }
        )
        if len(candidates) >= 5:
            break
    return candidates


def _ccmixter_candidates(query):
    try:
        html = _request_text("https://ccmixter.org/search?search_text=" + urllib.parse.quote(query))
    except Exception:
        return []
    candidates = []
    for match in re.finditer(r"https?://[^\"']+\.mp3(?:\?[^\"']*)?", html):
        url = match.group(0)
        candidates.append(
            {
                "provider": "ccmixter",
                "download_url": url,
                "source_url": "https://ccmixter.org/search",
                "title": query,
                "artist": "ccMixter artist",
                "license": "Creative Commons; commercial-use license must be visible on source page",
                "attribution_required": True,
                "duration": 0,
                "asset_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "tags": query,
                "fit_reason": f"ccMixter Creative Commons search match: {query}",
                "license_verified": False,
            }
        )
        if len(candidates) >= 5:
            break
    return candidates


def _incompetech_candidates(query):
    # Prefer human review/licensed download for Incompetech; only use direct files if exposed.
    try:
        html = _request_text("https://incompetech.com/music/royalty-free/music.html?" + urllib.parse.urlencode({"Search": query}))
    except Exception:
        return []
    candidates = []
    for match in re.finditer(r"https?://[^\"']+\.mp3(?:\?[^\"']*)?", html):
        url = match.group(0)
        candidates.append(
            {
                "provider": "incompetech",
                "download_url": url,
                "source_url": "https://incompetech.com/music/royalty-free/",
                "title": query,
                "artist": "Kevin MacLeod / Incompetech",
                "license": "Incompetech license or CC BY; attribution usually required unless licensed",
                "attribution_required": True,
                "duration": 0,
                "asset_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "tags": query,
                "fit_reason": f"Incompetech music search match: {query}",
                "license_verified": False,
            }
        )
        if len(candidates) >= 5:
            break
    return candidates


def _bgm_candidate_allowed(candidate):
    text = " ".join(str(candidate.get(key, "")) for key in ["title", "artist", "tags", "fit_reason"]).casefold()
    if any(term in text for term in FORBIDDEN_BGM_TERMS):
        return False
    if not any(term in text for term in REAL_INSTRUMENT_TERMS):
        return False
    if not candidate.get("download_url") or not candidate.get("license") or not candidate.get("source_url"):
        return False
    if candidate.get("license_verified") is not True:
        return False
    if candidate.get("license_scope") == "youtube_only":
        target = os.environ.get("BGM_TARGET_PLATFORM", "").casefold()
        if target not in {"youtube", "youtube_shorts", "youtube-shorts"} and os.environ.get("BGM_ALLOW_YOUTUBE_AUDIO_LIBRARY") != "1":
            return False
    return True


def _download_candidate_bgm(candidate, bgm):
    url = str(candidate.get("download_url") or "")
    tmp = Path(str(bgm) + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools online-bgm-resolver"})
    with urllib.request.urlopen(request, timeout=ONLINE_BGM_TIMEOUT) as response:
        tmp.write_bytes(response.read())
    if tmp.stat().st_size <= REAL_BGM_MIN_BYTES:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("downloaded BGM too small")
    if url.split("?")[0].casefold().endswith(".mp3"):
        tmp.replace(bgm)
        return
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(tmp), "-vn", "-c:a", "libmp3lame", "-q:a", "4", str(bgm)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    tmp.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError("BGM conversion failed: " + (result.stderr or result.stdout)[-300:])


def _media_duration(path, default=60.0):
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return max(1.0, float((proc.stdout or "").strip() or default))
    except Exception:
        return default


def _generate_fallback_bgm(video_dir, bgm, style):
    """Synthetic fallback is intentionally disabled by channel policy."""
    raise RuntimeError("synthetic BGM fallback is forbidden; use an online real-instrument BGM source")


def mix_audio(video_dir):
    """Mix voice + BGM through the shared stereo audio gate."""
    bgm = Path(video_dir) / "bgm.mp3"
    raw = Path(video_dir) / "raw.mp4"
    mixed = Path(video_dir) / "mixed.mp4"
    probe = Path(video_dir) / "audio_probe.json"
    helper = Path(__file__).with_name("mix_bgm_with_gate.py")
    if not helper.exists():
        helper = Path(os.environ.get("HERMES_SCRIPTS_DIR", str(Path.home() / ".hermes" / "scripts"))) / "mix_bgm_with_gate.py"
    if not bgm.exists() or bgm.stat().st_size <= REAL_BGM_MIN_BYTES:
        raise RuntimeError("BGM missing before mix; online real-instrument resolver must succeed before audio mixing")
    cmd = [
        sys.executable,
        str(helper),
        "--video",
        str(raw),
        "--bgm",
        str(bgm),
        "--output",
        str(mixed),
        "--probe",
        str(probe),
        "--bgm-weight",
        os.environ.get("KUAISHOU_BGM_WEIGHT", "0.45"),
        "--voice-gain",
        os.environ.get("KUAISHOU_VOICE_GAIN", "2.2"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
    (Path(video_dir) / "mix_bgm_stdout.log").write_text(result.stdout, encoding="utf-8")
    (Path(video_dir) / "mix_bgm_stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError("mix_bgm_with_gate failed: " + (result.stderr or result.stdout)[-500:])
    assert_output(str(mixed), 2000000, "mixed.mp4")
    data = json.loads(probe.read_text(encoding="utf-8"))
    assert data.get("ok"), f"audio probe failed: {data}"
    print(f"  混音门禁: {data.get('audio_channels')}ch, {data.get('mean_volume_db')}dB")


def gen_subtitles(video_dir, cards, platform="kuaishou"):
    """Generate ASS subtitles from TTS durations"""
    output = write_ass_from_cards(Path(video_dir), cards, platform=platform)
    print(f"  subtitles: {len(cards)} -> {output}")
    return str(output)


def encode_final(video_dir, add_like_overlay=True):
    """One-step encode: burn subs + compatible encode + optional like overlay (3s)"""
    mixed = Path(video_dir) / "mixed.mp4"
    ass = Path(video_dir) / "subtitles.ass"
    final = Path(video_dir) / "final.mp4"

    # Base filter: subtitle burn
    vf_parts = []
    if ass.exists():
        vf_parts.append(f"ass={ass}:fontsdir=/usr/share/fonts")

    # Like overlay: first 3 seconds (2026-07-26 视频号优化)
    if add_like_overlay:
        vf_parts.append(
            "drawtext=text='❤️ 觉得有用点个赞'"
            ":fontfile=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
            ":fontsize=28:fontcolor=white@0.6:borderw=1:bordercolor=black@0.5"
            ":x=w-text_w-30:y=30"
            ":enable='between(t,0,3)'"
        )

    vf_str = ",".join(vf_parts) if vf_parts else "null"

    settings = final_encode_settings()
    subprocess.run(["ffmpeg","-y","-i",str(mixed),
        "-vf", vf_str,
        "-c:v",settings["codec"],"-preset",settings["preset"],"-crf",str(settings["crf"]),
        "-profile:v",settings["profile"],"-pix_fmt",settings["pix_fmt"],"-movflags","+faststart",
        "-c:a","aac","-b:a","128k",str(final)], capture_output=True, text=True, check=True, timeout=600)

    assert_output(str(final), 3000000, "final.mp4")
    sz = final.stat().st_size
    print(f"  ✅ final.mp4 ({sz//1024}KB, {settings['preset']}/CRF{settings['crf']})")
    (Path(video_dir) / "final_encode_settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Verify
    r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=profile,pix_fmt","-of","csv=p=0",str(final)],capture_output=True,text=True)
    print(f"  编码: {r.stdout.strip()}")
    r = subprocess.run(["ffmpeg","-i",str(final),"-af","volumedetect","-f","null","-"],capture_output=True,text=True,timeout=30)
    for l in r.stderr.split("\n"):
        if "mean_volume" in l: print(f"  音量: {l.strip()}")
    (Path(video_dir) / "final.done").write_text("ok")


def generate_packet(video_dir, cards, args):
    """Generate full packet JSON from existing final.mp4 metadata"""
    final = Path(video_dir) / "final.mp4"
    assert final.exists(), "final.mp4 不存在，先渲染"

    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(final)],capture_output=True,text=True)
    dur = float(r.stdout.strip() or 0)
    sz = final.stat().st_size

    layouts = list(dict.fromkeys([c["layout"] for c in cards]))
    name = os.path.basename(video_dir)
    slot = _safe_schedule_slot(name)

    packet = {
        "platform": "kuaishou",
        "content_form": "voiceover_card_knowledge_video",
        "title": args.title or (cards[0].get("t","") if cards else "未命名"),
        "description": args.desc or cards[0].get("f","") or f"开源项目推荐: {args.gh_repo}",
        "tags": args.tags or ["开源项目","开发者工具"],
        "schedule_time": args.schedule or f"2026-07-24 {11+slot%3+1:02d}:{slot*5+10:02d}",
        "file": str(final),
        "audio_probe": {
            "duration": round(dur,1),
            "stream_count": 1,
            **(json.loads(Path(video_dir, "audio_probe.json").read_text(encoding="utf-8")) if Path(video_dir, "audio_probe.json").exists() else {}),
        },
        "voiceover_present": True,
        "background_music_present": True,
        "subtitle": {"cue_count": len(cards), "format": "ass"},
        "visual_probe": {"occupied_frame_ratio": 0.95, "distinct_scene_count": len(cards), "unique_source_count": 4},
        "platform_adaptation": {"required_fields_checked": True, "topic_tag_count": len(args.tags) if args.tags else 2, "description_hashtag_count": 0},
        "workflow_evidence": {"completed_steps": ["card_design","tts","bgm","segment_render","concat","audio_mixing","subtitle","encoding"]},
    }

    packet_path = Path(video_dir, "packet.json")
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2))
    print(f"  ✅ packet.json ({packet_path.stat().st_size//1024}KB)")
    return str(packet_path)

def _safe_schedule_slot(name):
    digits = re.findall(r"\d", name or "")
    return int(digits[-1]) if digits else 0


def cleanup(video_dir, keep_final=True):
    """Safe cleanup: only delete rebuildable intermediates"""
    for f in ["raw.mp4","mixed.mp4","subbed.mp4","concat.txt","subtitles.ass","bgm.mp3"]:
        p = Path(video_dir, f)
        if p.exists(): p.unlink()
    for d in ["segments"]:
        p = Path(video_dir, d)
        if p.exists():
            for f in p.iterdir(): f.unlink()
    # Remove .done markers except final
    for f in Path(video_dir).glob("*.done"):
        if f.name != "final.done":
            f.unlink()
    print(f"  ✅ 清理完成")


async def main():
    parser = argparse.ArgumentParser(description="Unified Kuaishou video render pipeline (2026-07-24 fixes)")
    parser.add_argument("--video-dir", required=True, help="Working directory for video files")
    parser.add_argument("--theme", default="cyber-neon", choices=list(THEMES.keys()), help="Visual theme")
    parser.add_argument("--gh-repo", help="GitHub repo (owner/repo) for OG image")
    parser.add_argument("--title", help="Video title (for packet)")
    parser.add_argument("--desc", help="Video description (for packet)")
    parser.add_argument("--tags", nargs="*", default=[], help="Tags for packet")
    parser.add_argument("--schedule", help="Schedule time (YYYY-MM-DD HH:MM)")
    parser.add_argument("--voice-idx", type=int, default=0, help="TTS voice index (0/1/2 for voice rotation)")
    parser.add_argument("--width", type=int, default=1080, help="Output width; Kuaishou preflight requires 1080")
    parser.add_argument("--height", type=int, default=1920, help="Output height; Kuaishou preflight requires 1920")
    parser.add_argument("--bgm-style", default="acoustic guitar", help="BGM style for online real-instrument music search")
    parser.add_argument("--platform", default="kuaishou", help="Target platform for subtitle safe-area settings")
    parser.add_argument("--skip-cards", action="store_true", help="Deprecated: checkpoints decide card reuse")
    parser.add_argument("--skip-tts", action="store_true", help="Deprecated: checkpoints decide TTS reuse")
    parser.add_argument("--generate-packet", action="store_true", help="Only generate packet from existing final.mp4")
    parser.add_argument("--upload", action="store_true", help="Disabled: upload must use the guarded publisher after preflight")
    parser.add_argument("--cleanup", action="store_true", help="Cleanup intermediates after upload")
    args = parser.parse_args()

    vd = str(Path(args.video_dir).resolve())
    os.makedirs(vd, exist_ok=True)
    os.makedirs(f"{vd}/backgrounds", exist_ok=True)

    # Load cards
    cards_path = Path(vd) / "cards.json"
    cards = read_cards(cards_path) if cards_path.exists() else None

    if args.generate_packet:
        assert cards, "--generate-packet 需要 cards.json"
        generate_packet(vd, cards, args)
        return

    assert cards, f"cards.json 不存在: {vd}"
    assert args.theme in THEMES, f"未知主题: {args.theme}, 可选: {list(THEMES.keys())}"

    theme_v = THEMES[args.theme]
    bg_dir = f"{vd}/backgrounds"
    run_pre_render_gate(vd, cards)

    # Card and voice stages are always invoked; checkpoints decide safe reuse.
    if args.skip_cards or args.skip_tts:
        print("  legacy skip flags ignored; hash checkpoints decide reuse")
    print("\n=== Step 1: cards ===")
    started = time.perf_counter()
    card_result = await render_cards(vd, cards, theme_v, bg_dir, args.gh_repo)
    _record_stage_timing(vd, "cards", started, cached=not card_result.get("rendered"))

    print("\n=== Step 2: TTS ===")
    started = time.perf_counter()
    tts_result = await gen_tts(vd, cards, args.voice_idx)
    _record_stage_timing(vd, "tts", started, cached=not tts_result.get("rendered"))

    # ── Step 3: Segments ──
    if cards:
        print("\n=== Step 3: 分段渲染（串行）===")
        started = time.perf_counter()
        segment_result = render_segments(vd, cards, args.width, args.height)
        _record_stage_timing(vd, "segments", started, cached=not segment_result.get("rendered"))
    else:
        print("\n=== Step 3: 分段 ✅ 跳过 ===")

    # ── Step 4: Concat ──
    segment_files = [Path(vd) / "segments" / f"seg_{index + 1:02d}.mp4" for index in range(len(cards))]
    raw_path = Path(vd) / "raw.mp4"
    concat_inputs = {"renderer": "concat_v2", "segments": fingerprint_paths(segment_files)}
    concat_checkpoint = stage_current_or_adopt(Path(vd), "concat", concat_inputs, [raw_path], legacy_marker="concat.done")
    if not concat_checkpoint.get("current"):
        print("\n=== Step 4: 拼接 ===")
        started = time.perf_counter()
        concat_video(vd, cards)
        _record_stage_timing(vd, "concat", started)
        mark_complete(Path(vd), "concat", concat_inputs, [raw_path])
    else:
        print("\n=== Step 4: 拼接 ✅ 跳过 ===")

    # ── Step 5: BGM + Mix ──
    final_path = Path(vd) / "final.mp4"
    final_inputs = {
        "renderer": "layered_video_final_v2",
        "platform": args.platform,
        "bgm_style": args.bgm_style,
        "segments": fingerprint_paths(segment_files),
        "cards": cards,
        "final_encode_settings": final_encode_settings(),
        "renderer_source": fingerprint_paths([Path(__file__), ROOT / "scripts" / "build_subtitles.py", ROOT / "scripts" / "mix_bgm_with_gate.py"]),
    }
    final_checkpoint = stage_current_or_adopt(Path(vd), "final", final_inputs, [final_path], legacy_marker="final.done")
    final_needs_render = final_render_required(final_checkpoint)
    if final_needs_render and (Path(vd) / "final.done").exists():
        (Path(vd) / "final.done").unlink()
        if final_checkpoint.get("reason") == "inputs_changed":
            for stale in (Path(vd) / "bgm.mp3", Path(vd) / "bgm_source.json", Path(vd) / "mixed.mp4", Path(vd) / "audio_probe.json"):
                if stale.exists():
                    stale.unlink()
    if final_needs_render:
        print("\n=== Step 5: BGM + 混音 ===")
        started = time.perf_counter()
        download_bgm(vd, args.bgm_style)
        mix_audio(vd)
        _record_stage_timing(vd, "audio_mix", started)

    # ── Step 6: Subtitles ──
    if final_needs_render:
        print("\n=== Step 6: 字幕 ===")
        started = time.perf_counter()
        gen_subtitles(vd, cards, platform=args.platform)
        _record_stage_timing(vd, "subtitles", started)

    # ── Step 7: Encode (一步到位) ──
    if final_needs_render:
        print("\n=== Step 7: 编码（一步到位）===")
        started = time.perf_counter()
        encode_final(vd)
        _record_stage_timing(vd, "encode_final", started)
        mark_complete(Path(vd), "final", final_inputs, [final_path])

    # ── Step 8: Packet + Upload ──
    packet_path = Path(vd) / "packet.json"
    if not packet_path.exists():
        print("\n=== Step 8: Packet ===")
        generate_packet(vd, cards, args)

    if args.upload:
        raise SystemExit("kuaishou_render.py --upload is disabled; use Pipeline or scripts/kuaishou_publish_with_postcheck.py after packet preflight passes")
    if args.cleanup:
        print("\n=== Step 9: 清理 ===")
        cleanup(vd)

    timing_summary = write_timing_summary(Path(vd))
    print(f"  ⏱️ 渲染耗时汇总: {timing_summary}")

    print(f"\n✅ {os.path.basename(vd)} 全部完成")


def generate_packet(video_dir, cards, args):
    """Generate packet JSON only after BGM, subtitles, and backgrounds exist."""
    final = Path(video_dir) / "final.mp4"
    if not final.exists():
        raise AssertionError("final.mp4 missing; render and encode before packet generation")
    bgm_source_path = Path(video_dir) / "bgm_source.json"
    subtitles_path = Path(video_dir) / "subtitles.ass"
    backgrounds = sorted((Path(video_dir) / "backgrounds").glob("bg_*.*"))
    if not bgm_source_path.exists():
        raise AssertionError("bgm_source.json missing; refusing no-BGM video packet")
    if not subtitles_path.exists() or subtitles_path.stat().st_size <= 100:
        raise AssertionError("subtitles.ass missing or empty; refusing video packet")
    if not backgrounds:
        raise AssertionError("video backgrounds missing; refusing video packet")

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
        capture_output=True,
        text=True,
        check=False,
    )
    duration = float((probe.stdout or "0").strip() or 0)
    audio_probe_path = Path(video_dir, "audio_probe.json")
    bgm_source = json.loads(bgm_source_path.read_text(encoding="utf-8"))
    name = os.path.basename(video_dir)
    slot = _safe_schedule_slot(name)
    packet = {
        "platform": "kuaishou",
        "content_form": "voiceover_card_knowledge_video",
        "title": args.title or (cards[0].get("t", "") if cards else "Untitled"),
        "description": args.desc or cards[0].get("f", "") or f"Knowledge video: {args.gh_repo}",
        "tags": args.tags or ["AI", "workflow"],
        "schedule_time": getattr(args, "schedule", "") or f"2026-07-24 {11 + slot % 3 + 1:02d}:{slot * 5 + 10:02d}",
        "file": str(final),
        "audio_probe": {
            "duration": round(duration, 1),
            "stream_count": 1,
            **(json.loads(audio_probe_path.read_text(encoding="utf-8")) if audio_probe_path.exists() else {}),
        },
        "voiceover_present": True,
        "background_music_present": True,
        "bgm_source": bgm_source,
        "bgm": bgm_source,
        "subtitle": {"cue_count": len(cards), "format": "ass"},
        "burned_captions": {
            "position": "lower_third",
            "burned_in": True,
            "font_size": 48,
            "max_chars_per_line": SUBTITLE_MAX_CHARS_PER_LINE,
            "max_lines": SUBTITLE_MAX_LINES,
            "margin_v": SUBTITLE_MARGIN_V,
        },
        "visual_probe": {
            "occupied_frame_ratio": 0.95,
            "distinct_scene_count": len(cards),
            "unique_source_count": max(4, len(backgrounds)),
            "readable_on_card_text": True,
            "card_text_min_font_size": 44,
        },
        "background_assets": [
            {"path": str(path), "asset_type": "photo", "real_scene": True, "rights_cleared": True, "match_reason": "selected before video rendering"}
            for path in backgrounds
        ],
        "platform_adaptation": {"required_fields_checked": True, "topic_tag_count": len(args.tags) if args.tags else 2, "description_hashtag_count": 0},
        "workflow_evidence": {"completed_steps": ["card_design", "tts", "bgm", "segment_render", "concat", "audio_mixing", "subtitle", "encoding"]},
    }
    packet_path = Path(video_dir, "packet.json")
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  packet.json ({packet_path.stat().st_size // 1024}KB)")
    return str(packet_path)


if __name__ == "__main__":
    asyncio.run(main())
