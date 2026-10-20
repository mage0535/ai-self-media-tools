#!/usr/bin/env python3
"""
shotcraft_core_v2.py — video-shotcraft 新增镜头卡（camera/data/effects/opening/rhythm类）

来源：https://github.com/Vincentwei1021/video-shotcraft (5.3k star)
将 152 张镜头配方卡中新增的 camera/data/effects/opening/rhythm 类别
翻译为 HTML+CSS+JS 动画，适配现有知识卡片视频管线。

使用方式：
  from scripts.shotcraft_core_v2 import SHOT_CARD_REGISTRY as CORE_V2
  # 与 shotcraft_moves.SHOT_CARD_REGISTRY 合并使用
"""

import math
import random

SHOT_CARD_REGISTRY = {}

def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta

# ── Camera Moves ──────────────────────────

_register("basic-3d-scene", {
    "description": "impress.js式空间演示：卡片散布3D空间，相机依次飞行对齐，末步总览",
    "duration_frames": 180,
    "css": {
        ".scene": {
            "animation": "b3d-cam 6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "transform-style": "preserve-3d",
            "perspective": "1200px",
        },
        ".card": {
            "position": "absolute",
            "animation": "b3d-card 6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".overview": {
            "animation": "b3d-overview 6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "b3d-cam": [
            {"offset": 0, "transform": "scale(1) rotateX(0deg) rotateY(0deg) translateZ(0)"},
            {"offset": 0.24, "transform": "scale(1) rotateX(0deg) rotateY(0deg) translateZ(0)"},
            {"offset": 0.48, "transform": "scale(1) rotateX(0deg) rotateY(40deg) translateX(-520px)"},
            {"offset": 0.74, "transform": "scale(1) rotateX(0deg) rotateY(40deg) rotateZ(-90deg) translateX(-520px)"},
            {"offset": 1, "transform": "scale(0.32) rotateX(0deg) rotateY(40deg) rotateZ(-90deg) translateX(-520px)"},
        ],
        "b3d-card": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.5, "opacity": 0.4, "filter": "blur(2px)"},
            {"offset": 0.75, "opacity": 0.4, "filter": "blur(2px)"},
            {"offset": 1, "opacity": 1, "filter": "blur(0)"},
        ],
        "b3d-overview": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.78, "opacity": 0},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("cursor-flyover", {
    "description": "整页俯瞰淡入后相机依次飞到四角特写，SVG光标同步指点并留下点击涟漪",
    "duration_frames": 180,
    "css": {
        ".scene": {
            "animation": "cfo-cam 6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".cursor": {
            "animation": "cfo-cursor 6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".ripple": {
            "animation": "cfo-ripple 0.6s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "cfo-cam": [
            {"offset": 0, "transform": "scale(0.8) translate(0, 0)", "filter": "blur(5px)"},
            {"offset": 0.14, "transform": "scale(0.8) translate(0, 0)", "filter": "blur(0)"},
            {"offset": 0.32, "transform": "scale(1.72) translate(12%, 12%)"},
            {"offset": 0.52, "transform": "scale(1.72) translate(-12%, 12%)"},
            {"offset": 0.72, "transform": "scale(1.72) translate(-12%, -12%)"},
            {"offset": 0.91, "transform": "scale(1.72) translate(12%, -12%)"},
            {"offset": 1, "transform": "scale(1.72) translate(12%, -12%)"},
        ],
        "cfo-cursor": [
            {"offset": 0, "left": "50%", "top": "50%"},
            {"offset": 0.32, "left": "70%", "top": "70%"},
            {"offset": 0.52, "left": "30%", "top": "70%"},
            {"offset": 0.72, "left": "30%", "top": "30%"},
            {"offset": 0.91, "left": "70%", "top": "30%"},
            {"offset": 1, "left": "70%", "top": "30%"},
        ],
        "cfo-ripple": [
            {"offset": 0, "transform": "scale(0.3)", "opacity": 0.6},
            {"offset": 1, "transform": "scale(1.9)", "opacity": 0},
        ],
    }
})

# ── Data Moves ────────────────────────────

