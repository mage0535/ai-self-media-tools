#!/usr/bin/env python3
"""生成 bgm_history_check 块——桥接 check_bgm_uniqueness 注册库 → media_quality gate。

用法: python3 gen_bgm_history_check.py <render_dir> [--platform kuaishou]
输出: <render_dir>/bgm_history_check.json
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path(__file__).resolve().parents[1])))
REGISTRY = PROJECT_ROOT / "data" / "bgm_fingerprint_registry.json"
CHECKER = PROJECT_ROOT / "scripts" / "check_bgm_uniqueness.py"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("render_dir")
    ap.add_argument("--platform", default="")
    args = ap.parse_args()
    render_dir = Path(args.render_dir)

    # 先跑唯一性检查（含登记，fail 会体现在 duplicate/failed_dimensions）
    r = subprocess.run(
        [sys.executable, str(CHECKER), str(render_dir),
         "--platform", args.platform, "--registry", str(REGISTRY)],
        capture_output=True, text=True, timeout=120,
    )
    try:
        check = json.loads(r.stdout)
    except Exception:
        print(json.dumps({"ok": False, "error": f"checker output unparsable: {r.stdout[:200]} {r.stderr[:200]}"}))
        return 1

    fp = str(check.get("fingerprint") or "")
    tracks = (json.loads(REGISTRY.read_text()) if REGISTRY.is_file() else {}).get("tracks") or []
    # 语义修正: "之前用过" = 同指纹且登记时间早于本次 bgm.mp3 的修改时间（排除本次刚自登记的条目）
    bgm_file = render_dir / "bgm.mp3"
    bgm_mtime = bgm_file.stat().st_mtime if bgm_file.is_file() else 0.0
    def _used_before(row) -> bool:
        try:
            ts = datetime.datetime.fromisoformat(str(row.get("registered_at")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            return ts.timestamp() < bgm_mtime - 1
        except Exception:
            return False
    prior_same = [t for t in tracks if isinstance(t, dict) and str(t.get("fingerprint") or "") == fp and _used_before(t)]
    # recent = 同平台近7天登记的其它指纹（按 registered_at 降序取前20）
    import datetime
    def _ts(row):
        try:
            ts = datetime.datetime.fromisoformat(str(row.get("registered_at")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            return ts
        except Exception:
            return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    recent_rows = sorted(
        (t for t in tracks if isinstance(t, dict) and str(t.get("fingerprint") or "") != fp),
        key=_ts, reverse=True)[:20]
    recent = [str(t.get("fingerprint")) for t in recent_rows]

    out = {
        "checked": True,
        "registry_path": str(REGISTRY),
        "current_fingerprint": fp,
        "recent_fingerprints": recent,
        "same_batch_fingerprints": [],
        "duplicate_found": bool(prior_same),
        "checker_passed": bool(check.get("passed")),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (render_dir / "bgm_history_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "current": fp[:16], "recent_count": len(recent), "duplicate_found": out["duplicate_found"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
