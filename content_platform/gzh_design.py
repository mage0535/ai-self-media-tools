"""
gzh_design.py — gzh-design-skill（1664⭐）桥接模块。

将 Markdown 内容转换为可直接粘贴到微信公众号编辑器的精美 HTML。
基于 isjiamu/gzh-design-skill 的 6 套主题 + 主题生成器 + 合规校验。

依赖：
  - 技能安装于 ~/.hermes/skills/creative/gzh-design-skill/
  - Python 3.10+（无额外依赖）

集成方式：
    from .gzh_design import format_for_wechat
    result = format_for_wechat(markdown_text, theme="摸鱼绿")
    html = result["html"]  # 可直接粘贴到公众号
"""

import json, os, subprocess, sys, tempfile, re
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "gzh-design-skill"
VALIDATE_SCRIPT = SKILL_DIR / "scripts" / "validate_gzh_html.py"
VALID_THEMES = ["摸鱼绿", "红白色系", "石墨极简风", "留白禅意风", "摸鱼票据风", "橄榄手记"]

# 主题主色表
THEME_COLORS = {
    "摸鱼绿":     {"p": "#059669", "l": "#D1FAE5", "t": "#065F46", "b": "#FFFFFF", "a": "#A7F3D0"},
    "红白色系":   {"p": "#DC2626", "l": "#FEE2E2", "t": "#991B1B", "b": "#FFFFFF", "a": "#FECACA"},
    "石墨极简风": {"p": "#52525B", "l": "#F4F4F5", "t": "#27272A", "b": "#FFFFFF", "a": "#D4D4D8"},
    "留白禅意风": {"p": "#4A5D52", "l": "#E8EDEA", "t": "#2D3A33", "b": "#F8F9F8", "a": "#B5C8BC"},
    "摸鱼票据风": {"p": "#059669", "l": "#D1FAE5", "t": "#065F46", "b": "#F9FAFB", "a": "#A7F3D0"},
    "橄榄手记":   {"p": "#ED7B2F", "l": "#FEF3C7", "t": "#1E1F23", "b": "#FFFFFF", "a": "#FDE68A"},
}


def skill_available() -> bool:
    return SKILL_DIR.is_dir() and (SKILL_DIR / "SKILL.md").exists()


def validate_html(html_path: str) -> dict:
    if not VALIDATE_SCRIPT.is_file():
        return {"ok": False, "error": "validate script not found"}
    try:
        r = subprocess.run([sys.executable, str(VALIDATE_SCRIPT), html_path],
                           capture_output=True, text=True, timeout=30)
        errs = [l for l in r.stdout.split("\n") if "ERROR" in l]
        warns = [l for l in r.stdout.split("\n") if "WARNING" in l]
        return {"ok": r.returncode == 0, "exit_code": r.returncode,
                "errors": errs, "warnings": warns, "stdout": r.stdout}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "validate timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def format_for_wechat(markdown: str, theme="摸鱼绿", title="",
                       output_path=None, auto_mode=False) -> dict:
    """将 Markdown 转为公众号可粘贴 HTML。"""
    if not skill_available():
        return {"ok": False, "error": "gzh-design-skill not installed"}

    # 主题匹配
    if theme not in VALID_THEMES:
        for t in VALID_THEMES:
            if theme in t or t in theme:
                theme = t; break
        else:
            theme = "摸鱼绿"

    colors = THEME_COLORS.get(theme, THEME_COLORS["摸鱼绿"])

    # 解析 Markdown → 内联 HTML
    html = _md_to_html(markdown, title, colors, theme)

    # 写文件
    if output_path:
        html_dir = Path(output_path).parent
    else:
        html_dir = Path(tempfile.mkdtemp(prefix="gzh_design_"))
    html_dir.mkdir(parents=True, exist_ok=True)

    safe_title = re.sub(r'[^\w\s-]', '', title)[:30] if title else "article"
    html_fn = f"{safe_title}_排版_{theme}.html"
    html_path = html_dir / html_fn
    html_path.write_text(html, encoding="utf-8")

    # 校验
    validation = validate_html(str(html_path))

    # 预览页
    preview_path = None
    ps = SKILL_DIR / "scripts" / "wrap_preview.py"
    if ps.is_file():
        try:
            subprocess.run([sys.executable, str(ps), str(html_path)],
                           capture_output=True, text=True, timeout=30)
            p = str(html_path).replace(".html", "_预览.html")
            if Path(p).is_file():
                preview_path = p
        except Exception:
            pass

    return {"ok": True, "html": html, "theme": theme,
            "html_path": str(html_path), "preview_path": preview_path,
            "validation": validation}