_register("counter-confetti", {
    "description": "大数字easeOutQuart冲刺计数带scale过冲，纸屑从两侧抛物线炸入，冲击环扩散",
    "duration_frames": 138,
    "css": {
        ".counter": {
            "animation": "cc-count 2.3s cubic-bezier(0.25, 0.1, 0.25, 1) forwards",
        },
        ".confetti": {
            "animation": "cc-confetti 1.2s ease-out forwards",
            "opacity": 0,
        },
        ".ring": {
            "animation": "cc-ring 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "cc-count": [
            {"offset": 0, "transform": "scale(0.2)", "opacity": 0},
            {"offset": 0.2, "transform": "scale(1.3)", "opacity": 1},
            {"offset": 0.85, "transform": "scale(1.3)", "opacity": 1},
            {"offset": 1, "transform": "scale(1)", "opacity": 1},
        ],
        "cc-confetti": [
            {"offset": 0, "transform": "translateX(-250px) translateY(0) rotate(0deg)", "opacity": 0},
            {"offset": 0.2, "opacity": 1},
            {"offset": 0.6, "transform": "translateX(0) translateY(-120px) rotate(360deg)", "opacity": 1},
            {"offset": 1, "transform": "translateX(20px) translateY(40px) rotate(720deg)", "opacity": 0.8},
        ],
        "cc-ring": [
            {"offset": 0, "transform": "scale(0.35)", "opacity": 0.8},
            {"offset": 1, "transform": "scale(2.95)", "opacity": 0},
        ],
    }
})

_register("hatch-depth", {
    "description": "剖面线填充深度：线条密度从疏到密揭示数据层次，末段高亮关键区域",
    "duration_frames": 90,
    "css": {
        ".hatch": {
            "animation": "hd-fill 3s linear forwards",
            "opacity": 0,
        },
        ".highlight": {
            "animation": "hd-glow 3s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "hd-fill": [
            {"offset": 0, "opacity": 0, "background-size": "200px 200px"},
            {"offset": 0.5, "opacity": 0.6, "background-size": "80px 80px"},
            {"offset": 1, "opacity": 1, "background-size": "30px 30px"},
        ],
        "hd-glow": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.7, "opacity": 0},
            {"offset": 1, "opacity": 1, "filter": "brightness(1.4)"},
        ],
    }
})

# ── Effects ───────────────────────────────

_register("aurora-bloom-bg-flip", {
    "description": "浅灰底升起紫橙柔焦blob，0.36s内压暗到近黑，文案blur-out换句blur-in",
    "duration_frames": 156,
    "css": {
        ".aurora": {
            "animation": "ab-flip 5.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".blob": {
            "animation": "ab-blob 5.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "filter": "blur(60px)",
        },
        ".line-a": {
            "animation": "ab-out 2.2s ease-in forwards",
        },
        ".line-b": {
            "animation": "ab-in 2.2s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "ab-flip": [
            {"offset": 0, "background": "#ececec"},
            {"offset": 0.63, "background": "#ececec"},
            {"offset": 0.70, "background": "#0a0a12"},
            {"offset": 1, "background": "#0a0a12"},
        ],
        "ab-blob": [
            {"offset": 0, "transform": "translateY(32%) scale(1)", "opacity": 0},
            {"offset": 0.04, "opacity": 0.8},
            {"offset": 0.62, "transform": "translateY(-6%) scale(1.25)", "opacity": 1},
            {"offset": 0.70, "opacity": 0.4},
            {"offset": 1, "opacity": 0.4},
        ],
        "ab-out": [
            {"offset": 0, "opacity": 1, "filter": "blur(0)"},
            {"offset": 1, "opacity": 0, "filter": "blur(8px)"},
        ],
        "ab-in": [
            {"offset": 0, "opacity": 0, "filter": "blur(8px)"},
            {"offset": 1, "opacity": 1, "filter": "blur(0)"},
        ],
    }
})

_register("scanline-annotate-focus", {
    "description": "扫描线扫过画面，到目标区域暂停放大标注，扫描线做视觉引导",
    "duration_frames": 90,
    "css": {
        ".scanline": {
            "animation": "saf-scan 3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".focus-box": {
            "animation": "saf-focus 3s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "saf-scan": [
            {"offset": 0, "top": "0%", "opacity": 1},
            {"offset": 0.6, "top": "60%", "opacity": 1},
            {"offset": 0.65, "top": "60%", "opacity": 0.4},
            {"offset": 1, "top": "60%", "opacity": 0},
        ],
        "saf-focus": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.65, "opacity": 0},
            {"offset": 1, "opacity": 1, "transform": "scale(1)", "border-color": "#ff6b35"},
        ],
    }
})

