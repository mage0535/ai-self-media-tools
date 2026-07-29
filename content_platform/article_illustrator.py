"""
article_illustrator.py — 基于认知锚点方法论的文章配图引擎。

改编自 ian-xiaohei-illustrations 的工作流：
  消化全文 → 锁定认知锚点 → 输出 shot list → 逐张生图 → QA → 嵌入文章

集成到 ai-self-media-tools 管线：
  - Pipeline.run() 自动触发 (media.illustration.enabled=true)
  - 输出 section_image_map 供 hermes_wechat_adapter.py 使用
  - 4 种风格：传统水墨 / 像素风 / 简笔画 / 信息图
"""

import json
import os
import re
import subprocess
import sys
import hashlib
from pathlib import Path
from typing import Optional

# ── 认知锚点类型 ──────────────────────────────────────────────
ANCHOR_TYPES = {
    "核心判断": {"keywords": ["本质", "关键", "核心", "一句话", "结论", "不是", "而是"],
                 "desc": "一句话定义/结论"},
    "两个断点": {"keywords": ["之前", "之后", "从", "到", "转型", "升级", "进化"],
                 "desc": "从 A 到 B 的转折"},
    "输入输出闭环": {"keywords": ["输入", "输出", "得到", "产出", "结果", "反馈"],
                   "desc": "做什么→得到什么"},
    "前后对比": {"keywords": ["对比", "vs", "区别", "before", "after", "传统", "现代"],
                "desc": "A vs B, 前后对比"},
    "一鱼多吃": {"keywords": ["多种用途", "复用", "多平台", "一次", "多处"],
                "desc": "同一资源多种用途"},
    "常见坑": {"keywords": ["坑", "陷阱", "误区", "注意", "不要", "避免", "90%"],
               "desc": "失败模式/常见错误"},
    "概念隐喻": {"keywords": ["就像", "好比", "像", "仿佛", "隐喻", "如"],
                "desc": "抽象概念变物理隐喻"},
    "方法分层": {"keywords": ["步骤", "层次", "阶段", "框架", "三层", "五步", "流程"],
                "desc": "架构/框架/方法"},
}

STYLE_DESCRIPTORS = {
    "水墨": "Traditional Chinese ink wash painting style, bold brushstrokes, watercolor texture on rice paper, artistic, poetic, minimalist, monochrome with subtle color accents",
    "像素": "Pixel art style, retro 8-bit game aesthetic, blocky pixelated graphics, nostalgic, chunky pixels, limited color palette",
    "简笔画": "Clean minimal line drawing style, black hand-drawn outlines on pure white background, sparse, elegant, sketch-like, single-weight lines",
    "信息图": "Modern infographic style, clean data visualization, structured layout, flat design elements, professional, clear visual hierarchy, icons and charts",
}

STYLE_KEYWORDS = {
    "水墨": ["文化", "哲学", "文学", "艺术", "传统", "软性", "思考", "人文"],
    # 像素风：仅限游戏/复古/娱乐主题，禁止自动分配给科技/AI/工具类内容
    "像素": ["游戏", "复古", "像素", "红白机", "街机", "任天堂", "怀旧游戏"],
    "简笔画": ["通用", "教程", "步骤", "方法", "概念", "解释"],
    "信息图": ["数据", "流程", "对比", "架构", "框架", "报告", "分析", "统计", "科技", "AI", "工具", "效率", "编程", "代码", "算法", "自动化"],
}

# 公众号配图风格强制规则：科技/AI/效率类文章禁止使用像素风
# 默认使用信息图或简笔画
FORCE_BAN_STYLES = {"像素"}
FORCE_DEFAULT_STYLES = ["信息图", "简笔画"]

IMAGE_GEN = Path("/root/.ai-self-media-tools/scripts/image_gen.py")


def _detect_style(text: str) -> str:
    """Auto-detect best illustration style based on content keywords.

    公众号配图强制规则：
    - 禁止像素风（仅限游戏/复古内容）
    - 科技/AI/效率类默认使用信息图或简笔画
    """
    text_lower = text.lower()
    scores = {}
    for style, keywords in STYLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[style] = score
    if scores:
        best = max(scores, key=lambda k: scores[k])
        # 强制规则：禁止像素风（除非内容明确是游戏/复古主题）
        if best in FORCE_BAN_STYLES:
            # 检查是否有足够证据支持像素风
            game_score = sum(1 for kw in STYLE_KEYWORDS["像素"] if kw in text_lower)
            if game_score < 3:  # 少于3个游戏关键词 → 降级到信息图
                return FORCE_DEFAULT_STYLES[0]
        return best
    return FORCE_DEFAULT_STYLES[0]  # 默认信息图


