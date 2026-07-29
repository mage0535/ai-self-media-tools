#!/usr/bin/env python3
"""
视觉质量门禁 — 生成后验证图片/卡片输出质量

用法:
  python3 visual_gate.py --image /tmp/card.png
  python3 visual_gate.py --image /tmp/cover.jpg --min-size 100 --cinema

退出码: 0=通过, 1=不通过
"""
import argparse, json, subprocess, sys
from pathlib import Path

MIN_SIZE_KB = 30         # 最小文件大小 (KB)
MIN_DIMENSION = 512    # 最小边长
MAX_ASPECT_RATIO = 4   # 最大宽高比 (防止畸变)

def check_image(path: str, cinema_check: bool = False, min_size_kb: int = MIN_SIZE_KB) -> tuple[bool, list[str]]:
    """检查图片质量"""
    reports = []
    ok = True
    p = Path(path)
    
    if not p.exists():
        return False, ["❌ 文件不存在"]
    
    size_kb = p.stat().st_size / 1024
    reports.append(f"📦 大小: {size_kb:.0f}KB")
    
    if size_kb < min_size_kb:
        reports.append(f"  ❌ 小于 {min_size_kb}KB，可能是纯色/空白图")
        ok = False
    
    # 用 ffprobe 获取图片信息
    try:
        r = subprocess.run([
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_entries", "stream=width,height,codec_name",
            str(p)
        ], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            data = json.loads(r.stdout)
            streams = data.get("streams", [])
            if streams:
                w = streams[0].get("width", 0)
                h = streams[0].get("height", 0)
                codec = streams[0].get("codec_name", "?")
                reports.append(f"📐 尺寸: {w}×{h}, 编码: {codec}")
                
                if w < MIN_DIMENSION or h < MIN_DIMENSION:
                    reports.append(f"  ❌ 边长 < {MIN_DIMENSION}px")
                    ok = False
                
                aspect = max(w, h) / min(w, h) if min(w, h) > 0 else 0
                if aspect > MAX_ASPECT_RATIO:
                    reports.append(f"  ⚠ 宽高比 {aspect:.1f}:1 异常")
                
                # 检查是否是纯色（用 PIL 计算像素标准差）
                try:
                    from PIL import Image
                    import numpy as np
                    img = Image.open(str(p))
                    arr = np.array(img.convert("L"))  # 灰度
                    std = arr.std()
                    reports.append(f"🎨 像素标准差: {std:.1f} (值越大越丰富)")
                    if std < 15:
                        reports.append(f"  ❌ 标准差 {std:.1f} < 15，画面太单一")
                        ok = False
                    elif std < 30:
                        reports.append(f"  ⚠ 标准差 {std:.1f} < 30，细节不足")
                except ImportError:
                    reports.append(f"  ⚠ 无法安装PIL/numpy，跳过对比度检测")
                except Exception as e:
                    reports.append(f"  ⚠ 对比度检测异常: {e}")
            else:
                reports.append("  ⚠ 无法读取图像信息")
        else:
            reports.append(f"  ⚠ ffprobe 无法解析")
    except Exception as e:
        reports.append(f"  ⚠ 检查异常: {e}")

    # Cinema DNA 反模板化检查
    if cinema_check:
        try:
            import sys as _sys
            _p = str(Path(__file__).resolve().parent.parent)
            if _p not in _sys.path:
                _sys.path.insert(0, _p)
            from scripts.cinema_composition import anti_template_check as cinema_atc
            cinema_result = cinema_atc(path)
            reports.append(f"🎬 Cinema DNA 检查: {'通过' if cinema_result['passed'] else '未通过'}")
            for c in cinema_result.get("checks", []):
                if any(s in c for s in ("❌", "⚠️")):
                    reports.append(f"  {c}")
            for s in cinema_result.get("suggestions", []):
                reports.append(f"  💡 {s}")
            if not cinema_result["passed"]:
                ok = False
        except ImportError:
            reports.append("  ⚠ cinema_composition 模块不可用，跳过")
        except Exception as e:
            reports.append(f"  ⚠ cinema 检查异常: {e}")

    return ok, reports

def main():
    parser = argparse.ArgumentParser(description="视觉质量门禁")
    parser.add_argument("--image", required=True, help="图片路径")
    parser.add_argument("--min-size", type=int, default=30, help="最小KB (默认30)")
    parser.add_argument("--cinema", action="store_true", help="启用 Cinema DNA 反模板化检查")
    args = parser.parse_args()

    print(f"🔍 检查: {args.image}")
    ok, reports = check_image(args.image, cinema_check=args.cinema, min_size_kb=args.min_size)
    for r in reports:
        print(f"  {r}")

    if ok:
        print(f"\n✅ 视觉质量通过")
        sys.exit(0)
    else:
        print(f"\n❌ 质量不达标，请重新生成")
        sys.exit(1)

if __name__ == "__main__":
    main()
