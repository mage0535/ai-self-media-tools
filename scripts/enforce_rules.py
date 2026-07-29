#!/usr/bin/env python3
"""强制规则预检门禁 v2 — 每次内容生成前自动运行

支持渠道: wechat, kuaishou, douyin, xiaohongshu
输出 JSON 结果，exit 1 阻断。
"""

import json, os, sys, subprocess, re
from pathlib import Path

CHANNEL_RULES = {
    "wechat": {
        "word_count_min": 1200, "word_count_max": 3000,
        "inline_images_min": 3, "cover_required": True,
        "theme_required": True, "theme_count": 109,
        "font_size_body": 16, "digest_max": 54,
        "css_inline": True, "image_format": "cdn_url",
    },
    "kuaishou": {
        "codec": "h264",  # 禁止 mpeg4
        "duration_min": 40, "duration_max": 100,
        "has_hook_3s": True,
        "tts_complete": True,  # 不截断
        "bgm_real_instrument": True,  # 真实乐器演奏
        "bgm_content_matched": True,
        "bgm_volume_max": 0.10,
        "cards_layout_diff": True,  # 多卡差异化
        "schedule_hours_min": 2.05,  # 快手定时≥2h
        "codec_blacklist": ["mpeg4", "mpeg"],
    },
}

def validate_article(path: str, channel: str) -> dict:
    rules = CHANNEL_RULES.get(channel, {})
    if not os.path.exists(path):
        return {"passed": False, "errors": [f"文件不存在: {path}"], "channel": channel}
    
    content = Path(path).read_text(encoding="utf-8")
    ext = Path(path).suffix.lower()
    errors, warnings = [], []
    
    # 字数
    char_count = len(re.sub(r'\s', '', content))
    min_w = rules.get("word_count_min", 0)
    max_w = rules.get("word_count_max", 0)
    if min_w and char_count < min_w:
        errors.append(f"字数不足: {char_count}/{min_w}")
    if max_w and char_count > max_w:
        errors.append(f"字数超限: {char_count}/{max_w}")
    
    # 图片：只认真实 <img 标签
    if channel == "wechat":
        img_count = content.count("<img ")
        min_imgs = rules.get("inline_images_min", 0)
        if min_imgs and img_count < min_imgs:
            errors.append(f"插图不足: {img_count}/{min_imgs}（需真实 <img> 标签，非 <!--IMG--> 注释）")
        
        # 禁止 <!--IMG--> 伪图片
        if "<!--IMG" in content:
            warnings.append("发现 <!--IMG--> 伪图片标记，应替换为真实 <img> 标签")
        
        # 检查微信CDN URL
        if img_count > 0 and not any("mmbiz.qpic.cn" in content for _ in range(1)):
            warnings.append("图片需上传微信CDN（mmbiz.qpic.cn），不接受外部URL")
    
    # 编码检查（视频）
    if channel == "kuaishou" and ext in (".mp4", ".mov"):
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "csv=p=0", path
        ], capture_output=True, text=True, timeout=15)
        codec = probe.stdout.strip()
        blacklist = rules.get("codec_blacklist", [])
        if codec in blacklist:
            errors.append(f"编码 {codec} 被禁止（快手黑屏），需用 h264")
        elif codec != "h264":
            warnings.append(f"编码 {codec}，建议 h264 保证兼容")
        
        # 时长
        dur_p = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path
        ], capture_output=True, text=True, timeout=15)
        try:
            dur = float(dur_p.stdout.strip())
            d_min = rules.get("duration_min", 0)
            d_max = rules.get("duration_max", 0)
            if d_min and dur < d_min:
                errors.append(f"时长不足: {dur:.0f}s/{d_min}s")
            if d_max and dur > d_max:
                errors.append(f"时长超限: {dur:.0f}s/{d_max}s")
        except ValueError:
            pass
    
    # 页面检查（视频或卡片）
    if channel == "kuaishou" and ext == ".mp4":
        # 画面检查（非黑屏）
        vf = subprocess.run([
            "ffmpeg", "-y", "-i", path, "-vframes", "1", "-q:v", "2",
            "/tmp/preflight_verify.jpg"
        ], capture_output=True, timeout=30)
        vf_size = os.path.getsize("/tmp/preflight_verify.jpg") if os.path.exists("/tmp/preflight_verify.jpg") else 0
        if vf_size < 100:
            errors.append(f"画面可能黑屏（verify帧仅{vf_size}B）")
        else:
            os.remove("/tmp/preflight_verify.jpg")
        
        # 音量检查
        vol_r = subprocess.run([
            "ffmpeg", "-i", path, "-af", "volumedetect", "-f", "null", "-"
        ], capture_output=True, text=True, timeout=30)
        mv_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", vol_r.stderr)
        if mv_match:
            mv = float(mv_match.group(1))
            if mv < -25:
                warnings.append(f"音量偏低: {mv}dB（建议≥ -25dB）")
    
    return {
        "passed": len(errors) == 0,
        "channel": channel,
        "char_count": char_count,
        "errors": errors,
        "warnings": warnings,
        "codec": codec if channel == "kuaishou" and ext in (".mp4",".mov") else None,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="内容预检门禁 v2")
    ap.add_argument("--channel", required=True, choices=list(CHANNEL_RULES.keys()))
    ap.add_argument("--content", help="内容文件路径")
    args = ap.parse_args()
    
    if not args.content:
        print(json.dumps({"passed": False, "errors": ["缺少 --content 参数"]}, ensure_ascii=False))
        sys.exit(1)
    
    result = validate_article(args.content, args.channel)
    
    # 输出 JSON（只到第一个空行）
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    
    if not result.get("passed"):
        print("❌ 规则门禁未通过！")
        for e in result.get("errors", []):
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("✅ 规则门禁通过！")
        for w in result.get("warnings", []):
            print(f"  ⚠ {w}")


if __name__ == "__main__":
    main()
