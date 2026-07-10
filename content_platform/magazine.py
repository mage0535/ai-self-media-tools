"""
magazine.py — magazine-layout（104⭐）桥接模块。

将文本内容转换为精美杂志风格 HTML 页面，12 种视觉风格 + PDF 导出。
用于渠道推广中需要「独立文章页」的场景（Dev.to/博客园/Steemit/频道内容页等）。

依赖：
  - 技能安装于 ~/.hermes/skills/creative/magazine-layout/
  - 12 种风格定义于 references/styles.md（1235 行专业 CSS）
  - Playwright（已安装）for PDF 导出

集成方式：
    from .magazine import create_magazine
    result = create_magazine(markdown_text, style="现代极简")
    html = result["html"]
"""

import json, os, subprocess, sys, tempfile
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "magazine-layout"
STYLES_FILE = SKILL_DIR / "references" / "styles.md"
PDF_SCRIPT = SKILL_DIR / "scripts" / "html_to_pdf.py"

STYLES = {
    "经典优雅": "1",
    "现代极简": "2",
    "科技杂志": "3",
    "自然生活": "4",
    "大胆社论": "5",
    "复古怀旧": "6",
    "商务专业": "7",
    "创意艺术": "8",
    "学术期刊": "9",
    "时尚奢华": "10",
    "新闻报道": "11",
    "暗黑科技": "12",
}


def skill_available() -> bool:
    return SKILL_DIR.is_dir() and (SKILL_DIR / "SKILL.md").exists()


def list_styles() -> dict:
    """返回 {中文名: 编号} 风格列表"""
    return dict(STYLES)


def create_magazine(markdown: str, style="现代极简", title="",
                     output_path=None) -> dict:
    """
    将 Markdown 文本转换为杂志风格 HTML 页面。

    Args:
        markdown: 完整 Markdown 文本
        style: 视觉风格（见 list_styles()）
        title: 文章标题
        output_path: 可选指定输出路径

    Returns:
        {"ok": bool, "html": str, "style": str, "path": str}
    """
    if not skill_available():
        return {"ok": False, "error": "magazine-layout skill not installed"}

    # 匹配风格
    style_num = None
    for name, num in STYLES.items():
        if style in name or name in style:
            style_num = num
            break
    if not style_num:
        style_num = "2"  # 默认现代极简
        style = "现代极简"

    # 构建完整的 magazine HTML
    html = _build_magazine_html(markdown, title, style, style_num)

    # 写文件
    if output_path:
        out_dir = Path(output_path).parent
    else:
        out_dir = Path(tempfile.mkdtemp(prefix="magazine_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_title = "".join(c for c in (title or "article") if c.isalnum() or c in " _-")[:30]
    html_path = out_dir / f"{safe_title}_{style}.html"
    html_path.write_text(html, encoding="utf-8")

    return {"ok": True, "html": html, "style": style,
            "path": str(html_path)}


def export_pdf(html_path: str) -> dict:
    """将杂志 HTML 导出为 PDF（需要 Playwright）。"""
    if not PDF_SCRIPT.is_file():
        return {"ok": False, "error": "html_to_pdf.py not found"}
    try:
        r = subprocess.run(
            [sys.executable, str(PDF_SCRIPT), html_path],
            capture_output=True, text=True, timeout=60
        )
        pdf_path = str(Path(html_path).with_suffix(".pdf"))
        ok = r.returncode == 0 and Path(pdf_path).is_file()
        return {"ok": ok, "path": pdf_path if ok else None,
                "stdout": r.stdout, "stderr": r.stderr}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "PDF export timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _build_magazine_html(md: str, title: str, style_name: str, style_num: str) -> str:
    """生成一个完整的、自包含的杂志风格 HTML 页面。"""
    # 基础 Tailwind/样式
    lines = md.split("\n")
    body_parts = []

    # 解析内容
    for line in lines:
        s = line.strip()
        if s.startswith("# ") and not s.startswith("## "):
            body_parts.append(f'<h1>{s[2:]}</h1>')
        elif s.startswith("## "):
            body_parts.append(f'<h2>{s[3:]}</h2>')
        elif s.startswith("### "):
            body_parts.append(f'<h3>{s[4:]}</h3>')
        elif s.startswith("> "):
            body_parts.append(f'<blockquote><p>{s[2:]}</p></blockquote>')
        elif s.startswith("- ") or s.startswith("* "):
            body_parts.append(f'<li>{s[2:]}</li>')
        elif s == "---" or s == "***":
            body_parts.append('<hr class="divider">')
        elif s:
            body_parts.append(f'<p>{s}</p>')
        else:
            body_parts.append('<br>')

    body_html = "\n".join(body_parts)

    # 页面风格 CSS — 从 styles.md 提取核心风格变量
    # 这里使用内联的简化版（完整版需 LLM 读取 styles.md 后生成）
    palette = _style_palette(style_num)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title or "杂志"}</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:{palette['font']}; color:{palette['text']}; background:{palette['bg']}; }}
