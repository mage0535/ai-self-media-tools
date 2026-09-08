"""Deterministic editorial visuals for abstract knowledge content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int, *, bold: bool = False):
    candidates = (
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _rgb(value: str) -> tuple[int, int, int]:
    clean = str(value or "#1E80FF").lstrip("#")
    try:
        return tuple(int(clean[index:index + 2], 16) for index in (0, 2, 4))
    except (TypeError, ValueError):
        return 30, 128, 255


def _panel(draw, box, *, fill=(17, 30, 49), outline=(81, 115, 151), radius=28, width=3):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _arrow(draw, start, end, accent, width):
    draw.line((*start, *end), fill=accent, width=width)
    ex, ey = end
    draw.polygon(((ex, ey), (ex - width * 3, ey - width * 2), (ex - width * 3, ey + width * 2)), fill=accent)


def _workflow(draw, width, height, accent):
    margin = int(width * 0.08)
    top = int(height * 0.24)
    card_w = int(width * 0.22)
    card_h = int(height * 0.38)
    gap = int(width * 0.075)
    labels = (("INPUT", "01"), ("SKILL", "02"), ("VERIFY", "03"))
    for index, (label, number) in enumerate(labels):
        x = margin + index * (card_w + gap)
        _panel(draw, (x, top, x + card_w, top + card_h))
        draw.rounded_rectangle((x + 24, top + 24, x + 86, top + 86), radius=16, fill=accent)
        draw.text((x + 42, top + 35), number, font=_font(23, bold=True), fill=(5, 15, 28))
        draw.text((x + 24, top + 120), label, font=_font(32, bold=True), fill=(238, 245, 252))
        for row in range(3):
            y = top + 185 + row * 42
            draw.ellipse((x + 26, y, x + 42, y + 16), fill=accent if row < 2 else (95, 122, 151))
            draw.rounded_rectangle((x + 58, y + 2, x + card_w - 25 - row * 14, y + 14), radius=6, fill=(118, 143, 169))
        if index < 2:
            _arrow(draw, (x + card_w + 12, top + card_h // 2), (x + card_w + gap - 16, top + card_h // 2), accent, 7)
    binder = (margin, int(height * 0.70), width - margin, int(height * 0.86))
    _panel(draw, binder, fill=(11, 22, 38), outline=accent, radius=22, width=3)
    draw.text((binder[0] + 30, binder[1] + 26), "MODULAR PLAYBOOK", font=_font(28, bold=True), fill=(238, 245, 252))
    draw.text((binder[2] - 175, binder[1] + 27), "PASS", font=_font(26, bold=True), fill=accent)


def _module_comparison(draw, width, height, accent):
    margin = int(width * 0.07)
    top = int(height * 0.17)
    gap = int(width * 0.05)
    panel_w = int((width - margin * 2 - gap) / 2)
    for index, label in enumerate(("CommonJS", "ESM")):
        x = margin + index * (panel_w + gap)
        _panel(draw, (x, top, x + panel_w, int(height * 0.83)), outline=accent if index else (131, 100, 111))
        draw.text((x + 28, top + 26), label, font=_font(34, bold=True), fill=(238, 245, 252))
        code = ("require()", "module.exports", "runtime load") if index == 0 else ("import", "export", "static graph")
        for row, text in enumerate(code):
            y = top + 115 + row * 92
            draw.rounded_rectangle((x + 28, y, x + panel_w - 28, y + 58), radius=12, fill=(8, 18, 31))
            draw.text((x + 48, y + 14), text, font=_font(25), fill=accent if index else (224, 152, 167))
    center = width // 2
    draw.ellipse((center - 39, height // 2 - 39, center + 39, height // 2 + 39), fill=accent)
    draw.text((center - 20, height // 2 - 25), "≠", font=_font(38, bold=True), fill=(4, 14, 27))


def _memory_archive(draw, width, height, accent):
    margin = int(width * 0.10)
    top = int(height * 0.18)
    _panel(draw, (margin, top, width - margin, int(height * 0.84)), outline=accent)
    draw.text((margin + 35, top + 28), "CONTEXT ARCHIVE", font=_font(34, bold=True), fill=(238, 245, 252))
    for row, label in enumerate(("IDENTITY", "RULES", "HISTORY", "NEXT ACTION")):
        y = top + 105 + row * int(height * 0.12)
        draw.rounded_rectangle((margin + 36, y, width - margin - 36, y + 62), radius=13, fill=(8, 18, 31), outline=(64, 91, 119), width=2)
        draw.rounded_rectangle((margin + 55, y + 17, margin + 83, y + 45), radius=7, fill=accent)
        draw.text((margin + 108, y + 13), label, font=_font(26, bold=True), fill=(225, 235, 246))
        draw.text((width - margin - 145, y + 15), "SAVED", font=_font(22), fill=accent)


def _dashboard(draw, width, height, accent):
    margin = int(width * 0.08)
    _panel(draw, (margin, int(height * 0.16), width - margin, int(height * 0.84)), outline=accent)
    for row in range(3):
        y = int(height * 0.27) + row * int(height * 0.16)
        draw.ellipse((margin + 42, y, margin + 78, y + 36), fill=accent)
        draw.rounded_rectangle((margin + 110, y + 2, width - margin - 48, y + 34), radius=12, fill=(91, 121, 151))
        if row < 2:
            _arrow(draw, (width // 2, y + 52), (width // 2, y + int(height * 0.13)), accent, 5)


def _tool_tab_overload(draw, width, height, accent, language):
    margin = int(width * 0.07)
    gap = int(width * 0.04)
    panel_w = int((width - margin * 2 - gap) / 2)
    top, bottom = int(height * 0.15), int(height * 0.85)
    _panel(draw, (margin, top, margin + panel_w, bottom), outline=accent)
    _panel(draw, (margin + panel_w + gap, top, width - margin, bottom), outline=(232, 95, 66))
    labels = ["8个工具标签", "任务清单", "待处理", "未完成", "未开始"] if language == "zh" else ["8 TOOL TABS", "TASK LIST", "PENDING", "UNFINISHED", "NOT STARTED"]
    draw.text((margin + 30, top + 28), labels[0], font=_font(32, bold=True), fill=(238, 245, 252))
    for row in range(4):
        y = top + 105 + row * 78
        draw.rounded_rectangle((margin + 30, y, margin + panel_w - 30, y + 48), radius=12, fill=(8, 18, 31), outline=accent, width=2)
        tool = "工具" if language == "zh" else "TOOL"
        draw.text((margin + 50, y + 10), f"{tool} {row * 2 + 1}   {tool} {row * 2 + 2}", font=_font(22), fill=(195, 215, 235))
    right = margin + panel_w + gap
    draw.text((right + 30, top + 28), labels[1], font=_font(32, bold=True), fill=(238, 245, 252))
    for row, label in enumerate(labels[2:]):
        y = top + 125 + row * 105
        draw.rectangle((right + 35, y, right + 70, y + 35), outline=(232, 95, 66), width=4)
        draw.text((right + 95, y), label, font=_font(25, bold=True), fill=(232, 152, 132))
    return labels


def _goal_input_output(draw, width, height, accent, language):
    margin = int(width * 0.08)
    labels = (("目标", "明确结果"), ("输入", "核对材料"), ("输出", "设定验收")) if language == "zh" else (("GOAL", "DEFINE RESULT"), ("INPUT", "CHECK MATERIAL"), ("OUTPUT", "SET ACCEPTANCE"))
    top = int(height * 0.17)
    card_h = int(height * 0.18)
    for index, (label, detail) in enumerate(labels):
        y = top + index * int(height * 0.22)
        _panel(draw, (margin, y, width - margin, y + card_h), fill=(9, 22, 39), outline=accent, radius=22, width=3)
        draw.rounded_rectangle((margin + 28, y + 28, margin + 190, y + card_h - 28), radius=15, fill=accent)
        draw.text((margin + 52, y + 43), label, font=_font(29, bold=True), fill=(5, 15, 28))
        draw.text((margin + 235, y + 44), detail, font=_font(27, bold=True), fill=(231, 239, 248))
    return [value for pair in labels for value in pair]


def _four_panel_boundary(draw, width, height, accent, language):
    margin = int(width * 0.07)
    gap = int(width * 0.035)
    top = int(height * 0.14)
    panel_w = int((width - margin * 2 - gap) / 2)
    panel_h = int((height - top - int(height * 0.12) - gap) / 2)
    labels = (("目标", "明确吗？"), ("输入", "齐全吗？"), ("验收", "可检查吗？"), ("卡点", "明确吗？")) if language == "zh" else (("GOAL", "CLEAR?"), ("INPUT", "READY?"), ("ACCEPT", "TESTABLE?"), ("BLOCKER", "KNOWN?"))
    for index, (label, question) in enumerate(labels):
        row, column = divmod(index, 2)
        x = margin + column * (panel_w + gap)
        y = top + row * (panel_h + gap)
        _panel(draw, (x, y, x + panel_w, y + panel_h), fill=(9, 22, 39), outline=accent if index < 3 else (232, 95, 66), radius=22, width=3)
        draw.rectangle((x + 30, y + 32, x + 68, y + 70), outline=accent, width=4)
        draw.text((x + 94, y + 28), label, font=_font(30, bold=True), fill=(238, 245, 252))
        draw.text((x + 94, y + 92), question, font=_font(24, bold=True), fill=accent)
    return [value for pair in labels for value in pair]


def _document_anatomy(draw, width, height, accent):
    margin = int(width * 0.12)
    top = int(height * 0.14)
    _panel(draw, (margin, top, width - margin, int(height * 0.86)), outline=accent)
    draw.text((margin + 38, top + 30), "SKILL.md", font=_font(38, bold=True), fill=(238, 245, 252))
    sections = (("YAML FRONTMATTER", accent), ("MARKDOWN INSTRUCTIONS", (118, 143, 169)))
    for index, (label, color) in enumerate(sections):
        y = top + 120 + index * int(height * 0.25)
        draw.rounded_rectangle((margin + 38, y, width - margin - 38, y + int(height * 0.18)), radius=18, fill=(8, 18, 31), outline=color, width=3)
        draw.text((margin + 68, y + 24), label, font=_font(27, bold=True), fill=color)
        for row in range(2):
            line_y = y + 78 + row * 28
            draw.rounded_rectangle((margin + 68, line_y, width - margin - 90 - row * 80, line_y + 12), radius=6, fill=(102, 128, 155))


def _resource_stack(draw, width, height, accent):
    labels = ("SCRIPTS", "REFERENCES", "ASSETS")
    margin = int(width * 0.09)
    top = int(height * 0.20)
    card_h = int(height * 0.17)
    for index, label in enumerate(labels):
        x = margin + index * int(width * 0.29)
        y = top + index * int(height * 0.12)
        _panel(draw, (x, y, x + int(width * 0.28), y + card_h), fill=(9, 22, 39), outline=accent, radius=22, width=3)
        draw.rounded_rectangle((x + 24, y + 24, x + 72, y + 72), radius=10, fill=accent)
        draw.text((x + 92, y + 29), label, font=_font(24, bold=True), fill=(235, 243, 251))
    _arrow(draw, (margin + int(width * 0.14), int(height * 0.70)), (width - margin - int(width * 0.08), int(height * 0.70)), accent, 7)
    draw.text((margin, int(height * 0.75)), "LOAD ONLY WHEN NEEDED", font=_font(27, bold=True), fill=accent)


def _selective_loading_sequence(draw, width, height, accent):
    margin = int(width * 0.08)
    center_y = height // 2
    main = (margin, int(height * 0.24), int(width * 0.38), int(height * 0.76))
    _panel(draw, main, fill=(10, 24, 42), outline=accent, radius=28, width=4)
    draw.text((main[0] + 34, main[1] + 34), "SKILL.md", font=_font(36, bold=True), fill=(238, 245, 252))
    for row in range(4):
        y = main[1] + 120 + row * 54
        draw.rounded_rectangle((main[0] + 36, y, main[2] - 36 - row * 18, y + 16), radius=7, fill=(105, 132, 160))
    _arrow(draw, (main[2] + 28, center_y), (int(width * 0.57), center_y), accent, 8)
    draw.text((int(width * 0.405), center_y - 62), "ON DEMAND", font=_font(23, bold=True), fill=accent)
    labels = ("SCRIPT", "REFERENCE", "ASSET")
    for index, label in enumerate(labels):
        y = int(height * 0.18) + index * int(height * 0.23)
        box = (int(width * 0.59), y, width - margin, y + int(height * 0.16))
        _panel(draw, box, fill=(8, 20, 35), outline=(80, 113, 146), radius=20, width=3)
        draw.rounded_rectangle((box[0] + 24, box[1] + 25, box[0] + 68, box[1] + 69), radius=10, fill=accent)
        draw.text((box[0] + 94, box[1] + 28), label, font=_font(26, bold=True), fill=(226, 237, 248))


def _agent_orchestrator(draw, width, height, accent):
    center_x, center_y = width // 2, height // 2
    center = (center_x - 190, center_y - 105, center_x + 190, center_y + 105)
    _panel(draw, center, fill=(13, 30, 52), outline=accent, radius=34, width=4)
    draw.text((center_x - 100, center_y - 46), "AI AGENT", font=_font(40, bold=True), fill=(238, 245, 252))
    draw.text((center_x - 124, center_y + 18), "PLAN  ACT  VERIFY", font=_font(22, bold=True), fill=accent)
    nodes = (
        ("INPUT", (80, center_y - 60, 300, center_y + 60)),
        ("OUTPUT", (width - 300, center_y - 60, width - 80, center_y + 60)),
        ("TOOLS", (center_x - 120, 70, center_x + 120, 170)),
        ("MEMORY", (center_x - 120, height - 170, center_x + 120, height - 70)),
    )
    for label, box in nodes:
        _panel(draw, box, fill=(8, 20, 35), outline=(80, 113, 146), radius=20, width=3)
        bbox = draw.textbbox((0, 0), label, font=_font(26, bold=True))
        draw.text(
            ((box[0] + box[2] - (bbox[2] - bbox[0])) / 2, (box[1] + box[3] - (bbox[3] - bbox[1])) / 2 - bbox[1]),
            label,
            font=_font(26, bold=True),
            fill=(226, 237, 248),
        )
    _arrow(draw, (300, center_y), (center[0] - 18, center_y), accent, 7)
    _arrow(draw, (center[2] + 18, center_y), (width - 300, center_y), accent, 7)
    draw.line((center_x, 170, center_x, center[1] - 16), fill=accent, width=6)
    draw.line((center_x, center[3] + 16, center_x, height - 170), fill=accent, width=6)


def render_editorial_visual(
    output: str | Path,
    *,
    role: str,
    size: tuple[int, int],
    title: str,
    subtitle: str,
    concepts: list[str],
    accent: str = "#1E80FF",
) -> dict[str, Any]:
    target = Path(output)
    width, height = int(size[0]), int(size[1])
    accent_rgb = _rgb(accent)
    image = Image.new("RGB", (width, height), (5, 13, 24))
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((-width // 5, -height // 3, width // 2, height // 2), fill=(*accent_rgb, 115))
    glow_draw.ellipse((width * 2 // 3, height // 2, width * 6 // 5, height * 7 // 6), fill=(232, 95, 66, 70))
    image = Image.alpha_composite(image.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(max(30, width // 18)))).convert("RGB")
    draw = ImageDraw.Draw(image)
    for x in range(0, width, max(28, width // 32)):
        draw.line((x, 0, x, height), fill=(10, 24, 41), width=1)
    for y in range(0, height, max(28, height // 24)):
        draw.line((0, y, width, y), fill=(10, 24, 41), width=1)

    joined = " ".join(str(item).casefold() for item in concepts)
    semantic_text = " ".join((str(title), str(subtitle), joined)).casefold()
    language = "zh" if any("\u4e00" <= char <= "\u9fff" for char in f"{title}{subtitle}") else "en"
    visible_labels = []
    if "multiple software tool tabs and unfinished task list" in semantic_text:
        layout = "tool_tab_overload"
        visible_labels = _tool_tab_overload(draw, width, height, accent_rgb, language)
    elif "goal input output checklist card" in semantic_text:
        layout = "goal_input_output_card"
        visible_labels = _goal_input_output(draw, width, height, accent_rgb, language)
    elif "four-panel task boundary checklist" in semantic_text:
        layout = "four_panel_boundary_check"
        visible_labels = _four_panel_boundary(draw, width, height, accent_rgb, language)
    elif any(token in semantic_text for token in ("skill.md", "frontmatter", "yaml", "markdown")):
        layout = "document_anatomy"
        _document_anatomy(draw, width, height, accent_rgb)
    elif "selective document loading sequence" in semantic_text:
        layout = "selective_loading_sequence"
        _selective_loading_sequence(draw, width, height, accent_rgb)
    elif any(token in semantic_text for token in (
        "scripts", "references", "assets", "资源目录",
        "structured skill directory documents",
    )):
        layout = "resource_stack"
        _resource_stack(draw, width, height, accent_rgb)
    elif "ai software agent" in joined:
        layout = "ai_agent_orchestrator"
        _agent_orchestrator(draw, width, height, accent_rgb)
    elif "module format comparison" in joined:
        layout = "module_comparison"
        _module_comparison(draw, width, height, accent_rgb)
    elif "memory archive" in joined:
        layout = "memory_archive"
        _memory_archive(draw, width, height, accent_rgb)
    elif "workflow" in joined or "playbook" in joined:
        layout = "workflow_playbook"
        _workflow(draw, width, height, accent_rgb)
    else:
        layout = "verification_dashboard"
        _dashboard(draw, width, height, accent_rgb)

    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", optimize=False)
    payload = {
        "role": str(role),
        "size": [width, height],
        "title": str(title),
        "subtitle": str(subtitle),
        "concepts": list(concepts),
        "layout": layout,
        "language": language,
        "visible_labels": visible_labels,
        "accent": str(accent),
    }
    prompt_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    output_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "provider": "cover_renderer" if str(role).casefold() == "cover" else "knowledge_card_renderer",
        "model": "deterministic_editorial_v1",
        "source_url": "generated:deterministic_editorial",
        "license": "generated_for_project",
        "prompt_hash": prompt_hash,
        "output_sha256": output_sha,
        "semantic_concepts": list(concepts),
        "layout": layout,
        "language": language,
        "visible_labels": visible_labels,
    }


__all__ = ["render_editorial_visual"]
