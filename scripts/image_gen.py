#!/usr/bin/env python3
"""
统一生图入口 — 四引擎按优先级调用，自动降级 + 压缩
P0 → Cloudflare FLUX Worker  (2s, 1024x1024, 10万次/天)
P1 → SenseNova U1 Fast      (8-15s, 最高4K, 1500次/5h, 免费)
P2 → Replicate FLUX 1.1 Pro  (13s, 1024x1024, API key)
P3 → Pollinations.ai          (1.5s, 768x768, 无限免key)

用法:
  python3 image_gen.py --prompt "一只猫在书桌上" --output /tmp/cat.jpg
"""
import argparse, json, os, subprocess, sys, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

CF_WORKER = "https://flux-img-v2.samarthnadigprouniversity.workers.dev"
REPLICATE_MODEL = "black-forest-labs/flux-1.1-pro"
MIN_VALID_SIZE = 2048
SN_API_KEY = os.environ.get("SN_API_KEY", "")

def _get_replicate_key():
    return os.environ.get("REPLICATE_API_KEY", "") or _from_env_file("REPLICATE_API_KEY")

def _from_env_file(name):
    env_path = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""

def _compress(output: str):
    size = Path(output).stat().st_size
    if size > 500 * 1024:
        tmp = output + ".tmp.jpg"
        subprocess.run([
            "ffmpeg", "-y", "-i", output,
            "-vf", "scale='min(1200,iw)':'min(1200,ih)':force_original_aspect_ratio=decrease",
            "-q:v", "10", tmp
        ], capture_output=True, timeout=15)
        if Path(tmp).exists():
            Path(tmp).replace(output)