.container {{ max-width:800px; margin:0 auto; padding:40px 24px; }}
h1 {{ font-size:2.2em; font-weight:700; margin-bottom:0.3em; {palette['title_style']} }}
h2 {{ font-size:1.5em; font-weight:600; margin:2em 0 0.8em; padding-bottom:0.3em; border-bottom:2px solid {palette['accent']}; }}
h3 {{ font-size:1.2em; font-weight:500; margin:1.5em 0 0.5em; color:{palette['accent']}; }}
p {{ line-height:1.9; margin:1em 0; font-size:1.05em; }}
blockquote {{ margin:1.5em 0; padding:1em 1.5em; border-left:4px solid {palette['accent']}; background:{palette['quote_bg']}; border-radius:0 8px 8px 0; font-style:italic; }}
li {{ line-height:1.8; margin:0.5em 0 0.5em 1.5em; list-style-type:{palette['list_style']}; }}
hr.divider {{ margin:2.5em 0; border:none; height:1px; background:linear-gradient(90deg,transparent,{palette['accent']}44,transparent); }}
@media print {{ h1,h2,h3 {{ page-break-after:avoid; }} blockquote {{ page-break-inside:avoid; }} p {{ orphans:3; widows:3; }} }}
</style>
</head>
<body>
<div class="container">
<header style="text-align:center;margin-bottom:3em;">
  <div style="width:60px;height:3px;background:{palette['accent']};margin:0 auto 1em;"></div>
  {body_html.split('<h1>')[0] if '<h1>' in body_html else ''}
</header>
<article>
{body_html}
</article>
<footer style="margin-top:3em;padding-top:1em;border-top:1px solid #ddd;text-align:center;font-size:0.85em;color:#999;">
  <p>Generated with magazine-layout · {style_name} Style</p>
</footer>
</div>
</body>
</html>"""


def _style_palette(num: str) -> dict:
    palettes = {
        "1": {"font":"'Noto Serif SC',Georgia,serif","text":"#2D2D2D","bg":"#FDF8F0",
              "accent":"#C4552C","quote_bg":"#F8F0E8","title_style":"text-align:center;color:#C4552C;","list_style":"circle"},
        "2": {"font":"'Noto Sans SC','Helvetica Neue',sans-serif","text":"#333","bg":"#FFFFFF",
              "accent":"#2563EB","quote_bg":"#F8FAFC","title_style":"font-weight:300;letter-spacing:2px;","list_style":"disc"},
        "3": {"font":"'Noto Sans SC',sans-serif","text":"#1E293B","bg":"#0F172A",
              "accent":"#38BDF8","quote_bg":"#1E293B","title_style":"color:#38BDF8;font-weight:700;","list_style":"square"},
        "4": {"font":"'Noto Serif SC',Georgia,serif","text":"#3A4D39","bg":"#F7F9F7",
              "accent":"#4A7C59","quote_bg":"#EDF3ED","title_style":"color:#4A7C59;font-style:italic;","list_style":"circle"},
        "5": {"font":"'Noto Sans SC',sans-serif","text":"#1A1A1A","bg":"#FAFAFA",
              "accent":"#DC2626","quote_bg":"#FEF2F2","title_style":"font-size:3em;font-weight:900;text-transform:uppercase;","list_style":"disc"},
        "6": {"font":"'Noto Serif SC',Georgia,serif","text":"#4A3728","bg":"#F5EDE0",
              "accent":"#8B6914","quote_bg":"#EDE0CE","title_style":"font-family:'Playfair Display',serif;font-style:italic;","list_style":"circle"},
        "7": {"font":"'Noto Sans SC',sans-serif","text":"#1F2937","bg":"#FFFFFF",
              "accent":"#1E3A5F","quote_bg":"#F0F4F8","title_style":"color:#1E3A5F;font-weight:600;","list_style":"disc"},
        "8": {"font":"'Noto Sans SC',sans-serif","text":"#2D1B69","bg":"#F8F6FF",
              "accent":"#7C3AED","quote_bg":"#F3EEFF","title_style":"font-weight:800;letter-spacing:-1px;","list_style":"square"},
        "9": {"font":"'Noto Serif SC',Georgia,serif","text":"#1A1A1A","bg":"#FAFAFA",
              "accent":"#1E3A5F","quote_bg":"#F0F4F8","title_style":"text-align:center;font-weight:600;","list_style":"decimal"},
        "10":{"font":"'Noto Serif SC',Georgia,serif","text":"#2D1810","bg":"#FFFCF5",
              "accent":"#B8860B","quote_bg":"#FDF6E3","title_style":"font-weight:300;letter-spacing:3px;color:#B8860B;","list_style":"circle"},
        "11":{"font":"'Noto Sans SC',sans-serif","text":"#111","bg":"#FFFEFC",
              "accent":"#B91C1C","quote_bg":"#FEF2F2","title_style":"font-size:2.8em;font-weight:900;","list_style":"disc"},
        "12":{"font":"'JetBrains Mono','Noto Sans SC',monospace","text":"#E2E8F0","bg":"#0A0A0A",
              "accent":"#22D3EE","quote_bg":"#1A1A2E","title_style":"color:#22D3EE;font-weight:700;","list_style":"square"},
    }
    return palettes.get(num, palettes["2"])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Markdown -> 杂志 HTML")
    ap.add_argument("input", help="Markdown 文件或 -")
    ap.add_argument("--style", default="现代极简", choices=list(STYLES.keys()))
    ap.add_argument("--title", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--pdf", action="store_true", help="同时导出 PDF")
    args = ap.parse_args()

    md = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    r = create_magazine(md, style=args.style, title=args.title, output_path=args.output)
    if r["ok"]:
        print(f'✅ 杂志排版完成（{r["style"]}）')
        print(f'📄 HTML: {r["path"]}')
        if args.pdf:
            pdf_r = export_pdf(r["path"])
            print(f'📕 PDF: {"ok" if pdf_r["ok"] else "failed"}')
        if not args.output:
            print("\n--- HTML ---\n" + r["html"][:500] + "\n...")
    else:
        print(f'❌ {r.get("error","?")}')
        sys.exit(1)
