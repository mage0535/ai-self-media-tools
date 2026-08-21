#!/usr/bin/env python3
"""自动从 archive.org 下载未用过的真实乐器 BGM 并写 bgm_source.json。

解决「online real-instrument BGM resolution budget exhausted」——定时任务渲染必卡问题。
用法:
  python3 scripts/fetch_bgm_archive.py --out <render_dir> [--collection solo-piano-7] [--min-duration 60]

行为:
  1. 拉取 archive.org metadata 拿真实文件列表（文件名编号不连续，不能猜）
  2. 排除 bgm_fingerprint.json 已登记的所有曲子（撞曲门禁）
  3. 按顺序下载第一个未用过的曲子到 <out>/bgm.mp3
  4. 写 <out>/bgm_source.json（含 license/vocal/sha256，满足 pre_render_gate）
  5. 校验: 文件 >500KB（REAL_BGM_MIN_BYTES 门禁）+ ffprobe 可读 + 时长 >= min_duration
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULT_COLLECTION = "solo-piano-7"
META_URL = "https://archive.org/metadata/{collection}"
DOWNLOAD_URL = "https://archive.org/download/{collection}"
FINGERPRINT_FILE = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser() / "data/bgm_fingerprint.json"
MIN_BYTES = 500 * 1024
DEFAULT_MIN_DURATION = 60.0
LICENSE = "CC-BY-NC-ND 3.0 (archive.org {collection} collection, personal-use video background)"
CST = timezone(timedelta(hours=8))


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def used_fingerprints() -> set[str]:
    try:
        reg = json.loads(FINGERPRINT_FILE.read_text(encoding="utf-8"))
        return {str(t.get("fingerprint") or "") for t in reg.get("tracks", []) if t.get("fingerprint")}
    except Exception:
        return set()


def register_fingerprint(sha256: str, title: str, collection: str) -> None:
    """登记到 bgm_fingerprint.json，防下一条视频撞曲"""
    try:
        reg = json.loads(FINGERPRINT_FILE.read_text(encoding="utf-8"))
        tracks = reg.setdefault("tracks", [])
    except Exception:
        reg = {"tracks": []}
        tracks = reg["tracks"]
    today = datetime.now(CST).strftime("%Y-%m-%d")
    tracks.append({
        "title": title, "artist": "Torley", "source": f"archive.org {collection}",
        "fingerprint": sha256, "used_date": today,
    })
    FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[register] {title} sha256={sha256[:16]} -> {FINGERPRINT_FILE}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=".", help="输出目录（bgm.mp3 + bgm_source.json 写入处）")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="archive.org collection")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION, help="最短时长秒")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    collection = args.collection
    min_duration = args.min_duration

    print(f"[1/5] 拉取 archive.org metadata: {collection}")
    try:
        meta = fetch_json(META_URL.format(collection=collection))
    except Exception as e:
        print(f"      metadata 获取失败: {str(e)[:100]}", file=sys.stderr)
        return 1
    mp3s = sorted(f["name"] for f in meta.get("files", []) if f["name"].endswith(".mp3"))
    if not mp3s:
        print(f"      collection 无 MP3 文件", file=sys.stderr)
        return 1
    print(f"      目录共 {len(mp3s)} 首 MP3")

    used = used_fingerprints()
    print(f"[2/5] 已登记指纹 {len(used)} 个（撞曲排除）")

    bgm_path = out_dir / "bgm.mp3"
    src_path = out_dir / "bgm_source.json"
    for name in mp3s:
        quoted = urllib.parse.quote(name)
        url = f"{DOWNLOAD_URL.format(collection=collection)}/{quoted}"
        print(f"[3/5] 尝试: {name}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                content = r.read()
        except Exception as e:
            print(f"      下载失败: {str(e)[:80]}")
            continue
        if len(content) < MIN_BYTES:
            print(f"      跳过: {len(content)//1024}KB < {MIN_BYTES//1024}KB")
            continue
        sha = hashlib.sha256(content).hexdigest()
        if sha in used:
            print(f"      跳过: 已用（撞曲）")
            continue
        # 双保险：重新读取指纹库（可能有并发/外部登记）
        if sha in used_fingerprints():
            print(f"      跳过: 指纹库实时校验撞曲")
            continue
        # 写 bgm.mp3
        bgm_path.write_bytes(content)
        print(f"      OK bgm.mp3 {len(content)//1024}KB sha256={sha[:16]}")

        # ffprobe 校验时长
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(bgm_path)], capture_output=True, text=True, timeout=30)
        try:
            dur = float(r.stdout.strip())
        except ValueError:
            dur = 0.0
        if dur < min_duration:
            print(f"      时长不足 {dur:.1f}s < {min_duration:.0f}s，换下一首")
            bgm_path.unlink(missing_ok=True)
            continue
        print(f"      时长 {dur:.1f}s ✅")

        # 写 bgm_source.json（license 字段必须，pre_render_gate 要求）
        now = datetime.now(CST).isoformat(timespec="seconds")
        src = {
            "source": f"archive.org {collection}",
            "title": name.replace(".mp3", ""),
            "artist": "Torley",
            "url": url,
            "license": LICENSE.format(collection=collection),
            "vocal": "none",
            "real_instrument": True,
            "duration": round(dur, 1),
            "sha256": sha,
            "downloaded_at": now,
            "manifest": {"fingerprint": sha, "vocal": "none", "real_instrument": True},
        }
        src_path.write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8")
        register_fingerprint(sha, name.replace(".mp3", ""), collection)
        print(f"[4/5] bgm_source.json 已写（含 license）")
        print(f"[5/5] 完成: {bgm_path}")
        return 0

    # 全部失败：清理残留 bgm（防半成品被渲染器误用）
    bgm_path.unlink(missing_ok=True)
    print("FAIL: 所有候选均已使用或下载失败", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
