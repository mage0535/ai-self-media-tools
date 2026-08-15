#!/usr/bin/env python3
"""Overnight batch quality regression checks — guards the 12 fixes from 2026-08-14.
Run after any video render to verify: background uniqueness, motion diversity,
platform TTS language, JSON parse tolerance, cover optimization, packet preflight.
"""
import json, hashlib, os, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path(__file__).resolve().parents[1])))
failures = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)

def md5s(paths):
    return [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]

def check_backgrounds(vid, minimum=6):
    bg_dir = ROOT / f"data/artifacts/{vid}/backgrounds"
    if not bg_dir.exists():
        return 0, 0
    files = sorted(bg_dir.glob("*.png"))
    unique = len(set(md5s(files)))
    check(f"{vid} backgrounds unique", len(files) >= 8 and unique >= minimum, f"{unique}/{len(files)} unique")

def check_motion(vid, minimum=6):
    ev = ROOT / f"data/artifacts/{vid}/segment_motion_evidence.json"
    if not ev.exists():
        check(f"{vid} motion evidence", False, "missing segment_motion_evidence.json")
        return
    moves = [s.get("move_id") for s in json.loads(ev.read_text()).get("segments", [])]
    check(f"{vid} motion diversity", len(set(moves)) >= minimum, f"{len(set(moves))} moves: {moves}")

def check_tts_platform(vid, platform):
    st = ROOT / f"data/artifacts/{vid}/.render_state/tts_01.json"
    if not st.exists():
        check(f"{vid} tts voice", False, "no render_state")
        return
    voice = json.loads(st.read_text()).get("inputs", {}).get("voice", "")
    en = platform in {"tiktok", "youtube", "youtube_shorts", "twitter", "x"}
    ok = (voice.startswith("en-") if en else voice.startswith("zh-"))
    check(f"{vid} tts language ({platform})", ok, f"voice={voice}")

def check_duration(vid):
    final = ROOT / f"data/artifacts/{vid}/final.mp4"
    if not final.exists():
        check(f"{vid} final.mp4", False, "missing")
        return
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                               capture_output=True, text=True).stdout.strip() or 0)
    check(f"{vid} duration", 40 <= dur <= 100, f"{dur:.1f}s")

def check_motion_score(vid):
    sys.path.insert(0, str(ROOT))
    from content_platform.video_artifact import measure_motion
    final = ROOT / f"data/artifacts/{vid}/final.mp4"
    score = measure_motion(final)
    check(f"{vid} motion_score", score >= 0.01, f"{score}")

def check_cover(vid):
    cover = ROOT / f"data/artifacts/{vid}/cover.png"
    ok = cover.exists() and cover.stat().st_size > 500 * 1024  # HTML-rendered = high density
    check(f"{vid} optimized cover", ok, f"{cover.stat().st_size//1024}KB" if cover.exists() else "missing")

def check_packet_preflight(vid, platform):
    packet = ROOT / f"data/artifacts/{vid}/packet.json"
    if not packet.exists():
        check(f"{vid} packet", False, "missing")
        return
    # Kuaishou is the only platform that auto-uploads via SAU and must pass
    # the full 12/12 preflight. Handoff platforms (douyin/tiktok) only need
    # the core media evidence since a human publishes them.
    if platform not in {"kuaishou"}:
        p = json.loads(packet.read_text())
        core_ok = bool(p.get("video_artifact_probe", {}).get("file_exists"))
        check(f"{vid} packet core evidence (handoff)", core_ok, "video_artifact_probe.file_exists")
        return
    r = subprocess.run([sys.executable, str(ROOT / "scripts/validate_kuaishou_auto_packet.py"), str(packet), "--phase", "preflight"],
                       capture_output=True, text=True)
    try:
        result = json.loads(r.stdout)
        check(f"{vid} packet preflight", result.get("passed"), f"{result.get('score')}/{result.get('total')}")
    except Exception as e:
        check(f"{vid} packet preflight", False, str(e))

def check_json_parse_tolerance():
    sys.path.insert(0, str(ROOT))
    from content_platform.generator import DraftGenerator
    raw = '{"title": "T", "body": {"chars": 10, "excerpt": "Wrapped body\\nwith newline"}, "hook": "Why?"}'
    d = DraftGenerator._extract_fields_tolerant(raw)
    check("JSON wrapped-body parse", d.get("body", "").startswith("Wrapped body"), repr(d.get("body"))[:40])
    raw2 = '{"title": "T2", "body": "Plain text body"}'
    d2 = DraftGenerator._extract_fields_tolerant(raw2)
    check("JSON plain-body parse", d2.get("body") == "Plain text body")

def main():
    videos = [
        ("kuaishou", "110d63d9345143f0", "kuaishou"),
        ("douyin_ai", "4ad4d1dc14a641b3", "douyin"),
        ("tiktok", "b7a2b8db91164d76", "tiktok"),
    ]
    print("=== overnight quality regression ===")
    for name, vid, platform in videos:
        print(f"-- {name} ({vid[:12]}) --")
        check_backgrounds(vid)
        check_motion(vid)
        check_tts_platform(vid, platform)
        check_duration(vid)
        check_motion_score(vid)
        check_cover(vid)
        check_packet_preflight(vid, platform)
    print("-- cross-video background uniqueness --")
    all_bg = []
    for _, vid, _ in videos:
        all_bg += [str(p) for p in (ROOT / f"data/artifacts/{vid}/backgrounds").glob("*.png")]
    unique = len(set(md5s(all_bg)))
    check("cross-video backgrounds", unique == len(all_bg), f"{unique}/{len(all_bg)}")
    print("-- generator parse tolerance --")
    check_json_parse_tolerance()
    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} checks)")
        sys.exit(1)
    print("RESULT: ALL PASS")

if __name__ == "__main__":
    main()
