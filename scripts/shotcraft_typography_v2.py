#!/usr/bin/env python3
"""
shotcraft_typography_v2.py — video-shotcraft 新增文字类镜头卡

来源：https://github.com/Vincentwei1021/video-shotcraft (5.3k star)
将 typography 类别新增镜头卡翻译为 HTML+CSS 动画。
"""

import math
import random

SHOT_CARD_REGISTRY = {}

def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta

# ── Typography Moves ──────────────────────

_register("blur-slide", {
    "description": "文字逐词从模糊滑入清晰，错峰stagger形成阅读节奏",
    "duration_frames": 75,
    "css": {
        ".blur-word": {
            "animation": "blur-slide-in 2.5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
            "filter": "blur(8px)",
            "transform": "translateX(30px)",
        }
    },
    "keyframes": {
        "blur-slide-in": [
            {"offset": 0, "opacity": 0, "filter": "blur(8px)", "transform": "translateX(30px)"},
            {"offset": 0.6, "opacity": 1, "filter": "blur(0)", "transform": "translateX(0)"},
            {"offset": 1, "opacity": 1, "filter": "blur(0)", "transform": "translateX(0)"},
        ]
    }
})

_register("brace-expand", {
    "description": "花括号从两侧展开，中间文字随后弹出，代码块宣言式标题",
    "duration_frames": 60,
    "css": {
        ".brace-left": {
            "animation": "brace-open-l 2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".brace-right": {
            "animation": "brace-open-r 2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".brace-text": {
            "animation": "brace-pop 2s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "brace-open-l": [
            {"offset": 0, "opacity": 0, "transform": "translateX(60px) scaleX(0.3)"},
            {"offset": 0.4, "opacity": 1, "transform": "translateX(0) scaleX(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "brace-open-r": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-60px) scaleX(0.3)"},
            {"offset": 0.4, "opacity": 1, "transform": "translateX(0) scaleX(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "brace-pop": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.6)"},
            {"offset": 0.55, "opacity": 0},
            {"offset": 0.8, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("countdown-arc-scatter", {
    "description": "表盘数字沿弧线扫过减速急停，5停在弧顶平移成标题首字符，其余数字blur散去",
    "duration_frames": 33,
    "css": {
        ".dial-number": {
            "animation": "cas-dial 1.1s cubic-bezier(0.22, 1, 0.36, 1) forwards",
            "opacity": 0,
        },
        ".dial-number-leave": {
            "animation": "cas-leave 1.1s ease-in forwards",
            "opacity": 1,
        },
        ".dial-title": {
            "animation": "cas-title 1.1s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "cas-dial": [
            {"offset": 0, "opacity": 0, "transform": "rotate(-96deg) translateX(150px) rotate(96deg)"},
            {"offset": 0.3, "opacity": 1},
            {"offset": 0.55, "transform": "rotate(0deg) translateX(150px) rotate(0deg)"},
            {"offset": 1, "opacity": 1},
        ],
        "cas-leave": [
            {"offset": 0, "opacity": 1, "filter": "blur(0)"},
            {"offset": 1, "opacity": 0, "filter": "blur(4px)"},
        ],
        "cas-title": [
            {"offset": 0, "opacity": 0, "filter": "blur(6px)"},
            {"offset": 1, "opacity": 1, "filter": "blur(0)"},
        ],
    }
})

_register("flying-words", {
    "description": "文字从远处快速飞来逐个落位，伴随拖尾模糊，像信使抵达",
    "duration_frames": 90,
    "css": {
        ".fly-word": {
            "animation": "fw-in 3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
            "transform": "translateX(-200px) scale(1.6)",
            "filter": "blur(6px)",
        }
    },
    "keyframes": {
        "fw-in": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-200px) scale(1.6)", "filter": "blur(6px)"},
            {"offset": 0.7, "opacity": 1, "transform": "translateX(0) scale(1)", "filter": "blur(0)"},
            {"offset": 0.85, "transform": "scale(1.05)"},
            {"offset": 1, "transform": "scale(1)"},
        ]
    }
})

_register("glitch-cycle", {
    "description": "等宽槽位循环轮播状态短语，头尾全乱码熔断，切换瞬间RGB分离+位移",
    "duration_frames": 168,
    "css": {
        ".glitch-slot": {
            "animation": "gc-cycle 5.6s steps(1) forwards",
        },
        ".glitch-char": {
            "animation": "gc-char 0.12s steps(2) infinite",
        },
        ".glitch-rgb": {
            "animation": "gc-rgb 5.6s ease-in-out forwards",
        }
    },
    "keyframes": {
        "gc-cycle": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.25, "opacity": 1},
            {"offset": 0.26, "opacity": 0.8},
            {"offset": 0.5, "opacity": 1},
            {"offset": 0.51, "opacity": 0.8},
            {"offset": 0.75, "opacity": 1},
            {"offset": 0.76, "opacity": 0.8},
            {"offset": 1, "opacity": 1},
        ],
        "gc-char": [
            {"offset": 0, "opacity": 1, "transform": "translateX(0)"},
            {"offset": 0.5, "opacity": 0.2, "transform": "translateX(-2px)"},
            {"offset": 1, "opacity": 1, "transform": "translateX(1px)"},
        ],
        "gc-rgb": [
            {"offset": 0, "text-shadow": "2px 0 0 rgba(255,0,80,.6), -2px 0 0 rgba(0,212,255,.6)"},
            {"offset": 0.25, "text-shadow": "none"},
            {"offset": 0.26, "text-shadow": "2px 0 0 rgba(255,0,80,.6), -2px 0 0 rgba(0,212,255,.6)"},
            {"offset": 0.5, "text-shadow": "none"},
            {"offset": 1, "text-shadow": "none"},
        ],
    }
})

_register("outline-word-fill", {
    "description": "空心词从3.2倍收缩落位，虚线圆收到字周围，描边增亮后瞬间实心点亮",
    "duration_frames": 75,
    "css": {
        ".outline-word": {
            "animation": "owf-shrink 2.5s cubic-bezier(0.22, 1, 0.36, 1) forwards",
            "color": "transparent",
            "-webkit-text-stroke": "1px #565b63",
            "transform": "scale(3.2)",
        },
        ".outline-dashed": {
            "animation": "owf-ring 2.5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".outline-fill": {
            "animation": "owf-fill 2.5s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "owf-shrink": [
            {"offset": 0, "transform": "scale(3.2)", "opacity": 0.4},
            {"offset": 0.19, "transform": "scale(1)", "opacity": 1, "-webkit-text-stroke": "1px #565b63"},
            {"offset": 0.95, "-webkit-text-stroke": "1.5px #8a9099"},
            {"offset": 1, "transform": "scale(1)", "color": "#ffffff", "-webkit-text-stroke": "0"},
        ],
        "owf-ring": [
            {"offset": 0, "opacity": 0, "transform": "scale(2.8)", "border-style": "dashed"},
            {"offset": 0.5, "opacity": 0.5, "transform": "scale(1.2)"},
            {"offset": 1, "opacity": 0, "transform": "scale(1)"},
        ],
        "owf-fill": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.9, "opacity": 0},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("scramble", {
    "description": "等宽整行字符高速跳乱码，再从左到右逐个锁定为真字，锁定瞬间高光闪",
    "duration_frames": 96,
    "css": {
        ".scramble-line": {
            "animation": "scr-lock 3.2s ease-out forwards",
            "font-family": "monospace",
        },
        ".scramble-char": {
            "animation": "scr-jump 0.1s steps(2) infinite",
        },
        ".scramble-locked": {
            "animation": "scr-flash 3.2s ease-out forwards",
        }
    },
    "keyframes": {
        "scr-lock": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.85, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        "scr-jump": [
            {"offset": 0, "opacity": 1, "color": "#8a9099"},
            {"offset": 0.5, "opacity": 0.6, "color": "#c8cdd4"},
            {"offset": 1, "opacity": 1, "color": "#8a9099"},
        ],
        "scr-flash": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.85, "opacity": 0, "color": "#fff"},
            {"offset": 1, "opacity": 1, "color": "#fff"},
        ],
    }
})

_register("text-column-converge", {
    "description": "双词对峙合拢——左右关键词硬切轮换，最后一词滑到居中咬合成短语",
    "duration_frames": 165,
    "css": {
        ".col-left": {
            "animation": "tcc-left 5.5s ease-out forwards",
        },
        ".col-right": {
            "animation": "tcc-right 5.5s ease-out forwards",
        },
        ".col-converged": {
            "animation": "tcc-converge 5.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "tcc-left": [
            {"offset": 0, "transform": "translateX(-80px)"},
            {"offset": 0.8, "transform": "translateX(-80px)"},
            {"offset": 1, "transform": "translateX(0)"},
        ],
        "tcc-right": [
            {"offset": 0, "transform": "translateX(80px)"},
            {"offset": 0.8, "transform": "translateX(80px)"},
            {"offset": 1, "transform": "translateX(0)"},
        ],
        "tcc-converge": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.8, "opacity": 0},
            {"offset": 1, "opacity": 1, "transform": "scale(1)"},
        ],
    }
})

