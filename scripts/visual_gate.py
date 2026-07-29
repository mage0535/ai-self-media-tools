#!/usr/bin/env python3
"""Visual quality gate for generated cards and cover images."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

MIN_SIZE_KB = 30
MIN_DIMENSION = 512
MAX_ASPECT_RATIO = 4


def check_image(path: str, cinema_check: bool = False, min_size_kb: int = MIN_SIZE_KB) -> tuple[bool, list[str]]:
    reports: list[str] = []
    ok = True
    image_path = Path(path)

    if not image_path.exists():
        return False, ["文件不存在"]

    size_kb = image_path.stat().st_size / 1024
    reports.append(f"大小: {size_kb:.0f}KB")
    if size_kb < min_size_kb:
        reports.append(f"小于 {min_size_kb}KB，可能是纯色或空白图")
        ok = False

    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_entries",
                "stream=width,height,codec_name",
                str(image_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode == 0:
            data = json.loads(probe.stdout or "{}")
            streams = data.get("streams", [])
            if streams:
                width = int(streams[0].get("width", 0) or 0)
                height = int(streams[0].get("height", 0) or 0)
                codec = streams[0].get("codec_name", "?")
                reports.append(f"尺寸: {width}x{height}, 编码: {codec}")
                if width < MIN_DIMENSION or height < MIN_DIMENSION:
                    reports.append(f"边长 < {MIN_DIMENSION}px")
                    ok = False
                aspect = max(width, height) / min(width, height) if min(width, height) > 0 else 0
                if aspect > MAX_ASPECT_RATIO:
                    reports.append(f"宽高比 {aspect:.1f}:1 异常")
            else:
                reports.append("无法读取图像信息")
        else:
            reports.append("ffprobe 无法解析")
    except Exception as exc:
        reports.append(f"基础图像检查异常: {exc}")

    try:
        from PIL import Image
        import numpy as np

        image = Image.open(str(image_path))
        arr = np.array(image.convert("L"))
        std = float(arr.std())
        reports.append(f"像素标准差: {std:.1f}")
        if std < 15:
            reports.append(f"标准差 {std:.1f} < 15，画面过于单一")
            ok = False
        elif std < 30:
            reports.append(f"标准差 {std:.1f} < 30，细节偏少")
    except ImportError:
        reports.append("PIL/numpy 不可用，跳过像素标准差检查")
    except Exception as exc:
        reports.append(f"像素标准差检查异常: {exc}")

    if cinema_check:
        try:
            root = str(Path(__file__).resolve().parent.parent)
            if root not in sys.path:
                sys.path.insert(0, root)
            from scripts.cinema_composition import anti_template_check

            cinema_result = anti_template_check(str(image_path))
            reports.append(f"Cinema DNA 检查: {'通过' if cinema_result.get('passed') else '未通过'}")
            for check in cinema_result.get("checks", []):
                reports.append(f"  {check}")
            for suggestion in cinema_result.get("suggestions", []):
                reports.append(f"  建议: {suggestion}")
            if not cinema_result.get("passed"):
                ok = False
        except ImportError:
            reports.append("cinema_composition 不可用，跳过")
        except Exception as exc:
            reports.append(f"cinema 检查异常: {exc}")

    return ok, reports


def main() -> None:
    parser = argparse.ArgumentParser(description="视觉质量门禁")
    parser.add_argument("--image", required=True, help="图片路径")
    parser.add_argument("--min-size", type=int, default=MIN_SIZE_KB, help="最小KB，默认30")
    parser.add_argument("--cinema", action="store_true", help="启用 Cinema DNA 反模板化检查")
    args = parser.parse_args()

    print(f"检查: {args.image}")
    ok, reports = check_image(args.image, cinema_check=args.cinema, min_size_kb=args.min_size)
    for report in reports:
        print(f"  {report}")
    if ok:
        print("\n视觉质量通过")
        sys.exit(0)
    print("\n质量不达标，请重新生成")
    sys.exit(1)


if __name__ == "__main__":
    main()
