"""
gif_utils.py — gif-splitter（104⭐）桥接模块。

GIF动图切分工具，将超过帧数限制的GIF自动拆分成多个小文件。
直接补充 gzh-design-skill + WeChat 发布链的最后一步（公众号300帧限制）。

依赖于：
  - 技能安装于 ~/.hermes/skills/utilities/gif-splitter/
  - Pillow（已安装 12.2.0）

集成方式：
    from .gif_utils import split_gif, get_gif_info
    info = get_gif_info("demo.gif")
    result = split_gif("demo.gif", max_frames=280)
"""

import os, subprocess, sys
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes" / "skills" / "utilities" / "gif-splitter"
SPLIT_SCRIPT = SKILL_DIR / "scripts" / "split_gif.py"


def skill_available() -> bool:
    return SKILL_DIR.is_dir() and (SKILL_DIR / "SKILL.md").exists()


def get_gif_info(path: str) -> dict:
    """
    获取 GIF 文件信息（帧数、大小、尺寸等）。
    使用 Pillow 直接读取，不依赖脚本。
    """
    try:
        from PIL import Image
        img = Image.open(path)
        frames = getattr(img, "n_frames", 1)
        size = os.path.getsize(path)
        return {
            "ok": True,
            "frames": frames,
            "size": size,
            "size_mb": round(size / 1048576, 2),
            "width": img.width,
            "height": img.height,
            "over_limit": frames > 300,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def split_gif(path: str, max_frames: int = 280, output_dir: str = None) -> dict:
    """
    切分 GIF 文件，使其每份不超过 max_frames 帧。

    Args:
        path: GIF 文件路径或包含 GIF 的文件夹路径
        max_frames: 每份最大帧数（默认 280，公众号限制 300）
        output_dir: 自定义输出目录（可选，默认为原目录下的 split_output/）

    Returns:
        {"ok": bool, "files": [str], "count": int, "info": dict}
    """
    if not skill_available():
        return {"ok": False, "error": "gif-splitter skill not installed"}

    if not SPLIT_SCRIPT.is_file():
        return {"ok": False, "error": "split_gif.py not found"}

    # 先获取原始信息
    info = get_gif_info(path)
    if not info.get("ok"):
        return {"ok": False, "error": info.get("error")}

    cmd = [sys.executable, str(SPLIT_SCRIPT), path, "--max-frames", str(max_frames)]
    if output_dir:
        cmd.extend(["-o", output_dir])

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        # 猜测输出目录
        if not output_dir:
            p = Path(path)
            output_dir = str(p.parent / "split_output") if p.is_file() else str(Path(path) / "split_output")

        out_files = []
        if Path(output_dir).is_dir():
            out_files = sorted([str(f) for f in Path(output_dir).glob("*.gif")])

        return {
            "ok": r.returncode == 0,
            "exit_code": r.returncode,
            "files": out_files,
            "count": len(out_files),
            "info": info,
            "stdout": r.stdout,
            "stderr": r.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "split timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="GIF 动图切分工具")
    ap.add_argument("path", help="GIF 文件或文件夹路径")
    ap.add_argument("--max-frames", "-m", type=int, default=280, help="每份最大帧数")
    ap.add_argument("-o", "--output", help="输出目录")
    ap.add_argument("--info", action="store_true", help="仅查看信息，不切分")
    args = ap.parse_args()

    if args.info:
        info = get_gif_info(args.path)
        if info["ok"]:
            print(f"帧数: {info['frames']} 帧")
            print(f"大小: {info['size_mb']} MB")
            print(f"尺寸: {info['width']}x{info['height']}")
            print(f"状态: {'⚠️ 需要切分' if info['over_limit'] else '✅ 正常'}")
        else:
            print(f"❌ {info['error']}")
    else:
        r = split_gif(args.path, max_frames=args.max_frames, output_dir=args.output)
        if r["ok"]:
            print(f"✅ 切分完成 → {r['count']} 个文件")
            for f in r["files"]:
                print(f"  📄 {f}")
        else:
            print(f"❌ {r.get('error', '?')}")