_register("vertical-word-roll-blur-cycle", {
    "description": "句尾词竖向滚轮换词，相邻行垂直blur与灰度，中心词落定染强调色",
    "duration_frames": 150,
    "css": {
        ".roll-item": {
            "animation": "vwrb-roll 5s cubic-bezier(0.22, 1, 0.36, 1) forwards",
        },
        ".roll-blur-top": {
            "animation": "vwrb-blur 5s ease-out forwards",
            "filter": "blur(2px) grayscale(1)",
            "opacity": 0.6,
        },
        ".roll-blur-bottom": {
            "animation": "vwrb-blur-b 5s ease-out forwards",
            "filter": "blur(2px) grayscale(1)",
            "opacity": 0.6,
        },
        ".roll-active": {
            "animation": "vwrb-active 5s ease-out forwards",
        }
    },
    "keyframes": {
        "vwrb-roll": [
            {"offset": 0, "transform": "translateY(0)", "opacity": 1},
            {"offset": 0.3, "transform": "translateY(-120%)", "opacity": 0},
            {"offset": 0.35, "transform": "translateY(120%)", "opacity": 0},
            {"offset": 0.65, "transform": "translateY(0)", "opacity": 1},
            {"offset": 1, "transform": "translateY(0)", "opacity": 1},
        ],
        "vwrb-blur": [
            {"offset": 0, "filter": "blur(0) grayscale(0)", "opacity": 1},
            {"offset": 0.35, "filter": "blur(2px) grayscale(1)", "opacity": 0.6},
            {"offset": 1, "filter": "blur(2px) grayscale(1)", "opacity": 0.6},
        ],
        "vwrb-blur-b": [
            {"offset": 0, "filter": "blur(2px) grayscale(1)", "opacity": 0.6},
            {"offset": 0.65, "filter": "blur(0) grayscale(0)", "opacity": 1},
            {"offset": 1, "filter": "blur(2px) grayscale(1)", "opacity": 0.6},
        ],
        "vwrb-active": [
            {"offset": 0, "color": "inherit"},
            {"offset": 0.65, "color": "inherit"},
            {"offset": 0.8, "color": "#ff6b35"},
            {"offset": 1, "color": "#ff6b35"},
        ],
    }
})

import sys as _sys_typo
if __name__ == "__main__":
    print(f"shotcraft_typography_v2 registered: {len(SHOT_CARD_REGISTRY)} shots", file=_sys_typo.stderr)
