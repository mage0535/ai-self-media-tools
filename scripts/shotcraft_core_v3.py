#!/usr/bin/env python3
"""
shotcraft_core_v3.py — video-shotcraft 新增镜头卡（interaction/effects/data补充）

来源：https://github.com/Vincentwei1021/video-shotcraft (5.3k star)
"""

import math
import random

SHOT_CARD_REGISTRY = {}

def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta

# ── Effects ───────────────────────────────

_register("assemble-then-type-flyin", {
    "description": "空网格上组件骨架从四面八方飞入贴合，随后文字逐字3D旋转落位，先大标题后小标注",
    "duration_frames": 156,
    "css": {
        ".skeleton-item": {
            "animation": "atf-skeleton 5.2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".skeleton-item-2": {
            "animation": "atf-skeleton2 5.2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".word-3d": {
            "animation": "atf-word 5.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".word-3d-sm": {
            "animation": "atf-word-sm 5.2s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "atf-skeleton": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-120px) rotate(-8deg)", "filter": "blur(2px)"},
            {"offset": 0.25, "opacity": 1, "transform": "translateX(0) rotate(0deg)", "filter": "blur(0)"},
            {"offset": 1, "opacity": 1, "transform": "translateX(0) rotate(0deg)"},
        ],
        "atf-skeleton2": [
            {"offset": 0, "opacity": 0, "transform": "translateX(200px) translateY(-60px) rotate(8deg)", "filter": "blur(2px)"},
            {"offset": 0.35, "opacity": 1, "transform": "translateX(0) translateY(0) rotate(0deg)", "filter": "blur(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "atf-word": [
            {"offset": 0, "opacity": 0, "transform": "rotateX(90deg) scale(1.5)"},
            {"offset": 0.45, "opacity": 0},
            {"offset": 0.7, "opacity": 1, "transform": "rotateX(0deg) scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "atf-word-sm": [
            {"offset": 0, "opacity": 0, "transform": "rotateX(90deg)"},
            {"offset": 0.55, "opacity": 0},
            {"offset": 0.8, "opacity": 1, "transform": "rotateX(0deg)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

# ── Data ──────────────────────────────────

_register("avatar-grid-radial-build-colorize", {
    "description": "8x7卡片网格由中心分环生长铺满，随后15%卡片随机时刻染红标异常，标题图例常驻中央",
    "duration_frames": 168,
    "css": {
        ".avatar-grid": {
            "animation": "agrb-build 5.6s ease-out forwards",
        },
        ".avatar-cell": {
            "animation": "agrb-cell 5.6s cubic-bezier(0.25, 0.46, 0.45, 0.94) forwards",
            "opacity": 0,
        },
        ".avatar-cell-alert": {
            "animation": "agrb-alert 5.6s ease-in forwards",
            "opacity": 0,
        },
        ".grid-title": {
            "animation": "agrb-title 5.6s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "agrb-build": [
            {"offset": 0, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        "agrb-cell": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.3, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1, "transform": "scale(1)"},
        ],
        "agrb-alert": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.3, "opacity": 0},
            {"offset": 0.5, "opacity": 1, "background": "#fdecec", "border-color": "#f6cfcf"},
            {"offset": 1, "opacity": 1, "background": "#fdecec", "border-color": "#f6cfcf"},
        ],
        "agrb-title": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.98)"},
            {"offset": 0.3, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

# ── Interaction ───────────────────────────

_register("chip-grid-single-select-blackout", {
    "description": "芯片网格单选：选中芯片高亮放大，其余全部压暗，像聚光灯扫过",
    "duration_frames": 60,
    "css": {
        ".chip-grid": {
            "animation": "cgss-bg 2s ease-out forwards",
        },
        ".chip": {
            "animation": "cgss-chip 2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        },
        ".chip-selected": {
            "animation": "cgss-sel 2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        }
    },
    "keyframes": {
        "cgss-bg": [
            {"offset": 0, "filter": "brightness(1)"},
            {"offset": 0.6, "filter": "brightness(0.6)"},
            {"offset": 1, "filter": "brightness(0.6)"},
        ],
        "cgss-chip": [
            {"offset": 0, "opacity": 1, "transform": "scale(1)"},
            {"offset": 0.6, "opacity": 0.4, "transform": "scale(0.9)"},
            {"offset": 1, "opacity": 0.4, "transform": "scale(0.9)"},
        ],
        "cgss-sel": [
            {"offset": 0, "opacity": 0.4, "transform": "scale(0.9)", "filter": "brightness(1)"},
            {"offset": 0.6, "opacity": 1, "transform": "scale(1.15)", "filter": "brightness(1.3)"},
            {"offset": 1, "opacity": 1, "transform": "scale(1.15)", "filter": "brightness(1.3)"},
        ],
    }
})

_register("research-card-stack-scroll", {
    "description": "研究卡片堆叠：上层卡片依次被翻走，露出下层卡片，像翻牌查看结果",
    "duration_frames": 90,
    "css": {
        ".stack": {
            "animation": "rcss-stack 3s ease-in-out forwards",
        },
        ".stack-card": {
            "animation": "rcss-card 3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".stack-card-back": {
            "animation": "rcss-card-back 3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        }
    },
    "keyframes": {
        "rcss-stack": [
            {"offset": 0, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        "rcss-card": [
            {"offset": 0, "transform": "translateY(0) rotate(0deg)", "opacity": 1},
            {"offset": 0.3, "transform": "translateY(-40px) rotate(-4deg)", "opacity": 0.8},
            {"offset": 0.35, "transform": "translateY(-60px) rotate(-6deg)", "opacity": 0},
            {"offset": 1, "opacity": 0},
        ],
        "rcss-card-back": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.9)"},
            {"offset": 0.35, "opacity": 0},
            {"offset": 0.5, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("avatar-bracket-carousel", {
    "description": "头像括弧轮播：多个头像沿弧形排列，中心头像放大，两侧缩小，像括弧展开",
    "duration_frames": 90,
    "css": {
        ".avatar-ring": {
            "animation": "abc-ring 3s ease-in-out forwards",
        },
        ".avatar-center": {
            "animation": "abc-center 3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".avatar-side": {
            "animation": "abc-side 3s ease-in-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "abc-ring": [
            {"offset": 0, "transform": "rotateY(0deg)"},
            {"offset": 1, "transform": "rotateY(0deg)"},
        ],
        "abc-center": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.6)"},
            {"offset": 0.4, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1, "transform": "scale(1.05)"},
        ],
        "abc-side": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-60px) scale(0.7)"},
            {"offset": 0.5, "opacity": 0.6, "transform": "translateX(0) scale(0.8)"},
            {"offset": 1, "opacity": 0.6, "transform": "translateX(0) scale(0.8)"},
        ],
    }
})

_register("doc-park-left-pill-deal", {
    "description": "文档左泊+胶囊展开：文档滑到左侧固定，右侧胶囊标签依次展开补充信息",
    "duration_frames": 75,
    "css": {
        ".doc-panel": {
            "animation": "dppd-doc 2.5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        },
        ".pill-row": {
            "animation": "dppd-pill 2.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "dppd-doc": [
            {"offset": 0, "transform": "translateX(0) scale(1)", "opacity": 1},
            {"offset": 0.45, "transform": "translateX(-55%) scale(0.85)", "opacity": 1},
            {"offset": 1, "transform": "translateX(-55%) scale(0.85)"},
        ],
        "dppd-pill": [
            {"offset": 0, "opacity": 0, "transform": "translateX(40px) scale(0.8)"},
            {"offset": 0.55, "opacity": 0},
            {"offset": 0.75, "opacity": 1, "transform": "translateX(0) scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("input-trigger-moves", {
    "description": "输入框触发动效：焦点框高亮+光标闪烁，输入内容逐字出现，联想下拉展开",
    "duration_frames": 80,
    "css": {
        ".input-field": {
            "animation": "itm-field 2.6s ease-in-out forwards",
        },
        ".input-cursor": {
            "animation": "itm-cursor 1s steps(2) infinite",
        },
        ".input-suggestion": {
            "animation": "itm-suggest 2.6s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "itm-field": [
            {"offset": 0, "border-color": "#ccc", "box-shadow": "0 0 0 0 rgba(0,120,255,0)"},
            {"offset": 0.25, "border-color": "#0078ff", "box-shadow": "0 0 0 3px rgba(0,120,255,0.2)"},
            {"offset": 1, "border-color": "#0078ff"},
        ],
        "itm-cursor": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.5, "opacity": 0},
            {"offset": 1, "opacity": 1},
        ],
        "itm-suggest": [
            {"offset": 0, "opacity": 0, "transform": "translateY(-8px)"},
            {"offset": 0.7, "opacity": 0},
            {"offset": 1, "opacity": 1, "transform": "translateY(0)"},
        ],
    }
})

import sys as _sys_v3
if __name__ == "__main__":
    print(f"shotcraft_core_v3 registered: {len(SHOT_CARD_REGISTRY)} shots", file=_sys_v3.stderr)