def _detect_anchors(text: str) -> list[dict]:
    """Scan article text and identify cognitive anchor points for illustration."""
    anchors = []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 50]

    for idx, para in enumerate(paragraphs):
        # Score each paragraph against anchor types
        para_lower = para.lower()
        best_type = None
        best_score = 0

        for atype, info in ANCHOR_TYPES.items():
            score = sum(1 for kw in info["keywords"] if kw in para_lower)
            if score > best_score:
                best_score = score
                best_type = atype

        if best_type and best_score >= 2:
            # Extract first 30 chars for section reference
            section_key = para[:40].strip()
            anchors.append({
                "section": section_key,
                "para_index": idx,
                "anchor_type": best_type,
                "reason": ANCHOR_TYPES[best_type]["desc"],
                "style": _detect_style(para),
            })

    # Deduplicate: if adjacent paragraphs have same type, keep only first
    if len(anchors) > 1:
        deduped = [anchors[0]]
        for a in anchors[1:]:
            if a["anchor_type"] != deduped[-1]["anchor_type"]:
                deduped.append(a)
        anchors = deduped

    # Limit to 4-8 shots
    if len(anchors) > 8:
        # Keep score-weighted top 8
        anchors = anchors[:8]
    elif len(anchors) < 4 and len(paragraphs) >= 4:
        # Pad with generic anchors on important-looking paragraphs
        existing_types = {a["anchor_type"] for a in anchors}
        fallbacks = ["核心判断", "概念隐喻", "前后对比", "方法分层"]
        for fb in fallbacks:
            if fb not in existing_types and len(anchors) < 4:
                anchors.append({
                    "section": paragraphs[len(anchors)][:40].strip(),
                    "para_index": min(len(anchors), len(paragraphs) - 1),
                    "anchor_type": fb,
                    "reason": ANCHOR_TYPES[fb]["desc"],
                    "style": _detect_style(paragraphs[min(len(anchors), len(paragraphs) - 1)]),
                })

    return anchors


def _generate_topic(anchor: dict, title: str) -> str:
    """Generate a concise illustration topic from anchor data."""
    atype = anchor["anchor_type"]
    section = anchor["section"][:20]

    topic_map = {
        "核心判断": f"核心判断: {section}",
        "两个断点": f"转折点: {section}",
        "输入输出闭环": f"闭环: {section}",
        "前后对比": f"对比: {section}",
        "一鱼多吃": f"复用: {section}",
        "常见坑": f"避坑: {section}",
        "概念隐喻": f"隐喻: {section}",
        "方法分层": f"框架: {section}",
    }
    return topic_map.get(atype, f"配图: {section}")


def _build_prompt(anchor: dict, title: str, idx: int) -> str:
    """Build a 5-element image generation prompt for a shot."""
    style = anchor.get("style", "简笔画")
    style_desc = STYLE_DESCRIPTORS.get(style, STYLE_DESCRIPTORS["简笔画"])
    topic = _generate_topic(anchor, title)
    atype = anchor["anchor_type"]
    section = anchor["section"]
    reason = anchor["reason"]

    composition_templates = {
        "核心判断": f"A central bold statement with visual emphasis, surrounded by clarifying elements, clean composition highlighting the key judgment",
        "两个断点": f"Split composition showing before/after or transition, arrow or bridge connecting two states, clear directional flow",
        "输入输出闭环": f"Input on left side, processing in middle, output on right, feedback loop arrow connecting output back to input",
        "前后对比": f"Left-right split panel, left side old/worse state, right side new/better state, clear dividing line or arrow in middle",
        "一鱼多吃": f"Central source splitting into multiple outputs, hub-and-spoke composition, each output has unique label",
        "常见坑": f"Warning sign or obstacle in center, figure approaching or falling into trap, red accent for danger/highlight",
        "概念隐喻": f"Creative metaphor visualization turning abstract concept into physical object/scene, surreal but clear",
        "方法分层": f"Stacked layers or steps from bottom to top, each layer labeled, progressive building composition",
    }
    comp = composition_templates.get(atype, "Clean minimalist composition, clear focal point, good use of negative space")

    return (
        f"{style_desc}. "
        f"16:9 horizontal Chinese article illustration. "
        f"标题: {title}. "
        f"主题: {topic}. "
        f"核心意思: {section[:80]}. "
        f"结构: {reason}. "
        f"构图: {comp}. "
        f"Clean professional composition, high quality detail, suitable for WeChat official account article."
    )


