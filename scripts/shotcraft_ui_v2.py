#!/usr/bin/env python3
"""
shotcraft_ui_v2.py — video-shotcraft 新增 UI 类镜头卡

来源：https://github.com/Vincentwei1021/video-shotcraft (5.3k star)
将 ui-entrance 类别新增镜头卡翻译为 HTML+CSS 动画。
"""

import math
import random

SHOT_CARD_REGISTRY = {}

def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta

# ── UI Entrance Moves ─────────────────────

_register("chip-lift-to-user-pill", {
    "description": "功能chip从列表升起滑向用户头像，变成对话pill，像把功能递给用户",
    "duration_frames": 90,
    "css": {
        ".chip-source": {
            "animation": "clup-chip 3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        },
        ".chip-user": {
            "animation": "clup-user 3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "clup-chip": [
            {"offset": 0, "transform": "translate(0, 0) scale(1)", "opacity": 1},
            {"offset": 0.6, "transform": "translate(60%, -40%) scale(0.7)", "opacity": 0.8},
            {"offset": 0.65, "transform": "translate(60%, -40%) scale(0.6)", "opacity": 0},
            {"offset": 1, "opacity": 0},
        ],
        "clup-user": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.65, "opacity": 0},
            {"offset": 0.8, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("dashboard-glow-highlight-pill", {
    "description": "仪表盘卡片逐个发光高亮，高亮pill标记重点指标，其余压暗",
    "duration_frames": 75,
    "css": {
        ".dash-card": {
            "animation": "dghp-card 2.5s ease-in-out forwards",
        },
        ".dash-card-dim": {
            "animation": "dghp-dim 2.5s ease-in-out forwards",
            "opacity": 1,
        },
        ".dash-highlight": {
            "animation": "dghp-glow 2.5s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "dghp-card": [
            {"offset": 0, "opacity": 1, "filter": "brightness(1)"},
            {"offset": 0.5, "opacity": 1, "filter": "brightness(1.35)", "box-shadow": "0 0 20px rgba(255,180,0,.5)"},
            {"offset": 1, "opacity": 1, "filter": "brightness(1.2)"},
        ],
        "dghp-dim": [
            {"offset": 0, "opacity": 1, "filter": "brightness(1)"},
            {"offset": 0.5, "opacity": 0.35, "filter": "brightness(0.6)"},
            {"offset": 1, "opacity": 0.35, "filter": "brightness(0.6)"},
        ],
        "dghp-glow": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.5, "opacity": 0},
            {"offset": 0.75, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("floating-glossy-label-pills", {
    "description": "玻璃质感标签pill从两侧缓慢浮动入场，柔和悬浮呼吸",
    "duration_frames": 90,
    "css": {
        ".glossy-pill": {
            "animation": "fglp-in 3s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
            "backdrop-filter": "blur(12px)",
            "background": "rgba(255,255,255,.12)",
        },
        ".glossy-pill-float": {
            "animation": "fglp-float 4s ease-in-out infinite",
        }
    },
    "keyframes": {
        "fglp-in": [
            {"offset": 0, "opacity": 0, "transform": "translateY(30px)"},
            {"offset": 0.6, "opacity": 1, "transform": "translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "fglp-float": [
            {"offset": 0, "transform": "translateY(0)"},
            {"offset": 0.5, "transform": "translateY(-12px)"},
            {"offset": 1, "transform": "translateY(0)"},
        ],
    }
})

_register("glass-pill-dictation-typing", {
    "description": "玻璃pill内逐字打字输入，光标闪烁，语音识别感",
    "duration_frames": 100,
    "css": {
        ".glass-input": {
            "animation": "gpdt-field 3.3s ease-in-out forwards",
        },
        ".glass-cursor": {
            "animation": "gpdt-cursor 0.7s steps(2) infinite",
        },
        ".glass-text": {
            "animation": "gpdt-type 3.3s steps(20) forwards",
            "white-space": "nowrap",
            "overflow": "hidden",
            "width": "0",
        }
    },
    "keyframes": {
        "gpdt-field": [
            {"offset": 0, "border-color": "rgba(255,255,255,.2)", "background": "rgba(255,255,255,.08)"},
            {"offset": 0.3, "border-color": "rgba(0,212,255,.5)", "background": "rgba(255,255,255,.14)"},
            {"offset": 1, "border-color": "rgba(0,212,255,.3)"},
        ],
        "gpdt-cursor": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.5, "opacity": 0},
            {"offset": 1, "opacity": 1},
        ],
        "gpdt-type": [
            {"offset": 0, "width": "0"},
            {"offset": 1, "width": "100%"},
        ],
    }
})

_register("list-reveal", {
    "description": "列表项依次滑入逐条点亮，每项带微小旋转归位",
    "duration_frames": 90,
    "css": {
        ".list-item": {
            "animation": "lr-item 3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
            "transform": "translateX(-40px) rotate(-2deg)",
        }
    },
    "keyframes": {
        "lr-item": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-40px) rotate(-2deg)"},
            {"offset": 0.7, "opacity": 1, "transform": "translateX(0) rotate(0deg)"},
            {"offset": 0.85, "transform": "scale(1.02)"},
            {"offset": 1, "transform": "scale(1)"},
        ]
    }
})

_register("picker-carousel-feature-cycle", {
    "description": "选择器轮播：中间高亮特征，两侧缩小模糊，像滚筒选择器滚动",
    "duration_frames": 100,
    "css": {
        ".picker-center": {
            "animation": "pcfc-center 3.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        },
        ".picker-side": {
            "animation": "pcfc-side 3.3s ease-in-out forwards",
            "opacity": 0.5,
            "filter": "blur(1px)",
        },
        ".picker-old": {
            "animation": "pcfc-old 3.3s ease-out forwards",
            "opacity": 1,
        }
    },
    "keyframes": {
        "pcfc-center": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.7) translateY(20px)", "filter": "blur(2px)"},
            {"offset": 0.5, "opacity": 1, "transform": "scale(1) translateY(0)", "filter": "blur(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "pcfc-side": [
            {"offset": 0, "opacity": 0.5, "transform": "scale(0.8)", "filter": "blur(1px)"},
            {"offset": 1, "opacity": 0.5, "transform": "scale(0.8)", "filter": "blur(1px)"},
        ],
        "pcfc-old": [
            {"offset": 0, "opacity": 1, "transform": "scale(1)", "filter": "blur(0)"},
            {"offset": 0.5, "opacity": 0, "transform": "scale(0.7) translateY(-30px)", "filter": "blur(2px)"},
            {"offset": 1, "opacity": 0},
        ],
    }
})

_register("product-card-progressive-assemble", {
    "description": "详情卡逐字段自建：图→标题→价格→正文逐行揭示，原价划线新价spring跳出",
    "duration_frames": 150,
    "css": {
        ".pc-image": {
            "animation": "pcpa-img 5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".pc-title": {
            "animation": "pcpa-title 5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".pc-price-old": {
            "animation": "pcpa-old 5s ease-out forwards",
            "opacity": 0,
        },
        ".pc-price-new": {
            "animation": "pcpa-new 5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".pc-body": {
            "animation": "pcpa-body 5s ease-out forwards",
            "opacity": 0,
        },
        ".pc-card": {
            "animation": "pcpa-push 5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
        }
    },
    "keyframes": {
        "pcpa-img": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.8)"},
            {"offset": 0.15, "opacity": 1, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "pcpa-title": [
            {"offset": 0, "opacity": 0, "transform": "translateY(20px)"},
            {"offset": 0.3, "opacity": 1, "transform": "translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "pcpa-old": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.45, "opacity": 1},
            {"offset": 0.5, "opacity": 0.6, "text-decoration": "line-through"},
            {"offset": 1, "opacity": 0.6, "text-decoration": "line-through"},
        ],
        "pcpa-new": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.6)"},
            {"offset": 0.5, "opacity": 0},
            {"offset": 0.62, "opacity": 1, "transform": "scale(1.3)"},
            {"offset": 0.75, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "pcpa-body": [
            {"offset": 0, "opacity": 0, "transform": "translateY(10px)"},
            {"offset": 0.7, "opacity": 0},
            {"offset": 0.85, "opacity": 1, "transform": "translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "pcpa-push": [
            {"offset": 0, "transform": "scale(1)"},
            {"offset": 1, "transform": "scale(1.06)"},
        ],
    }
})

_register("radial-ripple-phone-chips", {
    "description": "四层同心圆错相呼吸如水波，中央手机屏内feed缓滚，两侧chip spring入场",
    "duration_frames": 168,
    "css": {
        ".ripple-ring-1": {
            "animation": "rrpc-ring1 5.6s ease-in-out infinite",
        },
        ".ripple-ring-2": {
            "animation": "rrpc-ring2 5.6s ease-in-out infinite",
        },
        ".ripple-phone": {
            "animation": "rrpc-phone 5.6s ease-out forwards",
            "opacity": 0,
        },
        ".ripple-chip": {
            "animation": "rrpc-chip 5.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "rrpc-ring1": [
            {"offset": 0, "transform": "scale(1)", "opacity": 0.4},
            {"offset": 0.5, "transform": "scale(1.15)", "opacity": 0.2},
            {"offset": 1, "transform": "scale(1)", "opacity": 0.4},
        ],
        "rrpc-ring2": [
            {"offset": 0, "transform": "scale(1.15)", "opacity": 0.2},
            {"offset": 0.5, "transform": "scale(1)", "opacity": 0.4},
            {"offset": 1, "transform": "scale(1.15)", "opacity": 0.2},
        ],
        "rrpc-phone": [
            {"offset": 0, "opacity": 0, "transform": "translateY(30px)"},
            {"offset": 0.3, "opacity": 1, "transform": "translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "rrpc-chip": [
            {"offset": 0, "opacity": 0, "transform": "translateX(-40px) scale(0.8)"},
            {"offset": 0.4, "opacity": 0},
            {"offset": 0.55, "opacity": 1, "transform": "translateX(0) scale(1.15)"},
            {"offset": 0.7, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
    }
})

_register("radial-wave", {
    "description": "17x9圆点阵列按欧氏距离错峰点亮，每点scale过冲到1.5再落回常亮，第二道蓝脉冲反向收拢",
    "duration_frames": 114,
    "css": {
        ".wave-dot": {
            "animation": "rw-dot 3.8s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".wave-dot-blue": {
            "animation": "rw-blue 3.8s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "rw-dot": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.3)"},
            {"offset": 0.4, "opacity": 1, "transform": "scale(1.5)"},
            {"offset": 0.6, "transform": "scale(1)"},
            {"offset": 1, "opacity": 1},
        ],
        "rw-blue": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.6, "opacity": 0},
            {"offset": 0.75, "opacity": 1, "transform": "scale(1.3)", "background": "#00a8ff"},
            {"offset": 1, "opacity": 0.6},
        ],
    }
})

_register("scan-bracket-sweep", {
    "description": "骨架文档弹到中央，四角L形取景括号落下，扫描线在文档上往复扫5趟",
    "duration_frames": 150,
    "css": {
        ".scan-doc": {
            "animation": "sbs-doc 5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        },
        ".scan-bracket": {
            "animation": "sbs-bracket 5s cubic-bezier(0.4, 0, 0.2, 1) forwards",
            "opacity": 0,
        },
        ".scan-line": {
            "animation": "sbs-scan 5s linear forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "sbs-doc": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.9) translateY(20px)"},
            {"offset": 0.1, "opacity": 1, "transform": "scale(1) translateY(0)"},
            {"offset": 1, "opacity": 1},
        ],
        "sbs-bracket": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.15, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        "sbs-scan": [
            {"offset": 0, "opacity": 0.8, "top": "0%"},
            {"offset": 0.2, "opacity": 0.8, "top": "100%"},
            {"offset": 0.4, "opacity": 0.8, "top": "0%"},
            {"offset": 0.6, "opacity": 0.8, "top": "100%"},
            {"offset": 0.8, "opacity": 0.8, "top": "0%"},
            {"offset": 1, "opacity": 0, "top": "100%"},
        ],
    }
})

import sys as _sys_ui
if __name__ == "__main__":
    print(f"shotcraft_ui_v2 registered: {len(SHOT_CARD_REGISTRY)} shots", file=_sys_ui.stderr)
