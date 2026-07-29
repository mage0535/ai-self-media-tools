#!/usr/bin/env python3
"""
cinema_composition.py — Cinema DNA 构图规则引擎

从 cinema-dna-21x9x3 (v1.2.2) 提取的镜头语言判断规则，集成到视频卡片管线。

核心功能：
  visual_traffic(text)       → 推导视线流量 / 构图策略
  color_narrative(text)      → 解析色彩方案
  pressure_to_composition(t) → 关系压力 → 构图类型
  anti_template_check(path)  → 反模板化 / 反 CG 质量门禁

使用方式：
  from scripts.cinema_composition import visual_traffic, color_narrative
  traffic = visual_traffic("文章正文…")
  colors  = color_narrative("文章正文…")
"""

import re
import json
from pathlib import Path

# ═══════════════════════════════════════════
# 色彩叙事系统
# ═══════════════════════════════════════════

# 场景关键词 → 色彩方案映射
SCENE_COLOR_MAP = {
    # 科技 / 编程 / AI
    r"代码|编程|开发|服务器|终端|命令行|CI|CD|部署": {
        "primary": (20, 25, 35),       # 深蓝黑
        "secondary": (45, 55, 75),     # 藏蓝
        "accent": (0, 200, 255),       # 青蓝 (终端绿/蓝)
        "source": "显示器蓝光 + 暗室环境",
        "mood": "专注、冷静、高信息密度",
        "bgm_hint": "ambient electronic, minimal synth",
    },
    r"AI|人工智能|机器学习|大模型|训练|推理": {
        "primary": (15, 10, 25),       # 深紫黑
        "secondary": (40, 30, 55),     # 紫灰
        "accent": (180, 120, 255),     # 紫罗兰
        "source": "服务器指示灯 + 数据流光晕",
        "mood": "前沿、深邃、高能量",
        "bgm_hint": "synthwave, cyberpunk ambient",
    },
    # 效率 / 工作流 / 自动化
    r"效率|工作流|自动化|流程|管线|pipeline|workflow": {
        "primary": (30, 35, 40),       # 煤灰
        "secondary": (55, 65, 70),     # 钢蓝灰
        "accent": (100, 200, 180),     # 青绿 (进度条色)
        "source": "办公室人工照明 + 屏幕反光",
        "mood": "有序、专业、可执行",
        "bgm_hint": "acoustic guitar, folk",
    },
    # 数据 / 分析 / 指标
    r"数据|指标|分析|统计|仪表盘|dashboard|KPI|报表": {
        "primary": (20, 25, 30),
        "secondary": (40, 50, 60),
        "accent": (255, 180, 50),      # 琥珀色 (警示灯)
        "source": "大屏数据可视化灯光",
        "mood": "严肃、高对比、决策感",
        "bgm_hint": "cinematic percussive",
    },
    # 教程 / 教育 / 知识
    r"教程|课程|学习|指南|入门|基础|教学": {
        "primary": (240, 240, 235),    # 暖白
        "secondary": (210, 210, 200),  # 米灰
        "accent": (50, 150, 200),      # 知性蓝
        "source": "自然光 + 白板 / 纸张反射",
        "mood": "开放、亲和、清晰",
        "bgm_hint": "piano, light strings",
    },
    # 工具 / 产品 / 开源项目
    r"工具|开源|项目|GitHub|仓库|release|发布": {
        "primary": (30, 35, 45),
        "secondary": (55, 65, 80),
        "accent": (50, 210, 120),      # GitHub 绿
        "source": "屏幕投射 + 桌面灯光",
        "mood": "务实、可信、有活力",
        "bgm_hint": "lo-fi beats, hip hop instrumental",
    },
    # 创意 / 设计 / 视觉
    r"设计|创意|UI|UX|视觉|排版|审美": {
        "primary": (245, 245, 245),    # 近白
        "secondary": (220, 220, 230),  # 冷灰
        "accent": (255, 100, 100),     # 珊瑚红
        "source": "设计台灯 + 校色屏幕",
        "mood": "干净、利落、高审美",
        "bgm_hint": "jazz, chill electronic",
    },
    # 默认回退
    r"": {
        "primary": (35, 35, 40),
        "secondary": (55, 55, 65),
        "accent": (100, 180, 230),
        "source": "混合环境光",
        "mood": "中性",
        "bgm_hint": "ambient",
    },
}