def analyze_article(title: str, body: str, max_shots: int = 6) -> dict:
    """Full article analysis → shot list generation.

    Returns:
        dict with "shots" (list) and "section_image_map" (list)
    """
    text = f"{title}\n\n{body}"
    anchors = _detect_anchors(text)

    # Convert anchors to shot list
    shots = []
    for idx, anchor in enumerate(anchors[:max_shots]):
        style = anchor["style"]
        shot = {
            "id": f"shot_{idx + 1:02d}",
            "after_section": anchor["section"],
            "topic": _generate_topic(anchor, title),
            "core_idea": anchor["reason"],
            "structure_type": anchor["anchor_type"],
            "style": style,
            "prompt": _build_prompt(anchor, title, idx),
            "status": "pending",
        }
        shots.append(shot)

    return {
        "title": title,
        "total_shots": len(shots),
        "shots": shots,
        "section_image_map": _build_section_image_map(shots),
    }


def _build_section_image_map(shots: list) -> list[dict]:
    """Convert shot list to section_image_map format for wechat pipeline."""
    return [
        {
            "section": s["after_section"],
            "topic": s["topic"],
            "style": s["style"],
            "purpose": s["core_idea"],
            "structure_type": s["structure_type"],
            "prompt": s["prompt"],
            "image": "",
        }
        for s in shots
    ]


def generate_images(shot_list: dict, output_dir: Path) -> list[str]:
    """Call image_gen.py for each shot. Returns list of generated image paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths = []

    for s in shot_list.get("shots", []):
        if s["status"] == "generated":
            continue
        prompt = s.get("prompt", "")
        if not prompt:
            continue
        out_path = output_dir / f"{s['id']}.jpg"

        try:
            r = subprocess.run(
                [sys.executable, str(IMAGE_GEN), "--prompt", prompt, "--output", str(out_path)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and out_path.is_file():
                s["status"] = "generated"
                s["image_path"] = str(out_path)
                image_paths.append(str(out_path))
            else:
                s["status"] = "failed"
                s["error"] = (r.stderr or r.stdout or "unknown")[:100]
        except Exception as e:
            s["status"] = "failed"
            s["error"] = str(e)[:100]

    # Update section_image_map with generated paths
    for item in shot_list.get("section_image_map", []):
        topic = item["topic"]
        for s in shot_list.get("shots", []):
            if s["topic"] == topic and s.get("image_path"):
                item["image"] = s["image_path"]

    return image_paths


def illustrate_for_pipeline(draft: dict) -> Optional[dict]:
    """Pipeline integration entry point.

    Called by content_platform.pipeline.run() → media._generate_illustration().

    Expected draft format:
        {"title": "...", "body": "...", "topic": "..."}
    Returns:
        {"illustrations": [{"prompt": "...", "structure": "...", ...}],
         "section_image_map": [...],
         "shot_count": int}
    """
    title = draft.get("title", draft.get("topic", ""))
    body = draft.get("body", "")
    if not body or len(body) < 100:
        return None

    # Analyze article → shot list
    result = analyze_article(title, body, max_shots=6)
    if not result["shots"]:
        return None

    # Build output matching expected format
    illustrations = []
    for s in result["shots"]:
        illustrations.append({
            "prompt": s["prompt"],
            "structure": s["structure_type"],
            "style": s["style"],
            "topic": s["topic"],
            "section": s["after_section"],
            "labels": [],
            "accent": "ikb_blue",
        })

    return {
        "illustrations": illustrations,
        "section_image_map": result["section_image_map"],
        "shot_count": len(illustrations),
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="文章配图分析引擎")
    p.add_argument("--title", default="未命名文章", help="文章标题")
    p.add_argument("--body", required=True, help="文章正文文本文件路径")
    p.add_argument("--output", default="/tmp/shot_list.json", help="输出 shot list JSON")
    p.add_argument("--generate", action="store_true", help="生图")
    p.add_argument("--output-dir", default="/tmp/article_shots", help="图片输出目录")
    args = p.parse_args()

    body_path = Path(args.body)
    body = body_path.read_text(encoding="utf-8") if body_path.is_file() else args.body

    result = analyze_article(args.title, body)
    if args.generate:
        generate_images(result, Path(args.output_dir))

    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ shot list → {args.output}")
    print(f"   配图数: {result['total_shots']}")
