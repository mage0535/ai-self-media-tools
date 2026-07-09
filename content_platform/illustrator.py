"""
illustrator.py — 归藏材质插画桥接模块

将 guizang-material-illustration 的工作流接入 ai-self-media-tools 管线。

核心能力：
  - 从文章/笔记/数据中提取核心概念
  - 按归藏材质风格生成带中文标签的解释图
  - 图表美化（从数据/截图语义重画）
  - 参考辅助出图（冷门概念先查再画）

依赖：
  - ~/.hermes/skills/creative/guizang-material-illustration/ 已安装
  - image_generate 工具可用（GPT-Image 2.0 / Codex auth）
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

SKILL_DIR = Path.home() / ".hermes" / "skills" / "creative" / "guizang-material-illustration"


def is_available() -> bool:
    """检查归藏材质插画 Skill 是否可用"""
    return SKILL_DIR.is_dir() and (SKILL_DIR / "SKILL.md").exists()


class GuizangIllustrator:
    """
    归藏材质插画生成器。

    封装 guizang-material-illustration 的参考文件，
    提供从文本到图内提示词再到图片生成的标准流程。
    """

    ACCENT_COLORS = {
        "ikb_blue": "#002FA7",
        "safety_orange": "#FF6B35",
        "lemon_green": "#C5E803",
        "lemon_yellow": "#FFD500",
        "signal_red": "#E60012",
    }

    VISUAL_STRUCTURES = [
        "cycle",        # 循环/反馈/迭代
        "pipeline",     # 流程/管线/输入→处理→输出
        "hub_and_spoke", # 中心协调多分支
        "before_after",  # 前后对比/状态变更
        "layer_stack",   # 层级/架构/依赖
        "data_scene",    # 数据面板+场景
        "science",       # 科学机制/部件/力/反应
        "text_scene",    # 文学/历史/日常场景
    ]

    def __init__(self, accent: str = "ikb_blue", ratio: str = "16:9"):
        if accent not in self.ACCENT_COLORS:
            accent = "ikb_blue"
        self.accent = accent
        self.accent_hex = self.ACCENT_COLORS[accent]
        self.ratio = ratio

    def _read_ref(self, name: str) -> str:
        """读取 reference 文件内容"""
        path = SKILL_DIR / "references" / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
        return ""

    def _choose_structure(self, text: str) -> str:
        """根据文本内容自动判断最适合的图解结构"""
        text_lower = text.lower()

        # 循环/反馈/迭代
        if any(w in text_lower for w in ["循环", "反馈", "迭代", "闭环", "cycle", "loop", "反馈回路"]):
            return "cycle"
        # 流程
        if any(w in text_lower for w in ["流程", "步骤", "管线", "pipeline", "workflow", "输入", "输出"]):
            return "pipeline"
        # 架构/层级
        if any(w in text_lower for w in ["架构", "层级", "依赖", "体系", "架构图", "模块"]):
            return "layer_stack"
        # 对比
        if any(w in text_lower for w in ["对比", "区别", "vs", "before", "after", "前后", "升级"]):
            return "before_after"
        # 科学
        if any(w in text_lower for w in ["力", "电", "磁", "化学", "生物", "物理", "机制", "结构"]):
            return "science"
        # 数据
        if any(w in text_lower for w in ["数据", "图表", "指标", "增长", "趋势", "kpi", "统计"]):
            return "data_scene"
        # 中心辐射
        if any(w in text_lower for w in ["中心", "协调", "管理", "hub", "平台", "生态"]):
            return "hub_and_spoke"

        return "text_scene"

    def build_prompt(self, source_text: str, title: str = "",
                     labels: Optional[list[str]] = None,
                     structure: str = "") -> dict:
        """
        从源文本构建归藏材质插画提示词。

        返回:
            { "prompt": str,        # 完整的图像生成提示词
              "structure": str,     # 选定的图解结构
              "labels": list[str],  # 图内标签
              "accent": str,        # 强调色
              "ratio": str }        # 宽高比
        """
        if not structure:
            structure = self._choose_structure(source_text)

        # 从源文本提取核心标签（如果没有提供）
        if not labels:
            labels = self._extract_labels(source_text, structure)

        # 构建核心提示词
        structure_names = {
            "cycle": "循环机制图: 3-4 个对象以箭头连接成环形, 每个对象带短标签",
            "pipeline": "流程图解: 从左到右排列步骤对象, 箭头连接, 每步带短标签",
            "hub_and_spoke": "中心辐射图: 中央枢纽连接周围分支, 带标签",
            "before_after": "前后对比图: 左侧旧状态 → 中间变换 → 右侧新状态",
            "layer_stack": "层级架构图: 垂直堆叠层, 每层右侧带标签说明",
            "data_scene": "数据场景: 场景背景 + 嵌入的图表/指标面板",
            "science": "科学机制图: 展示各部件、方向、力和反应关系, 带标签",
            "text_scene": "意象场景: 布置一个能解释抽象概念的日常/文学场景",
        }

        structure_desc = structure_names.get(structure, "概念图解: 清晰展示对象和关系")

        labels_text = "、".join(labels[:6])

        prompt = (
            f"归藏材质插画风格。{structure_desc}。\n"
            f"干净白色背景，黑色墨线+柔和灰面3D质感。\n"
            f"仅用一个强调色 ({self.accent_hex}): 用于箭头、活动块、标签连接线。\n"
            f"柔光工作室照明，轻微接触阴影，无渐变光晕。\n\n"
            f"图内中文标签（黑字白底标签板）：{labels_text}\n"
            f"标签短小精炼，水平放置，大号清晰。\n\n"
            f"宽高比 {self.ratio}，所有对象和标签在安全区内，不被裁剪。\n"
            f"居中垂直构图。\n"
            f"不要Logo/水印/UI界面元素。\n"
            f"不要密集图例或段落文字。\n\n"
            f"概念来源：{title or source_text[:200]}"
        )

        return {
            "prompt": prompt,
            "structure": structure,
            "labels": labels,
            "accent": self.accent,
            "ratio": self.ratio,
        }

    def _extract_labels(self, text: str, structure: str) -> list[str]:
        """从文本中提取适合做图内标签的短词组"""
        # 简单策略: 按标点/换行分段，提取关键词
        parts = re.split(r'[。，；：、\n\r]', text)
        candidates = []
        for p in parts:
            p = p.strip()
            # 只保留 2-6 字的中文片段
            if re.match(r'^[\u4e00-\u9fff]{2,6}$', p):
                candidates.append(p)
            # 也接受 2-6 字 + 少量英文/数字
            elif re.match(r'^[\u4e00-\u9fff\w]{2,8}$', p):
                candidates.append(p)

        # 按结构补充默认标签
        structure_defaults = {
            "cycle": ["输入", "处理", "输出", "反馈"],
            "pipeline": ["开始", "步骤一", "步骤二", "完成"],
            "hub_and_spoke": ["中心", "分支1", "分支2", "分支3"],
            "before_after": ["改造前", "改造", "改造后"],
            "layer_stack": ["顶层", "中间层", "底层"],
            "data_scene": ["指标", "趋势", "洞察"],
            "science": ["对象", "力", "方向"],
            "text_scene": ["场景", "主体", "意象"],
        }

        if not candidates:
            candidates = structure_defaults.get(structure, ["概念1", "概念2"])

        return candidates[:6]


def generate_illustration_prompt(source_text: str, title: str = "",
                                 accent: str = "ikb_blue",
                                 ratio: str = "16:9") -> dict:
    """
    一站式生成归藏材质插画提示词。

    供 ai-self-media-tools 管线内部调用。
    """
    illustrator = GuizangIllustrator(accent=accent, ratio=ratio)
    return illustrator.build_prompt(source_text, title=title)


def illustrate_for_pipeline(draft: dict) -> Optional[dict]:
    """
    管线集成入口：根据草稿内容生成插画提示。

    返回 { "illustrations": [{ "prompt", "structure", "labels", "accent" }] }
    如果没有合适的概念，返回 None。
    """
    body = draft.get("body", "")
    title = draft.get("title", "")
    if not body and not title:
        return None

    # 从正文中提取值得配图的概念（简单分段取核心段落）
    paragraphs = [p.strip() for p in body.split("\n\n") if len(p.strip()) > 20]
    concepts = []
    for para in paragraphs[:3]:
        if len(para) < 30:
            continue
        result = generate_illustration_prompt(para, title)
        concepts.append(result)
        if len(concepts) >= 3:
            break

    if not concepts:
        # 兜底：用标题生成一张
        result = generate_illustration_prompt(title, title)
        concepts.append(result)

    return {"illustrations": concepts}