def gen_cf(prompt: str, output: str) -> bool:
    """P0: Cloudflare FLUX Worker"""
    data = json.dumps({"prompt": prompt, "width": 1024, "height": 1024}).encode()
    req = urllib.request.Request(CF_WORKER, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
            if body[:1] == b'{':
                try:
                    err = json.loads(body)
                    if err.get("error"):
                        print(f"[P0 CF] ❌ {err.get('error')}: {err.get('message','')[:80]}")
                        return False
                except: pass
            with open(output, "wb") as f:
                f.write(body)
        size = Path(output).stat().st_size
        if size > MIN_VALID_SIZE:
            print(f"[P0 CF] ✅ {size}B")
            _compress(output)
            return True
        print(f"[P0 CF] ❌ 图片太小 ({size}B)")
    except urllib.error.HTTPError as e:
        print(f"[P0 CF] ❌ HTTP {e.code}")
    except Exception as e:
        print(f"[P0 CF] ❌ {e}")
    return False

def gen_sensenova(prompt: str, output: str) -> bool:
    """P1: SenseNova U1 Fast — 免费，1500次/5h"""
    if not SN_API_KEY:
        print("[P1 SenseNova] ❌ 无 SN_API_KEY")
        return False
    data = json.dumps({
        "model": "sensenova-u1-fast",
        "prompt": prompt,
        "n": 1,
        "size": "1760x2368"
    }).encode()
    try:
        req = urllib.request.Request("https://token.sensenova.cn/v1/images/generations",
            data=data, headers={"Authorization": f"Bearer {SN_API_KEY}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            resp = json.loads(r.read())
        img_url = resp.get("data", [{}])[0].get("url", "")
        if img_url:
            urllib.request.urlretrieve(img_url, output)
            size = Path(output).stat().st_size
            if size > MIN_VALID_SIZE:
                print(f"[P1 SenseNova] ✅ {size}B")
                _compress(output)
                return True
        print(f"[P1 SenseNova] ❌ 无图片URL: {str(resp)[:100]}")
    except Exception as e:
        print(f"[P1 SenseNova] ❌ {e}")
    return False

def gen_replicate(prompt: str, output: str) -> bool:
    """P2: Replicate FLUX"""
    key = _get_replicate_key()
    if not key:
        print("[P2 Replicate] ❌ 无 API key")
        return False
    data = json.dumps({
        "input": {"prompt": prompt, "num_outputs": 1, "aspect_ratio": "1:1"}
    }).encode()
    try:
        req = urllib.request.Request(
            f"https://api.replicate.com/v1/models/{REPLICATE_MODEL}/predictions",
            data=data, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except Exception as e:
        print(f"[P2 Replicate] ❌ 提交失败: {e}")
        return False
    pred_id = resp.get("id")
    if not pred_id:
        print(f"[P2 Replicate] ❌ 无 task id")
        return False
    get_url = f"https://api.replicate.com/v1/predictions/{pred_id}"
    deadline = time.time() + 120
    last_status = ""
    while time.time() < deadline:
        time.sleep(3)
        try:
            req = urllib.request.Request(get_url, headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
        except Exception:
            continue
        status = resp.get("status", "")
        if status == last_status:
            continue
        last_status = status
        if status == "succeeded":
            img_url = resp.get("output")
            if isinstance(img_url, list):
                img_url = img_url[0] if img_url else None
            if img_url:
                try:
                    urllib.request.urlretrieve(img_url, output)
                    size = Path(output).stat().st_size
                    if size > MIN_VALID_SIZE:
                        print(f"[P2 Replicate] ✅ {size}B")
                        _compress(output)
                        return True
                except Exception as e:
                    print(f"[P2 Replicate] ❌ 下载失败: {e}")
                    return False
        elif status == "failed":
            err = resp.get("error") or resp.get("detail") or ""
            print(f"[P2 Replicate] ❌ {err[:100]}")
            return False
    print("[P2 Replicate] ⏰ 超时")
    return False

def gen_pollinations(prompt: str, output: str) -> bool:
    """P3: Pollinations.ai — 无限免key兜底"""
    url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1024&height=1024&nologo=true"
    try:
        urllib.request.urlretrieve(url, output)
        size = Path(output).stat().st_size
        if size > MIN_VALID_SIZE:
            print(f"[P3 Pollinations] ✅ {size}B")
            return True
    except Exception as e:
        print(f"[P3 Pollinations] ❌ {e}")
    return False

def main():
    parser = argparse.ArgumentParser(description="统一生图入口 — P0 CF→P1 SenseNova→P2 Replicate→P3 Pollinations")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", default="/tmp/gen_image.jpg")
    args = parser.parse_args()

    print(f"🎨 生图: {args.prompt[:80]}...")

    # 门禁1: prompt 质量检查
    r = subprocess.run(
        [sys.executable, "/root/.ai-self-media-tools/scripts/preflight_prompt.py",
         "--prompt", args.prompt, "--type", "image"],
        capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        print(f"❌ Prompt 未通过质量门禁:\n{r.stdout}{r.stderr}")
        sys.exit(1)

    # 四引擎级联
    ok = gen_cf(args.prompt, args.output) or \
         gen_sensenova(args.prompt, args.output) or \
         gen_replicate(args.prompt, args.output) or \
         gen_pollinations(args.prompt, args.output)

    if not ok:
        print("❌ 所有引擎都失败")
        sys.exit(1)

    # 门禁2: 视觉质量检查
    r = subprocess.run(
        [sys.executable, "/root/.ai-self-media-tools/scripts/visual_gate.py",
         "--image", args.output],
        capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        print(f"❌ 图片未通过视觉质量门禁:\n{r.stdout}{r.stderr}")
        sys.exit(1)
    sys.exit(0)


def pexels_search(query, output_path, count=1):
    """Search Pexels for real photos matching query. Returns list of saved paths."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        env_file = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools"))) / "secrets" / "channel_matrix.env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("PEXELS_API_KEY"):
                    api_key = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if not api_key:
        print("❌ PEXELS_API_KEY 未配置")
        return []

    encoded = urllib.parse.quote(query)
    url = f"https://api.pexels.com/v1/search?query={encoded}&per_page={count}"
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": "HermesImageGen/1.0"})

    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        print(f"❌ Pexels搜索失败: {e}")
        return []

    saved = []
    out_dir = Path(output_path).parent if str(output_path) != output_path else Path("/tmp")
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, photo in enumerate(resp.get("photos", [])[:count]):
        src = photo.get("src", {})
        img_url = src.get("medium") or src.get("original")
        if img_url:
            ext = "jpg"
            path = out_dir / f"pexels_{i}.{ext}"
            try:
                img_data = urllib.request.urlopen(urllib.request.Request(img_url, headers={"User-Agent": "HermesImageGen/1.0"}), timeout=15).read()
                path.write_bytes(img_data)
                if path.stat().st_size > 5000:
                    saved.append(str(path))
                    print(f"  ✅ Pexels[{i}]: {path.name} ({path.stat().st_size//1024}KB)")
            except Exception as e:
                print(f"  ⚠️ 下载失败[{i}]: {e}")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="统一生图 + Pexels 实图搜索")
    parser.add_argument("--prompt", help="AI生图提示词")
    parser.add_argument("--pexels", help="Pexels搜索关键词（实景图）")
    parser.add_argument("--output", default="/tmp/gen_image.jpg")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    if args.pexels:
        pexels_search(args.pexels, args.output, args.count)
    elif args.prompt:
        main()
    else:
        parser.print_help()
