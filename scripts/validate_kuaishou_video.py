#!/usr/bin/env python3
"""快手视频全自动门禁 v2 — 深度审计后强化"""
import subprocess, sys, json, os, re
from pathlib import Path
from datetime import datetime

# ── 全局常量 ──
CN_PROXY = "socks5://127.0.0.1:1080"
MIN_CARD_SIZE = 100_000
MIN_TTS_SIZE = 10_000
MIN_SEG_SIZE = 1000
MIN_RAW_SIZE = 10_000
MIN_FINAL_SIZE = 10_000
MIN_DURATION = 35
VOL_MIN = -18
VOL_MAX = -14
MIN_SCHEDULE_HOURS = 2
BGM_LOWPASS_THRESHOLD = 5  # dB

def die(msg): print(f"❌ {msg}"); sys.exit(1)
def ok(msg): print(f"  ✅ {msg}")
def warn(msg): print(f"  ⚠️ {msg}")

def get_vol(f):
    r = subprocess.run(["ffmpeg","-i",str(f),"-af","volumedetect","-f","null","-"], capture_output=True, text=True)
    for l in (r.stderr + "\n" + r.stdout).split("\n"):
        if "mean_volume" in l:
            m = re.search(r"mean_volume: ([\-\d\.]+)", l)
            if m: return float(m.group(1))
    return None

def has_audio(f):
    r = subprocess.run(["ffprobe","-v","error","-select_streams","a","-show_entries","stream=codec_type","-of","csv=p=0",str(f)], capture_output=True, text=True)
    return "audio" in r.stdout

def get_duration(f):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(f)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

def get_bitrate(f):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","stream=bit_rate","-of","csv=p=0",str(f)], capture_output=True, text=True)
    rates = [float(x) for x in r.stdout.strip().split("\n") if x]
    return rates[0] / 1000 if rates else 0  # kbps

# ── 资源预检 ──
def check_resources():
    print("\n📊 资源预检:")
    # CN代理
    try:
        r = subprocess.run(["curl","-s","--max-time","8","--socks5","127.0.0.1:1080","https://httpbin.org/ip"], capture_output=True, text=True, timeout=12)
        ip_data = json.loads(r.stdout)
        ip = ip_data.get("origin", "")
        expected_ips = [x.strip() for x in os.getenv("KUAISHOU_EXPECTED_CN_PROXY_IPS", "").split(",") if x.strip()]
        if expected_ips and not any(expected in ip for expected in expected_ips):
            die("CN代理IP异常: 当前出口不在 KUAISHOU_EXPECTED_CN_PROXY_IPS 白名单中")
        if ip:
            ok("CN代理: 出口IP已验证")
        else:
            die("CN代理IP异常: 未返回出口IP")
    except Exception as e:
        die(f"CN代理不可用: {str(e)[:80]}")
    # 磁盘
    st = os.statvfs("/tmp")
    free_gb = st.f_frsize * st.f_bavail / (1024**3)
    ok(f"磁盘: {free_gb:.1f}GB" + (" ✅" if free_gb > 2 else " ⚠️"))
    if free_gb < 1: die("磁盘不足1GB")
    # 内存
    try:
        mem = open("/proc/meminfo").read()
        free = int(re.search(r"MemAvailable:\s+(\d+)", mem).group(1)) / 1024
        ok(f"内存: {free:.0f}MB" + (" ✅" if free > 500 else " ⚠️"))
        if free < 200: die("内存不足200MB")
    except: pass
    # CPU负载
    try:
        load = open("/proc/loadavg").read().split()[0]
        load_val = float(load)
        cpus = os.cpu_count() or 1
        ok(f"CPU负载: {load} (核数:{cpus})" + (" ✅" if load_val < cpus * 0.8 else " ⚠️ 过高"))
    except: pass
    # SAU cookie
    try:
        sau_cli = Path(os.environ.get("SOCIAL_AUTO_UPLOAD_DIR", str(Path.home() / "social-auto-upload"))) / "sau_cli.py"
        r = subprocess.run(["python3", str(sau_cli), "kuaishou", "check", "--account", "main"],
            capture_output=True, text=True, timeout=15)
        if "SUCCESS" in r.stdout:
            ok("SAU cookie 有效")
        else:
            warn(f"SAU cookie状态异常: {r.stdout[:60]}")
    except Exception as e:
        warn(f"SAU cookie检查失败: {str(e)[:60]}")