def _md_to_html(md: str, title: str, c: dict, theme: str) -> str:
    """将 Markdown 文本解析为公众号合规的内联样式 HTML。"""
    lines = md.split("\n")
    blocks = []
    buf = []

    def flush():
        if buf:
            blocks.append({"type": "p", "text": "\n".join(buf).strip()})
            buf.clear()

    chapter_num = 0
    total = sum(1 for l in lines if l.lstrip().startswith("## ") and not l.lstrip().startswith("### "))

    for raw in lines:
        s = raw.strip()
        if not s:
            flush(); continue
        if s.startswith("# ") and not s.startswith("## "):
            flush()
            blocks.append({"type": "title", "text": s[2:].strip()})
        elif s.startswith("## ") and not s.startswith("### "):
            flush()
            chapter_num += 1
            blocks.append({"type": "h2", "text": s[3:].strip(),
                           "num": f"{chapter_num:02d}",
                           "last": chapter_num == total})
        elif s.startswith("### "):
            flush()
            blocks.append({"type": "h3", "text": s[4:].strip()})
        elif s.startswith("> "):
            flush()
            blocks.append({"type": "quote", "text": s[2:].strip()})
        elif "![" in s and ")" in s:
            flush()
            for alt, url in re.findall(r'!\[(.*?)\]\((.*?)\)', s):
                blocks.append({"type": "img", "alt": alt, "url": url})
        elif s in ("---", "***", "___"):
            flush()
            blocks.append({"type": "hr"})
        elif s.startswith("- ") or s.startswith("* "):
            flush()
            blocks.append({"type": "li", "text": s[2:].strip()})
        elif re.match(r'^\d+[.．、]\s', s):
            flush()
            blocks.append({"type": "li", "text": re.sub(r'^\d+[.．、]\s', '', s)})
        else:
            buf.append(s)

    flush()

    # 构建 HTML
    parts = []
    c_text = c["t"]
    c_prim = c["p"]
    c_light = c["l"]
    c_bg = c["b"]

    # 全文容器
    parts.append(
        '<section style="max-width:600px;margin:0 auto;padding:10px 16px;'
        'font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,PingFang SC,Microsoft YaHei,sans-serif;'
        f'font-size:15px;line-height:1.8;color:{c_text};background:{c_bg};">'
    )

    for b in blocks:
        t = b["type"]
        if t == "title":
            parts.append(
                f'<section style="margin:30px 0 20px;text-align:center;">'
                f'<h2 style="font-size:22px;font-weight:700;margin:0;color:{c_text};'
                f'border-bottom:3px solid {c_prim};display:inline-block;padding-bottom:8px;">'
                f'<span leaf="">{_fmt(b["text"])}</span></h2></section>'
            )
        elif t == "h2":
            n = b["num"]
            parts.append(
                f'<section style="margin:35px 0 15px;padding:12px 0 8px;'
                f'border-bottom:1.5px solid {c_light};">'
                f'<h3 style="font-size:18px;font-weight:700;margin:0;color:{c_prim};">'
                f'<span leaf="">{n} {_fmt(b["text"])}</span></h3></section>'
            )
        elif t == "h3":
            parts.append(
                f'<section style="margin:20px 0 10px;padding-left:12px;'
                f'border-left:3px solid {c_prim};">'
                f'<h4 style="font-size:16px;font-weight:600;margin:0;color:{c_text};">'
                f'<span leaf="">{_fmt(b["text"])}</span></h4></section>'
            )
        elif t == "quote":
            parts.append(
                f'<section style="margin:20px 0;padding:16px 20px;border-radius:6px;'
                f'background:{c_light};border-left:4px solid {c_prim};">'
                f'<span leaf="" style="font-style:italic;color:{c_text};">'
                f'{_fmt(b["text"])}</span></section>'
            )
        elif t == "img":
            alt_attr = f' alt="{b["alt"]}"' if b["alt"] else ""
            alt_cap = f'<p style="color:#999;font-size:13px;margin:6px 0 0;"><span leaf="">{b["alt"]}</span></p>' if b["alt"] else ""
            parts.append(
                f'<section style="margin:20px 0;text-align:center;">'
                f'<img src="{b["url"]}"{alt_attr} '
                f'style="max-width:100%;height:auto;display:block;margin:0 auto;border-radius:6px;">'
                f'{alt_cap}</section>'
            )
        elif t == "hr":
            parts.append(
                f'<section style="margin:30px 0;text-align:center;">'
                f'<span leaf="" style="color:{c_light};">— · · · —</span></section>'
            )
        elif t == "li":
            parts.append(
                f'<p style="margin:6px 0;padding-left:18px;line-height:1.8;font-size:15px;color:{c_text};">'
                f'<span leaf="">• {_fmt(b["text"])}</span></p>'
            )
        elif t == "p":
            txt = b["text"]
            if txt:
                parts.append(
                    f'<p style="margin:12px 0;line-height:1.8;font-size:15px;color:{c_text};">'
                    f'<span leaf="">{_fmt(txt)}</span></p>'
                )

    # 作者签名
    parts.append(
        f'<section style="margin:40px 0 10px;padding:20px;border-radius:8px;'
        f'background:{c_light};text-align:center;font-size:14px;color:{c_text};">'
        f'<span leaf="">我是 <strong>{{作者名}}</strong>，{{一句话简介}}</span>'
        f'<br><span leaf="" style="color:#999;font-size:13px;">'
        f'如果觉得有收获，欢迎 <strong>点赞、在看、转发</strong> 三连</span>'
        f'</section>'
    )

    parts.append("</section>")
    return "\n".join(parts)