def color_narrative(text: str) -> dict:
    """
    从文案中提取色彩叙事方案。

    扫描关键词匹配 SCENE_COLOR_MAP，返回最匹配的色彩方案。
    包含主色、次色、强调色、色彩来源说明、情绪标签、BGM 建议。
    """
    if not text:
        return dict(SCENE_COLOR_MAP[""])

    text_lower = text.lower()
    matches = []

    for pattern, scheme in SCENE_COLOR_MAP.items():
        if not pattern:
            continue
        if re.search(pattern, text, re.IGNORECASE):
            # 计算匹配密度作为权重
            count = len(re.findall(pattern, text_lower))
            matches.append((count, scheme))

    if not matches:
        return dict(SCENE_COLOR_MAP[""])

    # 按匹配密度降序取最佳
    matches.sort(key=lambda x: -x[0])
    best = dict(matches[0][1])

    # 如果多个大类匹配，混合强调色
    if len(matches) > 1 and matches[1][0] > 0:
        accent2 = matches[1][1].get("accent", best["accent"])
        # 混合强调色（加权平均）
        w1, w2 = matches[0][0], matches[1][0]
        total = w1 + w2
        best["accent"] = (
            (best["accent"][0] * w1 + accent2[0] * w2) // total,
            (best["accent"][1] * w1 + accent2[1] * w2) // total,
            (best["accent"][2] * w1 + accent2[2] * w2) // total,
        )
        best["source"] += f" + {matches[1][1]['source']}"

    best["matched_keywords"] = [k for k, _ in matches[:2]]
    return best


def color_to_css(scheme: dict) -> dict:
    """将色彩方案转为 CSS 变量和背景渐变色。"""
    p = scheme.get("primary", (35, 35, 40))
    s = scheme.get("secondary", (55, 55, 65))
    a = scheme.get("accent", (100, 180, 230))

    return {
        "bg_gradient": f"linear-gradient(135deg, rgb{p} 0%, rgb{s} 100%)",
        "bg_solid": f"rgb{p}",
        "accent_color": f"rgb{a}",
        "text_primary": "#ffffff",
        "text_secondary": "rgba(255,255,255,0.7)",
        "card_bg": f"rgba({s[0]},{s[1]},{s[2]},0.85)",
        "card_border": f"1px solid rgba({a[0]},{a[1]},{a[2]},0.3)",
    }


# ═══════════════════════════════════════════
# 视线流量分析
# ═══════════════════════════════════════════

# 视线流量模板
VISUAL_TRAFFIC_PATTERNS = [
    {
        "name": "列表扫描",
        "trigger": r"列表|步骤|要点|几种|多个|多少种|对比|区别",
        "traffic": "视线从列表左上进入，沿纵向扫描，被高亮关键词阻断，落在底部结论",
        "composition": "垂直列表布局，奇数行高亮，偶数行低对比",
    },
    {
        "name": "流程引导",
        "trigger": r"流程|步骤|第一阶段|第二阶段|过程|方法|路径",
        "traffic": "视线从流程起点进入，沿箭头方向移动，在判断节点短暂停留，落在终点结果",
        "composition": "水平流程图，节点为圆角矩形，箭头使用强调色",
    },
    {
        "name": "数据陈述",
        "trigger": r"数据|统计|增长|下降|百分比|百万|%|亿|万",
        "traffic": "视线先被最大数字吸引，沿数字大小降序扫视，最后落在趋势线方向",
        "composition": "数字居中放大，背景柱状/折线示意，强调色标注关键转折点",
    },
    {
        "name": "问题解决",
        "trigger": r"问题|困扰|痛点|麻烦|难题|挑战|怎么办|如何解决",
        "traffic": "视线从问题陈述进入，被问号/感叹阻断，沿解决方案路径移动，落在预期收益",
        "composition": "左右对比布局，左侧暗色(问题)，右侧亮色(方案)，中间箭头过渡",
    },
    {
        "name": "故事叙事",
        "trigger": r"曾经|有一次|那年|以前|我发现|经历了|分享一个|真实",
        "traffic": "视线从人物/场景全景进入，被局部特写中断，随动作线落向情感结论",
        "composition": "人物/场景大图作为背景，前景叠加关键文字，文字位于视觉重心",
    },
    {
        "name": "概念解释",
        "trigger": r"是什么|什么是|概念|定义|指的是|理解|原理",
        "traffic": "视线从概念名词进入，被下定义的关键词阻断，沿阐释线扩散到各部分",
        "composition": "中心词放大置顶，解释性文字分层排列，连接线表示概念关系",
    },
    {
        "name": "默认",
        "trigger": r"",
        "traffic": "视线从左上进入，经中央重点区，从右下离开",
        "composition": "均衡排版，主标题 + 正文 + 装饰元素三角形构图",
    },
]


