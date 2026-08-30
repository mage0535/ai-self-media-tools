"""Hermes-backed WeChat Official Account draft adapter.

This script is called by content_platform.publishers.HermesWechatAdapter with a
validated JSON packet. It resolves Hermes tools via environment variables and
returns a JSON delivery result. It intentionally avoids hard-coded server paths.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        packet = json.loads(Path(args.input).read_text(encoding="utf-8"))
        result = publish_packet(packet, Path(args.input).parent)
    except Exception as exc:
        result = {"ok": False, "status": "failed", "error": str(exc)[:500]}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.get("ok") else 2


def publish_packet(packet: dict, work_dir: Path) -> dict:
    # 预检：运行 preflight_wechat.py
    preflight_script = Path(__file__).parent / "preflight_wechat.py"
    if preflight_script.exists():
        import subprocess
        r = subprocess.run([sys.executable, str(preflight_script)], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            err = r.stdout.split("\n")[-5:] if r.stdout else ["preflight check failed"]
            return {"ok": False, "status": "blocked", "error": " | ".join(err[-3:])}

    if not os.environ.get("CN_PROXY"):
        return {"ok": False, "status": "blocked", "error": "missing CN_PROXY"}
    license_result = _run_publish_license_gate(packet, Path(__file__).parent / "gzh_publish_license.py")
    if not license_result.get("passed"):
        failures = "; ".join(str(item) for item in license_result.get("failures", [])[:3])
        return {
            "ok": False,
            "status": "blocked",
            "error": f"WeChat publish license blocked: {failures}",
            "license": license_result,
        }
    scripts_dir = Path(os.environ.get("HERMES_SCRIPTS_DIR", ""))
    themes_dir = Path(os.environ.get("HERMES_WECHAT_THEMES_DIR", ""))
    if scripts_dir.is_dir():
        sys.path.insert(0, str(scripts_dir))
    try:
        import wechat_publisher as wx
    except Exception as exc:
        return {"ok": False, "status": "blocked", "error": f"wechat_publisher unavailable: {str(exc)[:200]}"}
    theme_files = list(themes_dir.glob("*.json")) if themes_dir.is_dir() else []
    if len(theme_files) < 109:
        return {"ok": False, "status": "blocked", "error": f"WeChat theme library incomplete: {len(theme_files)}/109"}
    token = wx.get_access_token()
    if not token:
        return {"ok": False, "status": "blocked", "error": "WeChat token unavailable"}
    title = str(packet.get("title", ""))[:64]
    theme = _select_theme(packet, theme_files)
    cover_path = _cover_path(packet)
    if not cover_path:
        cover_path = _generate_image(packet, work_dir, "cover")
    if not cover_path:
        return {"ok": False, "status": "failed", "error": "cover image unavailable"}
    cover_upload = wx.upload_image(token, str(cover_path))
    if isinstance(cover_upload, dict):
        thumb_id = cover_upload.get("media_id", "")
        cover_url = cover_upload.get("url", "")
    elif isinstance(cover_upload, tuple):
        cover_url, thumb_id = cover_upload[0], cover_upload[1]
    else:
        thumb_id, cover_url = "", ""
    if not thumb_id:
        return {"ok": False, "status": "failed", "error": "cover upload failed"}
    inline_urls = _upload_inline_images(packet, work_dir, token, wx)
    if len(inline_urls) < 3:
        return {"ok": False, "status": "failed", "error": f"inline image upload incomplete: {len(inline_urls)}/3"}
    try:
        md = _markdown_with_inline_images(packet, cover_url, inline_urls)
    except ValueError as exc:
        return {"ok": False, "status": "blocked", "error": str(exc)}
    html = wx.md_to_wechat(md, theme=theme)
    digest = _digest(packet)
    author = _author(packet)
    media_id = wx.publish_draft(token, title, html, author=author, digest=digest, thumb_media_id=thumb_id)
    if not media_id:
        return {"ok": False, "status": "failed", "error": "draft add returned no media_id"}
    postcheck = _batchget_confirm(token, media_id, title, expected_inline_images=len(inline_urls))
    evidence = {
        "theme": theme,
        "cover_uploaded": bool(thumb_id),
        "inline_image_count": len(inline_urls),
        "digest_present": bool(digest),
        "author": author,
        "postcheck": postcheck,
    }
    evidence_path = work_dir / "wechat_adapter_evidence.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": bool(postcheck.get("passed")),
        "status": "drafted" if postcheck.get("passed") else "handoff_pending",
        "media_id": media_id,
        "postcheck": postcheck,
        "evidence_path": str(evidence_path),
        "theme": theme,
    }


def _select_theme(packet: dict, theme_files: list[Path]) -> str:
    strategy = packet.get("strategy_brief") or {}
    selected = str(strategy.get("selected_theme") or "").strip()
    available = {path.stem for path in theme_files}
    if selected in available:
        return selected
    title_body = f"{packet.get('title','')} {packet.get('body','')}".casefold()
    if any(word in title_body for word in ["roi", "增长", "运营", "商业"]):
        return "sage-premium" if "sage-premium" in available else sorted(available)[0]
    if any(word in title_body for word in ["agent", "智能体", "pipeline", "自动化"]):
        return "business-navy" if "business-navy" in available else sorted(available)[0]
    return "refined-blue" if "refined-blue" in available else sorted(available)[0]


def _cover_path(packet: dict) -> Path | None:
    for item in packet.get("artifacts") or []:
        if item.get("kind") == "image":
            path = Path(str(item.get("path", "")))
            if path.is_file():
                return path
    cover = packet.get("cover_design") or {}
    path = Path(str(cover.get("path", "")))
    return path if path.is_file() else None


def _generate_image(packet: dict, work_dir: Path, role: str) -> Path | None:
    prompt = f"{packet.get('title','')} {role} {packet.get('cover_design',{}).get('visual_subject','')}".strip()
    output = work_dir / f"{role}.jpg"
    project_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    image_gen_script = project_home / "scripts" / "image_gen.py"
    if not image_gen_script.is_file():
        return None
    try:
        import subprocess, sys

        result = subprocess.run(
            [
                sys.executable, str(image_gen_script), "--prompt", prompt, "--output", str(output),
                "--intent", "cinematic_cover", "--semantic-required",
                "--expected-concept", str(packet.get("title") or ""),
                "--role", "cover", "--platform", "wechat",
            ],
            capture_output=True, text=True, timeout=180,
        )
    except Exception:
        return None
    return output if result.returncode == 0 and output.is_file() else None


def _upload_inline_images(packet: dict, work_dir: Path, token: str, wx) -> list[str]:
    urls: list[str] = []
    # Try to load section_image_map from artifacts path (pipeline-generated)
    mapping = packet.get("section_image_map") or []
    if not mapping:
        # Check artifacts path: job_id is in work_dir parent's parent
        artifacts_map = work_dir.parent / "section_image_map.json"
        if not artifacts_map.is_file():
            # Try job-level artifacts path
            job_id = packet.get("id", "")
            if job_id:
                project_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
                alt = project_home / "data" / "artifacts" / job_id / "section_image_map.json"
                if alt.is_file():
                    artifacts_map = alt
        if artifacts_map.is_file():
            try:
                mapping = json.loads(artifacts_map.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                mapping = []
    for idx, item in enumerate(mapping[:6], 1):
        path = Path(str(item.get("image", "")))
        if not path.is_file():
            path = _generate_section_image(packet, work_dir, item, idx)
        if not path or not path.is_file():
            continue
        uploaded = wx.upload_image(token, str(path))
        if isinstance(uploaded, dict):
            url_val = str(uploaded.get("url", ""))
        elif isinstance(uploaded, tuple):
            url_val = str(uploaded[0])
        else:
            url_val = ""
        if url_val:
            urls.append(url_val)
    return urls


def _generate_section_image(packet: dict, work_dir: Path, item: dict, idx: int) -> Path | None:
    # Priority 1: use pre-generated image from shot list
    img_path = item.get("image", "")
    if img_path and Path(str(img_path)).is_file():
        return Path(str(img_path))

    # Priority 2: use shot list prompt if available (from article-illustrator skill)
    prompt = item.get("prompt", "") or ""
    if not prompt:
        prompt = f"{packet.get('title','')} {item.get('section','')} {item.get('purpose','')}".strip()
    else:
        # Add style descriptor
        style = item.get("style", "")
        if style:
            style_descriptors = {
                "水墨": "Traditional Chinese ink wash painting style, artistic, minimalist, poetic",
                "像素": "Pixel art style, retro game aesthetic, 8-bit",
                "简笔画": "Clean minimal black line drawing on white background, sketch-like",
                "信息图": "Modern infographic style, clean data visualization, flat design",
            }
            desc = style_descriptors.get(style, "")
            if desc:
                prompt = f"{desc}. {prompt}"

    # Use the ai-self-media-tools pipeline (CF Worker → Replicate → Pollinations)
    project_home = Path(os.environ.get("CONTENT_PLATFORM_HOME", str(Path.home() / ".ai-self-media-tools")))
    image_gen_script = project_home / "scripts" / "image_gen.py"
    if image_gen_script.is_file():
        try:
            import subprocess, sys
            output = work_dir / f"inline_{idx}.jpg"
            r = subprocess.run(
                [
                    sys.executable, str(image_gen_script), "--prompt", prompt, "--output", str(output),
                    "--intent", "editorial_illustration", "--semantic-required",
                    "--expected-concept", str(item.get("section") or packet.get("title") or ""),
                    "--role", "section", "--platform", "wechat",
                ],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0 and output.is_file():
                return output
        except Exception:
            pass

    return None


def _generated_image_path(result, fallback: Path) -> Path | None:
    if isinstance(result, dict):
        value = result.get("output") or result.get("path") or str(fallback)
    else:
        value = str(fallback)
    if not value:
        return None
    return Path(str(value))


def _strip_redundant_title_heading(body: str, title: str) -> str:
    """Remove first line if it's a heading (# or ##) matching the article title.

    WeChat renders the title separately from the body content via its draft API.
    A heading in the body that duplicates the title appears as two identical
    titles stacked on top of each other — visually broken.
    """
    if not title.strip():
        return body
    title_lower = title.strip().casefold()
    lines = body.split("\n", 1)
    first = lines[0].strip() if lines else ""
    # Match # Title or ## Title
    m = re.match(r"^#{1,3}\s+(.+)$", first)
    if m:
        heading_text = m.group(1).strip().casefold()
        # Allow partial overlap: heading is a prefix of title, or title contains heading
        if heading_text in title_lower or title_lower in heading_text:
            return lines[1].strip() if len(lines) > 1 else ""
    return body


def _markdown_with_inline_images(packet: dict, cover_url: str, inline_urls: list[str]) -> str:
    body = str(packet.get("body", ""))
    title = str(packet.get("title", ""))
    body = _strip_redundant_title_heading(body, title)
    placeholders = list(re.finditer(r"!\[([^\]]*)\]\(\s*\)", body))
    if len(placeholders) > len(inline_urls):
        raise ValueError(
            f"unresolved inline image placeholders: {len(placeholders)} placeholders, {len(inline_urls)} uploaded"
        )

    def replace_placeholder(match: re.Match[str]) -> str:
        index = replace_placeholder.index
        replace_placeholder.index += 1
        alt = match.group(1)
        return f"![{alt}]({inline_urls[index]})"

    replace_placeholder.index = 0
    rendered = re.sub(r"!\[([^\]]*)\]\(\s*\)", replace_placeholder, body)
    if re.search(r"!\[[^\]]*\]\(\s*\)", rendered):
        raise ValueError("unresolved inline image placeholders after replacement")
    return f"![]({cover_url})\n\n{rendered}" if cover_url else rendered


def _digest(packet: dict) -> str:
    strategy = packet.get("strategy_brief") or {}
    payload = packet.get("platform_payload") or {}
    digest = strategy.get("seo_digest") or payload.get("summary") or packet.get("digest") or ""
    geo = strategy.get("geo_tag") or ""
    full = f"{digest} {geo}".strip()
    return full[:54]


def _author(packet: dict) -> str:
    strategy = packet.get("strategy_brief") or {}
    return str(strategy.get("geo_author") or strategy.get("author") or "Magic")[:32]


def _batchget_confirm(token: str, media_id: str, title: str, *, expected_inline_images: int = 0) -> dict:
    url = "https://api.weixin.qq.com/cgi-bin/draft/batchget?" + urllib.parse.urlencode({"access_token": token})
    data = json.dumps({"offset": 0, "count": 20, "no_content": 0}, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read())
    except Exception as exc:
        return {"passed": False, "error": str(exc)[:200]}
    for item in result.get("item", []) or []:
        if item.get("media_id") != media_id:
            continue
        content = item.get("content") or {}
        news = content.get("news_item") or []
        article = next((row for row in news if str(row.get("title", "")) == title), {})
        found_title = bool(article)
        content = str(article.get("content", ""))
        inline_image_count = len(
            re.findall(r"<img\b[^>]*\b(?:src|data-src)=[\"']https?://", content, flags=re.IGNORECASE)
        )
        inline_images_match = inline_image_count >= expected_inline_images
        return {
            "passed": found_title and inline_images_match,
            "media_id": media_id,
            "title_match": found_title,
            "inline_image_count": inline_image_count,
            "expected_inline_images": expected_inline_images,
            "inline_images_match": inline_images_match,
        }
    return {"passed": False, "media_id": media_id, "error": "media_id not found in draft batchget"}


def _run_publish_license_gate(packet: dict, license_script: Path) -> dict:
    title = str(packet.get("title", "")).strip()
    if not title:
        return {"version": "gzh_publish_license_v1", "passed": False, "failures": ["title_missing"]}
    if not license_script.is_file():
        return {
            "version": "gzh_publish_license_v1",
            "title": title,
            "passed": False,
            "failures": ["license_script_missing"],
        }
    try:
        cmd = [sys.executable, str(license_script), "--title", title]
        direction = _content_direction(packet)
        if direction:
            cmd.extend(["--direction", direction])
        content_home = str(os.environ.get("CONTENT_PLATFORM_HOME") or "").strip()
        if content_home:
            cmd.extend(["--root", content_home])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return {
            "version": "gzh_publish_license_v1",
            "title": title,
            "passed": False,
            "failures": [f"license_script_error:{str(exc)[:160]}"],
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "version": "gzh_publish_license_v1",
            "title": title,
            "passed": False,
            "failures": [f"license_output_invalid:returncode={result.returncode}"],
            "stderr": result.stderr[-500:],
        }
    if not isinstance(payload, dict):
        return {
            "version": "gzh_publish_license_v1",
            "title": title,
            "passed": False,
            "failures": ["license_output_not_object"],
        }
    if result.returncode != 0 and payload.get("passed") is not False:
        payload["passed"] = False
        payload.setdefault("failures", []).append(f"license_returncode_nonzero:{result.returncode}")
    return payload


def _content_direction(packet: dict) -> str:
    for source in (packet.get("strategy_brief"), packet.get("draft_meta"), packet.get("platform_payload"), packet):
        if not isinstance(source, dict):
            continue
        for key in ("content_direction", "topic_direction", "direction", "content_line"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
