#!/usr/bin/env python3
"""渲染前时长预估：cinematic 模式成片时长 ≈ 总字数 × 0.226。

2026-08-16 实测（film_renderer cinematic-v8, edge-tts zh-CN-YunjianNeural -5%）:
  脚本 272字 → 成片 64.9s  (超 60s 上限)
  脚本 245字 → 成片 60.2s  (临界)
  脚本 246字 → 成片 59.05s (达标)
  → 比例 ≈ 0.226s/字；抖音目标 ≤55s → 脚本 ≤245 字

用法:
  python3 scripts/douyin_video_length_check.py <script.md> [--max-seconds 60]
"""
import re
import sys
from pathlib import Path

RATIO = 0.226  # cinematic 模式实测秒/字
MIN_SEGMENTS = 8
SEG_MIN = 30
SEG_MAX = 90


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"FAIL: 脚本文件不存在: {path}", file=sys.stderr)
        return 1
    script = path.read_text(encoding="utf-8").strip()
    max_seconds = float(sys.argv[sys.argv.index("--max-seconds") + 1]) if "--max-seconds" in sys.argv else 60.0

    segs = [s.strip() for s in re.split(r"\n\s*\n", script) if s.strip()]
    total = sum(len(s) for s in segs)
    est = total * RATIO
    lens = [len(s) for s in segs]

    ok_segments = len(segs) >= MIN_SEGMENTS
    ok_len = len(segs) >= MIN_SEGMENTS and all(SEG_MIN <= l <= SEG_MAX for l in lens)
    ok_time = est <= max_seconds

    print(f"段数: {len(segs)} (需≥{MIN_SEGMENTS}) {'✅' if ok_segments else '❌'}")
    print(f"段长: {lens}")
    print(f"总字数: {total}")
    print(f"估算成片时长: {est:.1f}s (比例 {RATIO}s/字) | 上限 {max_seconds:.0f}s {'✅' if ok_time else '❌'}")
    if lens:
        bad = [i + 1 for i, l in enumerate(lens) if not (SEG_MIN <= l <= SEG_MAX)]
        print(f"段长全部 {SEG_MIN}-{SEG_MAX}: {'✅' if ok_len else '❌ 段' + str(bad)}")
    if not ok_time:
        print(f"提示: 需精简到 ≤{int(max_seconds / RATIO)} 字")
    return 0 if (ok_segments and ok_len and ok_time) else 1


if __name__ == "__main__":
    raise SystemExit(main())