def visual_traffic(text: str, frame_index: int = 0) -> dict:
    """
    从文案推导视线流量策略。

    返回包含 traffic 描述和 composition 建议的 dict。
    frame_index 用于多帧间差异化（同一组不重复流量模式）。
    """
    if not text:
        return {"pattern": "默认", "traffic": VISUAL_TRAFFIC_PATTERNS[-1]["traffic"],
                "composition": VISUAL_TRAFFIC_PATTERNS[-1]["composition"]}

    text_lower = text.lower()
    matches = []

    for i, pattern in enumerate(VISUAL_TRAFFIC_PATTERNS):
        if not pattern["trigger"]:
            continue
        if re.search(pattern["trigger"], text_lower):
            count = len(re.findall(pattern["trigger"], text_lower))
            matches.append((count, i, pattern))

    if not matches:
        return {"pattern": "默认", "traffic": VISUAL_TRAFFIC_PATTERNS[-1]["traffic"],
                "composition": VISUAL_TRAFFIC_PATTERNS[-1]["composition"],
                "frame_index": frame_index}

    # 排序，但用 frame_index 做偏移避免同组重复
    matches.sort(key=lambda x: (-x[0], x[1]))
    chosen_idx = (frame_index) % len(matches)
    chosen = matches[chosen_idx][2]

    return {
        "pattern": chosen["name"],
        "traffic": chosen["traffic"],
        "composition": chosen["composition"],
        "frame_index": frame_index,
    }


# ═══════════════════════════════════════════
# 关系压力 → 构图类型
# ═══════════════════════════════════════════

PRESSURE_TYPES = [
    {
        "name": "被观察",
        "trigger": r"监视|观察|盯着|偷看|被发现|暗中|背后|隐藏",
        "description": "观众隔着一层距离观看事件",
        "layout": "overlay_card",  # 前景文字块 + 背景场景
        "overlay_opacity": 0.60,
    },
    {
        "name": "被困住",
        "trigger": r"被困|限制|无法|不能|只能|困在|卡在|陷入",
        "description": "人物被空间/制度限制",
        "layout": "framed_card",   # 边框式，文字在框内
        "overlay_opacity": 0.55,
    },
    {
        "name": "关系疏离",
        "trigger": r"疏远|距离|分开|陌生|隔阂|隔开|一个人|独自",
        "description": "人物之间存在空间或情感距离",
        "layout": "split_card",    # 左右/上下分割
        "overlay_opacity": 0.50,
    },
    {
        "name": "权力不对等",
        "trigger": r"领导|命令|控制|管理|审批|规则|必须|不准|禁止",
        "description": "权力结构通过空间/构图表现",
        "layout": "hierarchical_card",  # 标题在上，正文在下
        "overlay_opacity": 0.45,
    },
    {
        "name": "心理失衡",
        "trigger": r"困惑|纠结|犹豫|焦虑|压力|迷茫|不确定|挣扎",
        "description": "人物处于不稳定心理状态",
        "layout": "dynamic_card",   # 倾斜/不对称排版
        "overlay_opacity": 0.50,
    },
    {
        "name": "中性传达",
        "trigger": r"",
        "description": "平实传达信息",
        "layout": "balanced_card",  # 均衡布局
        "overlay_opacity": 0.40,
    },
]