_register("scanline-assemble-flyin", {
    "description": "扫描线逐行刷过，内容随扫描线从上到下组装显现，像打印机逐行输出",
    "duration_frames": 100,
    "css": {
        ".scan-wrapper": {
            "animation": "saf2-line 3.3s linear forwards",
        },
        ".content-row": {
            "animation": "saf2-row 3.3s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "saf2-line": [
            {"offset": 0, "top": "0%"},
            {"offset": 1, "top": "100%"},
        ],
        "saf2-row": [
            {"offset": 0, "opacity": 0, "transform": "translateY(20px)"},
            {"offset": 0.4, "opacity": 1, "transform": "translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

# ── Opening ───────────────────────────────

_register("fracture", {
    "description": "5x5瓦片从3D碎片态按中心波纹逐圈聚合，停一拍亮字，随后碎片飞散出画",
    "duration_frames": 156,
    "css": {
        ".tile": {
            "animation": "fr-assemble 5.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".title-word": {
            "animation": "fr-title 5.2s ease-in-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "fr-assemble": [
            {"offset": 0, "transform": "translateX(-450px) translateY(-300px) rotateX(180deg) rotateZ(180deg)", "opacity": 0},
            {"offset": 0.1, "opacity": 0.9},
            {"offset": 0.5, "transform": "translateX(0) translateY(0) rotateX(0) rotateZ(0)", "opacity": 1},
            {"offset": 0.7, "transform": "translateX(0) translateY(0) rotateX(0) rotateZ(0)", "opacity": 1},
            {"offset": 1, "transform": "translateX(650px) translateY(400px) rotateZ(150deg)", "opacity": 0},
        ],
        "fr-title": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.42, "opacity": 1},
            {"offset": 0.7, "opacity": 1},
            {"offset": 0.78, "opacity": 0},
            {"offset": 1, "opacity": 0},
        ],
    }
})

# ── Rhythm ────────────────────────────────

_register("quad-split-parallel-scenes", {
    "description": "2x2四宫格并行跑四个微场景，关键节拍错开3-6帧制造信息轰炸",
    "duration_frames": 63,
    "css": {
        ".quad-tl": {
            "animation": "qs-tl 2.1s ease-in-out forwards",
            "background": "#c3c6cc",
        },
        ".quad-tr": {
            "animation": "qs-tr 2.1s ease-in-out forwards",
            "background": "#f2f1ef",
        },
        ".quad-bl": {
            "animation": "qs-bl 2.1s ease-in-out forwards",
            "background": "#e7e6e3",
        },
        ".quad-br": {
            "animation": "qs-br 2.1s ease-in-out forwards",
            "background": "#b8bcc3",
        }
    },
    "keyframes": {
        "qs-tl": [
            {"offset": 0, "transform": "scale(1)", "opacity": 1},
            {"offset": 0.8, "transform": "scale(1.35)", "opacity": 1},
            {"offset": 1, "transform": "scale(1.45)", "opacity": 1},
        ],
        "qs-tr": [
            {"offset": 0, "transform": "scale(1)", "filter": "blur(0)"},
            {"offset": 0.42, "transform": "scale(1)", "filter": "blur(0)"},
            {"offset": 0.48, "transform": "scale(2.1)", "filter": "blur(4px)"},
            {"offset": 0.54, "transform": "scale(2.1)", "filter": "blur(0)"},
            {"offset": 1, "transform": "scale(2.1)"},
        ],
        "qs-bl": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.24, "opacity": 1, "transform": "scale(1)"},
            {"offset": 0.46, "opacity": 1},
            {"offset": 0.56, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        "qs-br": [
            {"offset": 0, "opacity": 0.6},
            {"offset": 0.42, "transform": "scale(0.7)"},
            {"offset": 0.74, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

import sys as _sys_v2
if __name__ == "__main__":
    print(f"shotcraft_core_v2 registered: {len(SHOT_CARD_REGISTRY)} shots", file=_sys_v2.stderr)