# ── BGM频谱验证 ──
def check_bgm_spectrum(d):
    bgm = None
    for p in Path(d).glob("bgm*.mp3"):
        bgm = p
        break
    if not bgm:
        die("BGM file is missing; spectrum gate cannot pass")

    def measure(filter_chain):
        result = subprocess.run(
            ["ffmpeg", "-t", "5", "-i", str(bgm), "-af", filter_chain, "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        match = re.search(r"mean_volume: ([\-\d\.]+)", result.stderr + "\n" + result.stdout)
        return float(match.group(1)) if match else None

    orig = measure("volumedetect")
    filtered = measure("lowpass=f=1000,volumedetect")
    if orig is None or filtered is None:
        die("BGM spectrum is not parseable; gate cannot pass")
    drop = orig - filtered
    if drop >= BGM_LOWPASS_THRESHOLD:
        die(f"BGM may be synthetic/electronic: original={orig}dB lowpass={filtered}dB drop={drop:.1f}dB")
    if orig < -30:
        die(f"BGM source too quiet: {orig:.1f}dB < -30dB")
    ok(f"BGM spectrum passed: original={orig}dB lowpass={filtered}dB drop={drop:.1f}dB")
    return
    if not bgm:
        die("BGM文件不存在，不能跳过频谱验证")
    r = subprocess.run(["ffmpeg","-t","5","-i",str(bgm),
        "-filter_complex","[0:a]asplit=2[orig][lp];[lp]lowpass=f=1000[lpf]",
        "-map","[orig]","-map","[lpf]","-f","null","-"],
        capture_output=True, text=True, timeout=30)
    vols = re.findall(r"mean_volume: ([\-\d\.]+)", r.stderr + "\n" + r.stdout)
    if len(vols) < 2:
        die("BGM频谱无法解析，不能通过门禁")
    orig = float(vols[0])
    filtered = float(vols[1])
    drop = orig - filtered
    if drop < BGM_LOWPASS_THRESHOLD:
        die(f"BGM可能电子乐！原始{orig}dB→低通后{filtered}dB，衰减仅{drop:.1f}dB")
    ok(f"BGM频谱通过（原{orig}dB→低通{filtered}dB，衰减{drop:.1f}dB）")


def check_bgm_audibility(d):
    raw = Path(d) / "raw.mp4"
    final = Path(d) / "final.mp4"
    if not raw.exists() or not final.exists():
        return

    def high_freq_mean(path):
        result = subprocess.run(
            ["ffmpeg", "-i", str(path), "-af", "highpass=f=2000,volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        match = re.search(r"mean_volume:\s*([-\d.]+)", result.stderr + "\n" + result.stdout)
        return float(match.group(1)) if match else None

    raw_hf = high_freq_mean(raw)
    final_hf = high_freq_mean(final)
    if raw_hf is None or final_hf is None:
        warn("BGM audibility probe unavailable")
        return
    lift = final_hf - raw_hf
    if lift < 1.0:
        die(f"BGM inaudible: final high-frequency lift {lift:.1f}dB < 1dB")
    ok(f"BGM audibility passed: high-frequency lift {lift:.1f}dB")


def check_burned_subtitles(final, ass, min_white_ratio=0.002):
    if not final.exists() or not ass.exists():
        die("subtitle burn-in probe missing final.mp4 or ASS file")
    dur = get_duration(final)
    if dur < 5:
        die("subtitle burn-in probe cannot read video duration")
    import tempfile

    probe = Path(tempfile.gettempdir()) / "kuaishou_subtitle_probe.png"
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{dur * 0.6:.2f}", "-i", str(final), "-frames:v", "1", str(probe)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not probe.exists():
        die("subtitle burn-in probe failed to extract frame")
    try:
        from PIL import Image
    except Exception:
        warn("PIL unavailable; subtitle burn-in pixel probe skipped")
        return
    image = Image.open(probe).convert("RGB")
    width, height = image.size
    white = total = 0
    pixels = image.load()
    for y in range(int(height * 0.70), int(height * 0.94), 2):
        for x in range(0, width, 2):
            r, g, b = pixels[x, y]
            white += int(r > 200 and g > 200 and b > 200)
            total += 1
    ratio = white / total if total else 0
    if ratio < min_white_ratio:
        die(f"subtitle burn-in probe failed: lower-third white ratio {ratio:.4f} < {min_white_ratio}")
    ok(f"subtitle burn-in probe passed: lower-third white ratio {ratio:.4f}")

# ── 黑帧检测 ──
def check_black_frames(f):
    """检测视频是否有大面积黑帧（损坏/渲染失败）"""
    if not Path(f).exists(): return
    r = subprocess.run(["ffmpeg","-i",str(f),"-vf","blackdetect=d=0.5:pic_th=0.95","-f","null","-"],
        capture_output=True, text=True, timeout=30)
    black_secs = re.findall(r"black_duration:([\d\.]+)", r.stdout)
    total_black = sum(float(x) for x in black_secs)
    dur = get_duration(f)
    if dur > 0 and total_black > max(dur * 0.5, 5):
        warn(f"视频 {Path(f).name} 黑帧 {total_black:.1f}s/{dur:.1f}s，可能损坏")

# ── ASS时间戳验证 ──
def check_ass_timestamps(d):
    for name in ["subtitles.ass", "subs.ass"]:
        ass = Path(d) / name
        if ass.exists():
            content = ass.read_text(encoding="utf-8")
            if "," in content[:500]:
                comma_times = re.findall(r"\d+:\d+:\d+,\d+", content[:500])
                if comma_times:
                    warn(f"ASS文件含逗号时间戳（{comma_times[0]}），libass可能解析失败")
            break
    # 如果都没找到，check_ass_timestamps不做处理

# ── 卡片内容检测（OCR）──
def check_card_content(d):
    """用OCR检测卡片上的关键内容"""
    try:
        import pytesseract
        from PIL import Image
    except:
        warn("pytesseract不可用，跳过卡片OCR检测")
        return

    # 检测 card_02: GitHub截图嵌入
    c2 = Path(d) / "card_02.png"
    if c2.exists():
        sz = c2.stat().st_size
        if sz < 50000:
            warn(f"card_02仅{sz//1024}KB（<50KB），可能未嵌入GitHub截图")
        # OCR检测是否含"git"相关文字
        try:
            text = pytesseract.image_to_string(Image.open(c2), lang='eng+chi_sim')
            if "git" not in text.lower() and "hub" not in text.lower() and "pull" not in text.lower():
                warn("card_02 OCR未检测到\"github\"文字，可能缺少项目截图")
            else:
                ok(f"card_02: {sz//1024}KB, OCR含github信息")
        except:
            warn("card_02 OCR识别失败")

    # 检测 card_08: 完整URL
    c8 = Path(d) / "card_08.png"
    if c8.exists():
        try:
            text = pytesseract.image_to_string(Image.open(c8), lang='eng+chi_sim')
            if "https://github.com" in text or "github.com" in text:
                ok(f"card_08: 检测到完整GitHub URL")
            elif "github" in text.lower():
                warn("card_08含\"github\"但缺少\"https://\"前缀，可能不是完整URL")
            else:
                warn("card_08 OCR未检测到github信息，可能缺少项目链接")
        except:
            warn("card_08 OCR识别失败")

    # 卡片布局多样性（通过文件大小分布判断）
    cards = sorted(Path(d).glob("card_*.png"))
    if len(cards) >= 7:
        sizes = [c.stat().st_size for c in cards]
        unique_ratios = len(set(s // 10000 for s in sizes))  # 按10KB分组
        if unique_ratios < 4:
            warn(f"卡片大小分布单一（{unique_ratios}种/8张），可能布局重复")
        else:
            ok(f"卡片布局多样性: {unique_ratios}种大小分布")

# ── 门禁核心 ──
def run_gates(d):
    print("\n🔍 逐项门禁:")

    # 卡片 — 支持7张或8张
    cards = sorted(Path(d).glob("card_*.png"))
    if len(cards) < 7: die(f"卡片不足: {len(cards)}（需要7-8张）")
    small_cards = [c for c in cards if c.stat().st_size < 100_000]
    if small_cards:
        for c in small_cards: warn(f"卡片 {c.name} 仅 {c.stat().st_size//1024}KB")
        die(f"{len(small_cards)}张卡片 <100KB（可能纯色背景）")
    ok(f"卡片{len(cards)}张全部 >100KB")

    # TTS — 支持 tts_1 或 tts_01 格式
    found_tts = 0
    for i in range(1, 9):
        for name in [f"tts_{i:02d}.mp3", f"tts_{i}.mp3"]:
            f = Path(d) / name
            if f.exists() and f.stat().st_size > 10000:
                found_tts += 1; break
    if found_tts < len(cards): die(f"TTS不足: {found_tts}/{len(cards)}")
    ok(f"TTS {found_tts}段全部存在")

    # Segments + 音频
    seg_ok = 0
    for i in range(1, 9):
        for name in [f"seg_{i:02d}.mp4", f"seg_{i}.mp4"]:
            f = Path(d) / name
            if f.exists() and f.stat().st_size > 1000 and has_audio(f):
                seg_ok += 1; break
    need_seg = min(found_tts, 8)
    if seg_ok < need_seg: die(f"segment不足: {seg_ok}/{need_seg}（无音频）")
    ok(f"segment{seg_ok}段全部有音频")

    # mixed.mp4 — 检查混音中间产物
    mixed = d / "mixed.mp4"
    if mixed.exists() and mixed.stat().st_size > 10000:
        mv = get_vol(mixed)
        ok(f"mixed.mp4 混音完成" + (f" ({mv}dB)" if mv else ""))

    # raw.mp4
    raw = d / "raw.mp4"
    if not raw.exists() or raw.stat().st_size < MIN_RAW_SIZE or not has_audio(raw):
        die("raw.mp4 缺失/无音频")
    dur = get_duration(raw)
    if dur < MIN_DURATION: die(f"raw.mp4 时长 {dur:.1f}s < {MIN_DURATION}s")
    ok(f"raw.mp4: {dur:.1f}s")

    # concat.txt 验证
    ct = d / "concat.txt"
    if ct.exists():
        entries = ct.read_text().strip().count("file ")
        if entries < 7: warn(f"concat.txt 仅 {entries} 条（异常）")
        else: ok(f"concat.txt: {entries} 条")

    # final.mp4
    final = d / "final.mp4"
    if not final.exists() or final.stat().st_size < MIN_FINAL_SIZE:
        die("final.mp4 缺失")
    if not has_audio(final):
        die("final.mp4 无音频流")
    vol = get_vol(final)
    if vol is None or vol < VOL_MIN or vol > VOL_MAX:
        die(f"final.mp4 音量 {vol}dB（需{VOL_MIN}~{VOL_MAX}dB）")
    dur2 = get_duration(final)

    # 检查final vs mixed 大小 — 字幕烧录不应大幅缩小文件
    if mixed.exists() and mixed.stat().st_size > 10000:
        ratio = final.stat().st_size / mixed.stat().st_size
        if ratio < 0.3:
            warn(f"final.mp4 ({final.stat().st_size//1024}KB) << mixed.mp4 ({mixed.stat().st_size//1024}KB)，可能烧录异常")

    # 检查final编码质量
    raw_br = get_bitrate(str(raw))
    final_br = get_bitrate(str(final))
    if final_br > 0 and raw_br > 0 and final_br < raw_br * 0.3:
        warn(f"final.mp4 bitrate {final_br:.0f}kbps << raw {raw_br:.0f}kbps（重编码异常）")
    ok(f"final.mp4: {dur2:.1f}s, {vol}dB, {final.stat().st_size//1024}KB")

    # ASS字幕
    ass_found = None
    for ass_name in ["subtitles.ass", "subs.ass"]:
        ass = Path(d) / ass_name
        if ass.exists():
            cnt = ass.read_text(encoding="utf-8").count("Dialogue:")
            if cnt >= 6:
                ok(f"ASS字幕: {cnt}条 ({ass_name})")
                ass_found = ass
                break
    else:
        die("ASS字幕文件不存在")
    check_ass_timestamps(d)
    if ass_found is not None:
        check_burned_subtitles(final, ass_found)

    # 卡片内容OCR检测
    check_card_content(d)

    # 黑帧检测（final.mp4）
    check_black_frames(final)

    # ── 新增：定时时间验证 ──
    for mf_name in ["manifest.json", "packet.json"]:
        mf = Path(d) / mf_name
        if mf.exists():
            try:
                data = json.loads(mf.read_text())
                sched = data.get("schedule_time") or data.get("schedule", "")
                if sched:
                    sched_dt = datetime.strptime(sched, "%Y-%m-%d %H:%M")
                    now = datetime.now()
                    diff_h = (sched_dt - now).total_seconds() / 3600
                    if diff_h < 2:
                        die(f"定时时间 {sched} 距现在仅 {diff_h:.1f}h（需≥2h）")
                    ok(f"定时 {sched} ({diff_h:.1f}h后)")
            except: pass
        break

# ── 上传 → postcheck 闭环 ──
def upload_and_postcheck(d, manifest_data):
    """Disabled: validation scripts must not publish."""
    die("validate_kuaishou_video.py upload helper is disabled; use scripts/kuaishou_publish_with_postcheck.py after full preflight")
# ── 清理临时文件 ──
def cleanup_workdir(d):
    """上传成功后清理临时文件"""
    keep = ["final.mp4", "manifest.json"]
    # 清理文件
    for f in Path(d).iterdir():
        if f.name not in keep and f.is_file():
            try: f.unlink()
            except: pass
    # 清理子目录 (segs/, tts/, etc.)
    for subdir in Path(d).iterdir():
        if subdir.is_dir() and subdir.name not in keep:
            try:
                for f in subdir.glob("*"):
                    try: f.unlink()
                    except: pass
                subdir.rmdir()
            except: pass
    ok(f"清理完成（保留 {keep}）")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 validate_kuaishou_video.py check <目录>        # 门禁检查")
        print("  python3 validate_kuaishou_video.py self-test           # 自检（验证脚本自身）")
        sys.exit(0)

    # 自检模式
    if sys.argv[1] == "self-test":
        print("🔧 自检模式:")
        script_path = sys.argv[0]
        print(f"  ✅ 脚本可运行 ({Path(script_path).stat().st_size//1024}KB)")
        print(f"  ✅ 函数: {len([n for n in dir() if n.startswith('check_') or n in ['get_vol','has_audio','get_duration','get_bitrate','die','ok','warn','cleanup_workdir','upload_and_postcheck','run_gates']])}个")
        import py_compile
        py_compile.compile(script_path, doraise=True)
        print(f"  ✅ 语法通过")
        print(f"  ✅ 自检完成")
        # 清理
        d = Path("/tmp/ks_self_test")
        if d.exists():
            import shutil
            shutil.rmtree(str(d))
        sys.exit(0)

    cmd = sys.argv[1]
    workdir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/ks_yoinks"
    d = Path(workdir)
    if not d.exists(): die(f"目录不存在: {workdir}")

    if cmd == "check":
        check_resources()
        check_bgm_spectrum(d)
        check_bgm_audibility(d)
        run_gates(d)
        print(f"\n{'='*50}")
        print("✅ 全部门禁通过！")
        print(f"{'='*50}")

    elif cmd == "upload":
        die("validate_kuaishou_video.py upload is disabled; use scripts/kuaishou_publish_with_postcheck.py after the full auto packet passes preflight")