def pressure_to_composition(text: str) -> dict:
    """
    从文案判断关系压力类型，返回推荐构图布局。
    """
    if not text:
        return dict(PRESSURE_TYPES[-1])

    text_lower = text.lower()
    matches = []

    for pt in PRESSURE_TYPES:
        if not pt["trigger"]:
            continue
        if re.search(pt["trigger"], text_lower):
            count = len(re.findall(pt["trigger"], text_lower))
            matches.append((count, pt))

    if not matches:
        return dict(PRESSURE_TYPES[-1])

    matches.sort(key=lambda x: -x[0])
    return dict(matches[0][1])


# ═══════════════════════════════════════════
# 反模板化质量检查
# ═══════════════════════════════════════════

def anti_template_check(image_path: str) -> dict:
    """
    对生成的卡片图片进行反模板化 / 反 CG 检查。

    使用 PIL + numpy 分析：
    - 像素颜色分布（是否过于均匀 → 可能是纯色模板）
    - 边缘密度（是否缺少纹理 → 可能是 CG/AI 平滑）
    - 对比度分布（是否过于极端 → 可能是广告风格）

    返回: {
        "passed": bool,
        "checks": [str],
        "suggestions": [str],
    }
    """
    result = {"passed": True, "checks": [], "suggestions": []}
    path = Path(image_path)

    if not path.exists():
        return {"passed": False, "checks": ["❌ 文件不存在"], "suggestions": ["重新生成"]}

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        result["checks"].append("⚠️ 需要 numpy+PIL，跳过高级检测")
        return result

    try:
        img = Image.open(str(path))
        arr_rgb = np.array(img.convert("RGB"))
        arr_gray = np.array(img.convert("L"))
        h, w = arr_gray.shape

        # 1. 像素标准差检测（太均匀 = 模板化）
        std = arr_gray.std()
        result["checks"].append(f"像素标准差: {std:.1f}")
        if std < 20:
            result["checks"].append("⚠️ 标准差 < 20，画面可能过于均匀（模板化风险）")
            result["suggestions"].append("增加背景纹理/渐变/噪点")
        if std < 12:
            result["passed"] = False
            result["checks"].append("❌ 标准差 < 12，极可能为纯色模板")

        # 2. 边缘密度检测（太少 = 过度平滑 / CG）
        edges_h = np.abs(np.diff(arr_gray, axis=1)).mean()
        edges_v = np.abs(np.diff(arr_gray, axis=0)).mean()
        edge_density = (edges_h + edges_v) / 2
        result["checks"].append(f"边缘密度: {edge_density:.2f}")
        if edge_density < 3.0:
            result["checks"].append("⚠️ 边缘密度偏低，可能有过度平滑/AI 感")
            result["suggestions"].append("增加文字边框/阴影/背景纹理")
        if edge_density < 1.5:
            result["passed"] = False
            result["checks"].append("❌ 边缘密度极低，严重过度平滑")

        # 3. 对比度分布（过于极端 = 广告/游戏风格）
        low_pct = (arr_gray < 30).mean() * 100
        high_pct = (arr_gray > 225).mean() * 100
        result["checks"].append(f"暗部 {low_pct:.0f}% / 亮部 {high_pct:.0f}%")
        if low_pct > 40 or high_pct > 40:
            result["checks"].append("⚠️ 对比度过高，接近广告/游戏风格")
            result["suggestions"].append("压缩对比度，增加中间调")

        # 4. 颜色多样性（RGB 通道标准差差异判断是否偏色）
        std_r = arr_rgb[:, :, 0].std()
        std_g = arr_rgb[:, :, 1].std()
        std_b = arr_rgb[:, :, 2].std()
        color_range = max(std_r, std_g, std_b) - min(std_r, std_g, std_b)
        result["checks"].append(f"RGB 标准差差: {color_range:.1f}")
        if color_range > 30:
            result["checks"].append("⚠️ 单通道过强，可能偏色/滤镜过重")

    except Exception as e:
        result["passed"] = False
        result["checks"].append(f"❌ 检测异常: {e}")

    return result