def _fmt(text: str) -> str:
    """Markdown 内联语法 → HTML + <span leaf> 包裹"""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`(.+?)`',
                  r'<code style="background:#F3F4F6;padding:2px 6px;border-radius:3px;font-size:14px;">\1</code>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)',
                  r'<a href="\2" style="color:#059669;text-decoration:underline;">\1</a>', text)
    text = re.sub(r'==(.+?)==', r'<mark style="background:#FDE68A;padding:0 4px;border-radius:2px;">\1</mark>', text)
    return text


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Markdown -> 公众号 HTML")
    ap.add_argument("input", help="Markdown 文件或 - (stdin)")
    ap.add_argument("--theme", default="摸鱼绿", choices=VALID_THEMES)
    ap.add_argument("--title", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--auto", action="store_true")
    args = ap.parse_args()

    md = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    r = format_for_wechat(md, theme=args.theme, title=args.title,
                          output_path=args.output, auto_mode=args.auto)
    if r["ok"]:
        print(f'✅ 排版完成 ({r["theme"]})')
        print(f'📄 HTML: {r["html_path"]}')
        if r.get("preview_path"):
            print(f'🔍 预览: {r["preview_path"]}')
        v = r["validation"]
        if v.get("ok"):
            print("✅ 合规校验通过")
        else:
            print(f'⚠️ 校验: {len(v.get("errors",[]))} ERROR, {len(v.get("warnings",[]))} WARNING')
        if not args.output:
            print("\n--- HTML ---\n" + r["html"])
    else:
        print(f'❌ {r.get("error", "?")}')
        sys.exit(1)