# ═══════════════════════════════════════════
# 场景级分镜策划
# ═══════════════════════════════════════════

def storyboard(text: str, num_scenes: int = 3) -> list[dict]:
    """
    从文案生成多帧分镜策划，每帧包含:
      - traffic: 视线流量
      - composition: 构图建议
      - color: 色彩方案
      - pressure: 关系压力
      - css: 可直接用于 HTML 的 CSS 变量
    """
    scenes = []
    # 分割文案为段落
    paragraphs = [p.strip() for p in text.replace("\n\n", "\n").split("\n") if p.strip()]

    for i in range(num_scenes):
        # 取对应段落，循环使用
        p = paragraphs[i % max(1, len(paragraphs))] if paragraphs else text

        traffic = visual_traffic(p, frame_index=i)
        color = color_narrative(p)
        pressure = pressure_to_composition(p)
        css = color_to_css(color)

        scenes.append({
            "scene_index": i,
            "source_snippet": p[:80] + "…" if len(p) > 80 else p,
            "traffic_pattern": traffic["pattern"],
            "traffic_flow": traffic["traffic"],
            "composition_advice": traffic["composition"],
            "pressure_type": pressure["name"],
            "pressure_description": pressure["description"],
            "layout_template": pressure["layout"],
            "color_scheme": {
                "primary": color.get("primary"),
                "secondary": color.get("secondary"),
                "accent": color.get("accent"),
                "source": color.get("source"),
                "mood": color.get("mood"),
                "bgm_hint": color.get("bgm_hint"),
            },
            "css": css,
        })

    return scenes


def format_storyboard_prompt(scenes: list[dict]) -> str:
    """
    将分镜策划格式化为可嵌入 HTML 模板的 prompt。
    输出每帧的 CSS 覆盖变量。
    """
    lines = ["/* 分镜策划 — cinema-dna composition engine */", ""]

    for i, s in enumerate(scenes):
        lines.append(f"/* === 帧 {i+1} === */")
        lines.append(f"/* 视线: {s['traffic_flow']} */")
        lines.append(f"/* 构图: {s['composition_advice']} */")
        lines.append(f"/* 压力: {s['pressure_type']} — {s['pressure_description']} */")
        lines.append(f"/* 色彩: {s['color_scheme']['mood']} — {s['color_scheme']['source']} */")
        lines.append(f"/* BGM: {s['color_scheme']['bgm_hint']} */")
        css = s["css"]
        lines.append(f".scene-{i} {{")
        lines.append(f"  background: {css['bg_gradient']};")
        lines.append(f"  color: {css['text_primary']};")
        lines.append(f"  --accent: {css['accent_color']};")
        lines.append(f"  --card-bg: {css['card_bg']};")
        lines.append(f"  --card-border: {css['card_border']};")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    test_text = """
    为了省时间我装了15个AI工具，结果每天多花2小时维护它们。
    步骤一：砍掉功能重叠的。这些工具干的事大部分是重叠的。
    数据说大部分人在使用AI工具时都会犯这个错误。
    """

    print("=== 色彩叙事 ===")
    print(json.dumps(color_narrative(test_text), indent=2, ensure_ascii=False))

    print("\n=== 视线流量 ===")
    for i in range(3):
        t = visual_traffic(test_text, frame_index=i)
        print(f"  帧{i}: {t['pattern']} | {t['composition']}")

    print("\n=== 构图压力 ===")
    print(json.dumps(pressure_to_composition(test_text), indent=2, ensure_ascii=False))

    print("\n=== 完整分镜 (3帧) ===")
    scenes = storyboard(test_text, 3)
    print(format_storyboard_prompt(scenes))
