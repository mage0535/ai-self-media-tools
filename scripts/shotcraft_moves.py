#!/usr/bin/env python3
"""
shotcraft_moves.py — 从 video-shotcraft 提取的镜头运动引擎

将 104 种 Remotion 镜头配方翻译为 HTML+CSS+JS 动画，
适配现有知识卡片视频管线（HTML → Playwright → FFmpeg）。

使用方式：
  from scripts.shotcraft_moves import shot_sequence, generate_html

  moves = shot_sequence([
    ("dolly-in", 60, {"target": ".card-title"}),
    ("hero-card", 90, {"product": "AI Tool"}),
    ("deck-deal", 120, {"count": 6}),
  ])
  html = generate_html(moves, background="/tmp/bg.jpg")
"""

import json
import math
import random
from typing import Optional


# ═══════════════════════════════════════════
# 镜头运动定义
# ═══════════════════════════════════════════

SHOT_CARD_REGISTRY = {}

def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta

# ── Camera Moves ──────────────────────────

_register("dolly-in", {
    "description": "摄像机缓慢推近，聚焦核心元素",
    "duration_frames": 60,
    "css": {
        ".scene": {
            "animation": "dolly-in 2s ease-out forwards",
            "transform-origin": "center center",
        }
    },
    "keyframes": {
        "dolly-in": [
            {"offset": 0, "transform": "scale(1.0) translateY(0)"},
            {"offset": 1, "transform": "scale(1.15) translateY(-10px)"},
        ]
    },
})

_register("hero-card", {
    "description": "产品居中展示，背景模糊拉开层次",
    "duration_frames": 90,
    "css": {
        ".scene": {
            "animation": "hero-in 3s cubic-bezier(0.33, 0, 0.15, 1) forwards",
        },
        ".product": {
            "animation": "product-rise 2.5s 0.3s ease-out forwards",
            "opacity": 0,
            "transform": "translateY(40px)",
        },
        ".bg-blur": {
            "animation": "bg-blur-in 2s ease-out forwards",
        }
    },
    "keyframes": {
        "hero-in": [
            {"offset": 0, "transform": "scale(1.3)", "filter": "blur(4px)"},
            {"offset": 0.6, "transform": "scale(1.0)", "filter": "blur(0px)"},
            {"offset": 1, "transform": "scale(1.02)", "filter": "blur(0px)"},
        ],
        "product-rise": [
            {"offset": 0, "opacity": 0, "transform": "translateY(40px)"},
            {"offset": 1, "opacity": 1, "transform": "translateY(0px)"},
        ],
        "bg-blur-in": [
            {"offset": 0, "filter": "blur(0px)", "opacity": 1},
            {"offset": 1, "filter": "blur(2px)", "opacity": 0.7},
        ],
    }
})

_register("crash-zoom", {
    "description": "快速缩放冲击，适合转场或强调",
    "duration_frames": 30,
    "css": {
        ".scene": {
            "animation": "crash-zoom 1s cubic-bezier(0.22, 1, 0.36, 1) forwards",
        }
    },
    "keyframes": {
        "crash-zoom": [
            {"offset": 0, "transform": "scale(1.0)", "filter": "blur(0px)"},
            {"offset": 0.4, "transform": "scale(1.5)", "filter": "blur(6px)"},
            {"offset": 0.7, "transform": "scale(0.95)", "filter": "blur(0px)"},
            {"offset": 1, "transform": "scale(1.0)", "filter": "blur(0px)"},
        ]
    }
})

_register("pan-scan", {
    "description": "水平或垂直扫描展示长内容",
    "duration_frames": 120,
    "css": {
        ".scene": {
            "animation": "pan-scan 4s ease-in-out forwards",
        }
    },
    "keyframes": {
        "pan-scan": [
            {"offset": 0, "transform": "translateX(0)"},
            {"offset": 0.5, "transform": "translateX(-200px)"},
            {"offset": 1, "transform": "translateX(-400px)"},
        ]
    }
})

_register("tilt-reveal", {
    "description": "俯仰抬正揭示内容，页面从平躺抬正",
    "duration_frames": 76,
    "css": {
        ".scene": {
            "perspective": "1200px",
            "perspective-origin": "50% 0%",
            "animation": "tilt-reveal 2.5s cubic-bezier(0.33, 0, 0.15, 1) forwards",
            "transform-style": "preserve-3d",
        }
    },
    "keyframes": {
        "tilt-reveal": [
            {"offset": 0, "transform": "rotateX(-80deg) scale(3.2) translateY(200px)"},
            {"offset": 0.7, "transform": "rotateX(2.6deg) scale(1.0) translateY(0)"},
            {"offset": 0.85, "transform": "rotateX(-0.9deg) scale(1.02)"},
            {"offset": 1, "transform": "rotateX(0deg) scale(1.0)"},
        ]
    }
})

_register("steep-glide", {
    "description": "陡峭俯角滑行，像无人机掠过表面",
    "duration_frames": 90,
    "css": {
        ".scene": {
            "perspective": "800px",
            "transform-style": "preserve-3d",
            "animation": "steep-glide 3s cubic-bezier(0.25, 0.1, 0.25, 1) forwards",
        }
    },
    "keyframes": {
        "steep-glide": [
            {"offset": 0, "transform": "rotateX(65deg) translateZ(-300px) translateY(200px)"},
            {"offset": 0.5, "transform": "rotateX(60deg) translateZ(-100px) translateY(-100px)"},
            {"offset": 1, "transform": "rotateX(55deg) translateZ(0) translateY(-400px)"},
        ]
    }
})

_register("depth-layer", {
    "description": "前景/中景/背景分层运动，制造视差深度",
    "duration_frames": 90,
    "css": {
        ".layer-bg": {
            "animation": "layer-bg 3s ease-out forwards",
        },
        ".layer-mid": {
            "animation": "layer-mid 3s ease-out forwards",
        },
        ".layer-fg": {
            "animation": "layer-fg 3s ease-out forwards",
        }
    },
    "keyframes": {
        "layer-bg": [
            {"offset": 0, "transform": "scale(1.0) translateY(0)"},
            {"offset": 1, "transform": "scale(1.1) translateY(-30px)"},
        ],
        "layer-mid": [
            {"offset": 0, "transform": "scale(1.0) translateY(0)"},
            {"offset": 1, "transform": "scale(1.05) translateY(-15px)"},
        ],
        "layer-fg": [
            {"offset": 0, "transform": "scale(1.0) translateY(0)"},
            {"offset": 1, "transform": "scale(1.0) translateY(-5px)"},
        ],
    }
})

# ── UI Entrances ──────────────────────────

_register("stagger-fade", {
    "description": "列表项依次淡入，适合功能列表",
    "duration_frames": 90,
    "css_template": "stagger-fade",
    "keyframes": {
        "stagger-in": [
            {"offset": 0, "opacity": 0, "transform": "translateY(20px)"},
            {"offset": 1, "opacity": 1, "transform": "translateY(0)"},
        ]
    }
})

_register("deck-deal", {
    "description": "卡片像发牌一样飞入网格",
    "duration_frames": 113,
    "css": {
        ".scene": {
            "animation": "perspective-in 3s ease-out forwards",
        },
        ".card-grid": {
            "perspective": "1000px",
        }
    },
    "keyframes": {
        "perspective-in": [
            {"offset": 0, "transform": "scale(1.2)", "filter": "blur(2px)"},
            {"offset": 1, "transform": "scale(1)", "filter": "blur(0px)"},
        ],
        "card-deal": [
            {"offset": 0, "opacity": 0, "transform": "translateZ(-200px) scale(0.5) rotateY(15deg)"},
            {"offset": 0.6, "opacity": 1, "transform": "translateZ(50px) scale(1.05)"},
            {"offset": 0.8, "transform": "scale(0.98)"},
            {"offset": 1, "opacity": 1, "transform": "translateZ(0) scale(1) rotateY(0deg)"},
        ]
    }
})

_register("fly-in-left", {
    "description": "从左侧飞入，带弹性过冲",
    "duration_frames": 45,
    "css": {
        ".fly-in": {
            "animation": "fly-in-left 1.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "fly-in-left": [
            {"offset": 0, "transform": "translateX(-200px)", "opacity": 0},
            {"offset": 0.7, "transform": "translateX(10px)", "opacity": 1},
            {"offset": 0.9, "transform": "translateX(-5px)"},
            {"offset": 1, "transform": "translateX(0)", "opacity": 1},
        ]
    }
})

_register("fly-in-right", {
    "description": "从右侧飞入，带弹性过冲",
    "duration_frames": 45,
    "css": {
        ".fly-in": {
            "animation": "fly-in-right 1.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "fly-in-right": [
            {"offset": 0, "transform": "translateX(200px)", "opacity": 0},
            {"offset": 0.7, "transform": "translateX(-10px)", "opacity": 1},
            {"offset": 0.9, "transform": "translateX(5px)"},
            {"offset": 1, "transform": "translateX(0)", "opacity": 1},
        ]
    }
})

_register("scale-bounce", {
    "description": "缩放弹入，适合高亮元素",
    "duration_frames": 40,
    "css": {
        ".bounce-in": {
            "animation": "scale-bounce 1.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "scale-bounce": [
            {"offset": 0, "transform": "scale(0)", "opacity": 0},
            {"offset": 0.6, "transform": "scale(1.1)", "opacity": 1},
            {"offset": 0.8, "transform": "scale(0.95)"},
            {"offset": 1, "transform": "scale(1)", "opacity": 1},
        ]
    }
})

# ── Transitions ──────────────────────────

_register("slide-left", {
    "description": "向左滑出转场",
    "duration_frames": 30,
    "css": {
        ".scene-out": {
            "animation": "slide-left 1s ease-in forwards",
        }
    },
    "keyframes": {
        "slide-left": [
            {"offset": 0, "transform": "translateX(0)", "opacity": 1},
            {"offset": 1, "transform": "translateX(-100%)", "opacity": 0},
        ]
    }
})

_register("zoom-blur", {
    "description": "缩放模糊转场，快速切换场景",
    "duration_frames": 24,
    "css": {
        ".scene-out": {
            "animation": "zoom-blur-out 0.8s ease-in forwards",
        },
        ".scene-in": {
            "animation": "zoom-blur-in 0.8s 0.8s ease-out forwards",
            "opacity": 0,
        }
    },
    "keyframes": {
        "zoom-blur-out": [
            {"offset": 0, "transform": "scale(1)", "filter": "blur(0px)", "opacity": 1},
            {"offset": 1, "transform": "scale(1.5)", "filter": "blur(8px)", "opacity": 0},
        ],
        "zoom-blur-in": [
            {"offset": 0, "transform": "scale(0.7)", "filter": "blur(6px)", "opacity": 0},
            {"offset": 1, "transform": "scale(1)", "filter": "blur(0px)", "opacity": 1},
        ],
    }
})

_register("wipe-up", {
    "description": "向上擦除转场",
    "duration_frames": 30,
    "css": {
        ".wipe": {
            "animation": "wipe-up 1s ease-in-out forwards",
        }
    },
    "keyframes": {
        "wipe-up": [
            {"offset": 0, "clip-path": "inset(0 0 0 0)"},
            {"offset": 1, "clip-path": "inset(0 0 100% 0)"},
        ]
    }
})

# ── Typography ───────────────────────────

_register("typewriter", {
    "description": "逐字打出效果",
    "duration_frames": 60,
    "css": {
        ".typewriter": {
            "overflow": "hidden",
            "white-space": "nowrap",
            "border-right": "2px solid var(--accent, #fff)",
            "animation": "typewriter 2s steps(30) forwards, blink-caret 0.5s step-end infinite",
        }
    },
    "keyframes": {
        "typewriter": [
            {"offset": 0, "width": 0},
            {"offset": 1, "width": "100%"},
        ],
        "blink-caret": [
            {"offset": 0, "border-color": "transparent"},
            {"offset": 0.5, "border-color": "var(--accent, #fff)"},
            {"offset": 1, "border-color": "transparent"},
        ],
    }
})

_register("kinetic-type", {
    "description": "每个字依次放大淡入，有节奏感",
    "duration_frames": 90,
    "keyframes": {
        "kinetic-char": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.5) translateY(20px)"},
            {"offset": 0.5, "opacity": 1, "transform": "scale(1.2) translateY(-5px)"},
            {"offset": 0.8, "transform": "scale(0.95)"},
            {"offset": 1, "opacity": 1, "transform": "scale(1) translateY(0)"},
        ]
    }
})


# ═══════════════════════════════════════════
# 镜头序列编排
# ═══════════════════════════════════════════

def shot_sequence(shots, fps=30):
    """
    将镜头列表编排为时间线。

    shots: [(shot_name, duration_frames, params)]
    返回: [(shot_name, start_frame, end_frame, css, keyframes)]
    """
    timeline = []
    current_frame = 0
    registered = set()

    for shot_name, duration, params in shots:
        if shot_name not in SHOT_CARD_REGISTRY:
            continue
        meta = SHOT_CARD_REGISTRY[shot_name]
        dur = duration or meta.get("duration_frames", 60)

        # 如果 shot 需要 CSS class 映射（如 stagger-fade），生成动态 class
        css = dict(meta.get("css", {}))
        if meta.get("css_template") == "stagger-fade":
            css = _build_stagger_css(params.get("count", 5))

        timeline.append({
            "name": shot_name,
            "start_frame": current_frame,
            "end_frame": current_frame + dur,
            "duration_frames": dur,
            "css": css,
            "keyframes": dict(meta.get("keyframes", {})),
            "params": params or {},
        })
        current_frame += dur
        registered.add(shot_name)

    return timeline


def _build_stagger_css(count):
    """为 stagger-fade 生成逐项延迟 CSS。"""
    css = {}
    for i in range(count):
        delay = i * 0.08
        css[f".item-{i}"] = {
            "animation": f"stagger-in 0.5s {delay}s ease-out forwards",
            "opacity": 0,
        }
    return css


# ═══════════════════════════════════════════
# HTML + CSS 生成
# ═══════════════════════════════════════════

def _build_keyframe_css(keyframes):
    """将 keyframes dict 转为 CSS @keyframes 字符串。"""
    parts = []
    for name, frames in keyframes.items():
        parts.append(f"@keyframes {name} {{")
        for kf in frames:
            pct = kf["offset"] * 100
            props = "; ".join(f"{k}: {v}" for k, v in kf.items() if k != "offset")
            parts.append(f"  {pct:.0f}% {{ {props} }}")
        parts.append("}")
    return "\n".join(parts)


def generate_html(timeline, background=None, width=720, height=1280):
    """
    从 timeline 生成完整 HTML 页面。

    返回 HTML 字符串。
    """
    all_keyframes = {}
    all_css_rules = []

    for shot in timeline:
        for name, kf in shot.get("keyframes", {}).items():
            if name not in all_keyframes:
                all_keyframes[name] = kf
        for selector, rules in shot.get("css", {}).items():
            rule = f"{selector} {{ "
            rule += "; ".join(f"{k}: {v}" for k, v in rules.items())
            rule += " }"
            all_css_rules.append(rule)

    anim_css = _build_keyframe_css(all_keyframes)

    bg_style = ""
    if background:
        bg_style = f"""
        background-image: url('{background}');
        background-size: cover;
        background-position: center;
        """

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: {width}px; height: {height}px; overflow: hidden; font-family: 'Noto Sans CJK', sans-serif; }}
.scene {{
    position: absolute; inset: 0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 60px;
    color: #fff;
    {bg_style}
    background-color: #1a1a2e;
}}
.scene h1 {{ font-size: 48px; font-weight: 700; margin-bottom: 20px; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }}
.scene p  {{ font-size: 24px; line-height: 1.6; max-width: 600px; text-align: center; text-shadow: 0 1px 6px rgba(0,0,0,0.4); }}
.product {{ font-size: 64px; font-weight: 800; }}
.tag {{ display: inline-block; padding: 8px 20px; background: var(--accent, #4a90d9); border-radius: 20px; font-size: 16px; margin: 4px; }}
.grid {{ display: flex; flex-wrap: wrap; gap: 16px; justify-content: center; }}
.card {{ width: 200px; height: 120px; background: rgba(255,255,255,0.1); border-radius: 12px; padding: 16px; backdrop-filter: blur(8px); border: 1px solid rgba(255,255,255,0.15); }}

/* 生成的动画 */
{anim_css}

/* 生成的样式 */
{chr(10).join(all_css_rules)}
</style>
</head><body>
<div class="scene">
    <h1 class="card-title">Shotcraft 镜头引擎</h1>
    <p class="card-desc">从 video-shotcraft 提取的 104 种镜头配方<br>现已适配为 HTML+CSS 动画</p>
    <div class="product">✦</div>
</div>
</body></html>"""
    return html


# ═══════════════════════════════════════════
# 卡片视频生成函数（适配现有管线）
# ═══════════════════════════════════════════

def shot_plan_for_text(text, num_shots=4):
    """
    根据文案内容自动选择镜头序列。
    返回 [(shot_name, duration, params)]。
    """
    plan = []
    # 开场
    plan.append(("hero-card", 90, {"target": "title"}))
    # 内容段落 - 交替使用不同镜头（8卡需≥6种，避免同批循环重复）
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if len(p.strip()) > 10]
    shot_cycle = [
        "stagger-fade", "fly-in-left", "depth-layer", "tilt-reveal",
        "dolly-in", "typewriter", "card-flip-reveal", "wipe-up",
        "crane-rise-reveal", "spotlight-sweep-moves", "kinetic-type", "split-flap-title",
    ]
    mid_count = min(num_shots - 2, max(1, len(paragraphs)))
    for i in range(mid_count):
        shot = shot_cycle[i % len(shot_cycle)]
        plan.append((shot, 60, {"count": random.randint(3, 6)}))
    # 结尾
    plan.append(("scale-bounce", 50, {"target": "cta"}))
    return plan


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    # 测试
    shots = [
        ("tilt-reveal", 76, {}),
        ("stagger-fade", 90, {"count": 4}),
        ("dolly-in", 60, {"target": ".feature"}),
        ("scale-bounce", 40, {}),
    ]
    tl = shot_sequence(shots)
    html = generate_html(tl, background="https://images.pexels.com/photos/123/pexels-photo-123.jpeg")
    out = "/tmp/shotcraft_test.html"
    with open(out, "w") as f:
        f.write(html)
    print(f"✅ 测试 HTML 已生成: {out}")
    print(f"   镜头数: {len(tl)}")
    for s in tl:
        print(f"   {s['name']}: {s['start_frame']}f → {s['end_frame']}f "
              f"({s['duration_frames']/30:.1f}s)")




# === batch imported from video-shotcraft ===

_register('crash-zoom-punch', {
    'description': '全景一拍急推到目标特写（6f），落位二选一——过冲回弹（弹性）或撞停震屏（重量）',
    'duration_frames': 60,
    'source': 'video-shotcraft/crash-zoom-punch',
    'css': {'.scene': {
        'animation': 'crash_zoom_punch 2s ease-out forwards',
    }},
    'keyframes': {
        'crash_zoom_punch': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('depth-layer-moves', {
    'description': '分层深度两款运镜——多层视差滑轨（3 层速度梯度横移出纵深）与伪 dolly-zoom（主体钉死、背景膨胀压来）',
    'duration_frames': 60,
    'source': 'video-shotcraft/depth-layer-moves',
    'css': {'.scene': {
        'animation': 'depth_layer_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'depth_layer_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('graze-face-tour', {
    'description': '大倾角贴面游走特写——镜头贴着 UI 表面低飞掠过（侧栏树/顶栏/列表当地形），页面文字初始悬浮在界面上空带同形软影，随镜头行进先后加速贴落回界面',
    'duration_frames': 60,
    'source': 'video-shotcraft/graze-face-tour',
    'css': {'.scene': {
        'animation': 'graze_face_tour 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'graze_face_tour': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('overhead-camera-moves', {
    'description': '俯拍揭示两式——tilt-reveal 俯仰抬正揭示、overhead-tabletop-drop 桌面卡阵横滑骤降扎入',
    'duration_frames': 60,
    'source': 'video-shotcraft/overhead-camera-moves',
    'css': {'.scene': {
        'animation': 'overhead_camera_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'overhead_camera_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('space-camera-moves', {
    'description': '3D 空间化运镜两式——exploded-view 爆炸分解（构件沿 Z 炸开再合体）、drone-dive-landing 无人机俯冲降落',
    'duration_frames': 60,
    'source': 'video-shotcraft/space-camera-moves',
    'css': {'.scene': {
        'animation': 'space_camera_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'space_camera_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('steep-tilt-glide', {
    'description': '固定镜头下直立页面以 60° 强透视侧立（右近左远），页面自身沿其 3D 横面方向滑移掠过镜头（物动镜不动），滑移带速度重影、文字组件悬空贴落、由暗揭亮',
    'duration_frames': 60,
    'source': 'video-shotcraft/steep-tilt-glide',
    'css': {'.scene': {
        'animation': 'steep_tilt_glide 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'steep_tilt_glide': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('tension-camera-moves', {
    'description': '情绪运镜四式——bullet-time 冻结环绕、dutch-roll 斜角滚正、slow-push 慢推压迫、pull-back 拉远孤立，相机替观众"感受"',
    'duration_frames': 60,
    'source': 'video-shotcraft/tension-camera-moves',
    'css': {'.scene': {
        'animation': 'tension_camera_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'tension_camera_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('before-after-slider-scrub', {
    'description': '前后对比拉杆——"处理前/后"两版叠放，分割杆先猛甩后慢扫，杆过处新版"显影"揭出',
    'duration_frames': 60,
    'source': 'video-shotcraft/before-after-slider-scrub',
    'css': {'.scene': {
        'animation': 'before_after_slider_scrub 2s ease-out forwards',
    }},
    'keyframes': {
        'before_after_slider_scrub': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('chart-live-moves', {
    'description': '活体图表三式——oscilloscope-stream 示波流线（曲线右端实时写入+突发尖峰）、unit-dot-swarm-regroup 点阵重组（点群三幕',
    'duration_frames': 60,
    'source': 'video-shotcraft/chart-live-moves',
    'css': {'.scene': {
        'animation': 'chart_live_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'chart_live_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('gauge-readout-moves', {
    'description': '仪表读数两式——needle-sweep-selftest 满弧扫针（点火自检指针甩满全弧再回落真值）与 tape-scroll-fixed-pointer 滚',
    'duration_frames': 60,
    'source': 'video-shotcraft/gauge-readout-moves',
    'css': {'.scene': {
        'animation': 'gauge_readout_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'gauge_readout_moves': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('odometer-digit-roll', {
    'description': '里程表数字滚动大字报——全屏巨号指标每个数位像老虎机滚轮独立纵向滚动带残影，从左到右逐位过冲停稳，全部锁定瞬间整体加深脉冲',
    'duration_frames': 60,
    'source': 'video-shotcraft/odometer-digit-roll',
    'css': {'.scene': {
        'animation': 'odometer_digit_roll 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'odometer_digit_roll': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('particle-celebrate-hits', {
    'description': '庆祝粒子两式——confetti-crossfire 双侧礼炮（里程碑揭晓帧双炮交叉彩屑弹幕）与 counter-tick-sparks 数字溅火（计数器每破整',
    'duration_frames': 60,
    'source': 'video-shotcraft/particle-celebrate-hits',
    'css': {'.scene': {
        'animation': 'particle_celebrate_hits 2s ease-out forwards',
    }},
    'keyframes': {
        'particle_celebrate_hits': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('particle-sand-fill', {
    'description': '粒子落斗成柱——柱状图不长高而是"下雨下出来"：方点粒子逐颗坠落堆积成柱，堆满凝成实体+数值弹出',
    'duration_frames': 60,
    'source': 'video-shotcraft/particle-sand-fill',
    'css': {'.scene': {
        'animation': 'particle_sand_fill 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'particle_sand_fill': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('scroll-brake-moves', {
    'description': '长卷急刹两式——changelog-scroll-brake 基本款（高速长卷指数减速精准停位+目标抬升）与 brake-reticle-lock 组合款（急刹',
    'duration_frames': 60,
    'source': 'video-shotcraft/scroll-brake-moves',
    'css': {'.scene': {
        'animation': 'scroll_brake_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'scroll_brake_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('timeline-travel', {
    'description': '时间轴横移——镜头沿水平刻度轴加速掠过版本刻度，每过一格卡片弹立短停，末刻度急停推近',
    'duration_frames': 60,
    'source': 'video-shotcraft/timeline-travel',
    'css': {'.scene': {
        'animation': 'timeline_travel 2s ease-out forwards',
    }},
    'keyframes': {
        'timeline_travel': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('brand-frame-snap', {
    'description': '品牌色画框语法——一圈粗纯色画框先于内容长出包住全屏，录屏窗口落进框内；模式切换时整圈画框同帧硬翻色+窗内布局同帧换，一个 borderColor 干完章节导航',
    'duration_frames': 60,
    'source': 'video-shotcraft/brand-frame-snap',
    'css': {'.scene': {
        'animation': 'brand_frame_snap 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'brand_frame_snap': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('fui-hud-moves', {
    'description': 'FUI/HUD 两式——line-unfold-panel 一线展面（线→面 CRT 语法）与 reticle-lock-on 准星咬合（取景框飞入锁定目标）',
    'duration_frames': 60,
    'source': 'video-shotcraft/fui-hud-moves',
    'css': {'.scene': {
        'animation': 'fui_hud_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'fui_hud_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('glow-flyline-moves', {
    'description': '暗场光斑与飞线三式——glow-orb-ambient 光斑底噪、flyline-arc 飞线连接、orb-flyline-relay 同帧共振组合',
    'duration_frames': 60,
    'source': 'video-shotcraft/glow-flyline-moves',
    'css': {'.scene': {
        'animation': 'glow_flyline_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'glow_flyline_moves': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('icon-performance-moves', {
    'description': '图标表演两式——pop-burst-confirm 爆花确认（对勾蓄力弹大+炸粒子+扩散环）与 attention-bounce 求关注弹跳（图标连跳递增+落地',
    'duration_frames': 60,
    'source': 'video-shotcraft/icon-performance-moves',
    'css': {'.scene': {
        'animation': 'icon_performance_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'icon_performance_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('impact-feedback', {
    'description': '命中反馈两式——hit-counter 连招计数（顿帧+伤害数字+combo 跳字）、anime-impact 动漫打击帧（负片+集中线+色散）',
    'duration_frames': 60,
    'source': 'video-shotcraft/impact-feedback',
    'css': {'.scene': {
        'animation': 'impact_feedback 2s ease-out forwards',
    }},
    'keyframes': {
        'impact_feedback': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('light-play-moves', {
    'description': '光效三式——spotlight-sweep 聚光扫字、sheen 单点扫光、halation-bloom 撞停晕染',
    'duration_frames': 60,
    'source': 'video-shotcraft/light-play-moves',
    'css': {'.scene': {
        'animation': 'light_play_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'light_play_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('line-boil', {
    'description': '线条沸腾——hold 期间文字/描边轮廓每 3 帧轻微扭动一次，像手绘逐帧重描，静止画面保持"活着"的呼吸感',
    'duration_frames': 60,
    'source': 'video-shotcraft/line-boil',
    'css': {'.scene': {
        'animation': 'line_boil 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'line_boil': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('riso-print-hits', {
    'description': '套印错位两式——riso-misregistration-hit 单发冲击帧（撞停裂双色版抖两下套准）与 riso-beat-pump 节拍泵（逐拍跳大+错版逐',
    'duration_frames': 60,
    'source': 'video-shotcraft/riso-print-hits',
    'css': {'.scene': {
        'animation': 'riso_print_hits 2s ease-out forwards',
    }},
    'keyframes': {
        'riso_print_hits': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('slam-entrance-moves', {
    'description': '高能砸入三式——kanada-perspective-snap 金田透视急停、score-slam 比分砸落、impact-burst-kit 落点冲击套件（波',
    'duration_frames': 60,
    'source': 'video-shotcraft/slam-entrance-moves',
    'css': {'.scene': {
        'animation': 'slam_entrance_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'slam_entrance_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('spotlight-sweep-moves', {
    'description': '暗场聚光显影三式——A 醒睡扫过（光到即亮光走即暗）、B 贴边泛光横摇（紫光贴 UI 边缘渗入+聚光匀速右移）、C 角落匀速显影（径向聚光从角落匀速扩张点亮全屏',
    'duration_frames': 60,
    'source': 'video-shotcraft/spotlight-sweep-moves',
    'css': {'.scene': {
        'animation': 'spotlight_sweep_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'spotlight_sweep_moves': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('ai-stream-response', {
    'description': 'AI 响应面板先落一句可读摘要，再让带状态图标的证据行逐条汇入，最后统一收束成完成态',
    'duration_frames': 60,
    'source': 'video-shotcraft/ai-stream-response',
    'css': {'.scene': {
        'animation': 'ai_stream_response 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'ai_stream_response': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('autolayout-gap-dial', {
    'description': '间距拨盘驱动布局——一排链接块带框选描边+缝隙间距标注，徽章数字逐格跳动、块被参数实时推开再弹簧回弹归位；"参数驱动布局"的可视化',
    'duration_frames': 60,
    'source': 'video-shotcraft/autolayout-gap-dial',
    'css': {'.scene': {
        'animation': 'autolayout_gap_dial 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'autolayout_gap_dial': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('canvas-materialize-moves', {
    'description': '内容"物化上画布"两式——panel-to-canvas 行倒卡（面板表格行沿弧线飞出、跨容器变形成画布卡片）与 diagram-cascade 级联生成树（p',
    'duration_frames': 60,
    'source': 'video-shotcraft/canvas-materialize-moves',
    'css': {'.scene': {
        'animation': 'canvas_materialize_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'canvas_materialize_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('collab-cursor-moves', {
    'description': '协作光标当演员的两式——dialogue-duet 双光标暗场对话双人舞（靠近/绕位/灯光交接/放大成转场），与 cast-ensemble 五光标群演氛围层（',
    'duration_frames': 60,
    'source': 'video-shotcraft/collab-cursor-moves',
    'css': {'.scene': {
        'animation': 'collab_cursor_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'collab_cursor_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('command-palette-summon', {
    'description': '命令面板降临——整屏压暗加模糊，⌘K 面板带过冲弹落，候选行错峰浮现，敲字列表实时收窄',
    'duration_frames': 60,
    'source': 'video-shotcraft/command-palette-summon',
    'css': {'.scene': {
        'animation': 'command_palette_summon 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'command_palette_summon': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('hashtag-to-pill-materialize', {
    'description': '话题词打字实体化——居中打出 "#word"（红实心光标恒亮），1 帧硬切变成宽大胶囊标签，hold 后缩小左移落到页面标签位，再 1 帧硬切揭示成品页；"两次',
    'duration_frames': 60,
    'source': 'video-shotcraft/hashtag-to-pill-materialize',
    'css': {'.scene': {
        'animation': 'hashtag_to_pill_materialize 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'hashtag_to_pill_materialize': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('input-trigger-moves', {
    'description': '输入触发两式——cursor-performance 光标表演点击推近、keycap-smash-cut 键帽引信引爆猛切',
    'duration_frames': 60,
    'source': 'video-shotcraft/input-trigger-moves',
    'css': {'.scene': {
        'animation': 'input_trigger_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'input_trigger_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('segmented-thumb-hero', {
    'description': '分段控件 thumb 位移当主角特写——超大胶囊 segmented control 弹簧浮入，描边箭头光标画外滑入按下，白 thumb 8f ease-out',
    'duration_frames': 60,
    'source': 'video-shotcraft/segmented-thumb-hero',
    'css': {'.scene': {
        'animation': 'segmented_thumb_hero 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'segmented_thumb_hero': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('theme-switch-moves', {
    'description': '主题切换两式——theme-sweep 斜向扫场（边界扫过处就地换肤）与 palette-ripple 组合款（⌘K 面板收缩成点、涟漪从点荡开换肤）',
    'duration_frames': 60,
    'source': 'video-shotcraft/theme-switch-moves',
    'css': {'.scene': {
        'animation': 'theme_switch_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'theme_switch_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('type-and-filter', {
    'description': '真实 UI 上打字搜索、网格自己收敛成一张卡、点击穿透进详情页',
    'duration_frames': 60,
    'source': 'video-shotcraft/type-and-filter',
    'css': {'.scene': {
        'animation': 'type_and_filter 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'type_and_filter': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('voice-waveform-live', {
    'description': '录音胶囊实时声纹——64 根细竖条随"说话"起伏，说话时中部高耸、停顿缩成点线，波形从右往左滚动；说→停→说→提交塌缩的完整表演',
    'duration_frames': 60,
    'source': 'video-shotcraft/voice-waveform-live',
    'css': {'.scene': {
        'animation': 'voice_waveform_live 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'voice_waveform_live': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('brand-ink-open', {
    'description': '墨线十字准星描画→字标逐字压印→打字机副标→满一秒静止再上浮消散',
    'duration_frames': 60,
    'source': 'video-shotcraft/brand-ink-open',
    'css': {'.scene': {
        'animation': 'brand_ink_open 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'brand_ink_open': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('crane-rise-reveal', {
    'description': '升降臂拉升揭示——开场怼在一行数据特写，相机沿 Y 轴减速升起后拉，行行涌入直到整面 dashboard 铺满全幅',
    'duration_frames': 60,
    'source': 'video-shotcraft/crane-rise-reveal',
    'css': {'.scene': {
        'animation': 'crane_rise_reveal 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'crane_rise_reveal': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('dataviz-landscape-open', {
    'description': '暗场支流线束地景开场——多条流线汇入主干、虚构 ID 标签浮在线上、相机重景深低速飞越',
    'duration_frames': 60,
    'source': 'video-shotcraft/dataviz-landscape-open',
    'css': {'.scene': {
        'animation': 'dataviz_landscape_open 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'dataviz_landscape_open': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('icon-field-colorize', {
    'description': '灰阶小图标点阵错峰浮现铺满全屏，停一拍后多道品牌色横带波纹极快向下扫翻全场——"功能全景先摆满，品牌一瞬间点亮"的开场/收束卡',
    'duration_frames': 60,
    'source': 'video-shotcraft/icon-field-colorize',
    'css': {'.scene': {
        'animation': 'icon_field_colorize 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'icon_field_colorize': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('letterspace-materialize', {
    'description': '大字距字标全字符并行连续描画结晶——所有字母同帧起笔、笔画像手写一样连续生长、同帧齐收成词；氛围底景上的品牌字标显影',
    'duration_frames': 60,
    'source': 'video-shotcraft/letterspace-materialize',
    'css': {'.scene': {
        'animation': 'letterspace_materialize 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'letterspace_materialize': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('magician-card-flourish', {
    'description': '纯黑场上蓝色星芒闪现 0.3s（X 形针状光束旋转 90°+中心辉光放射小光芒），卡片从闪光点弹射而出——极速自旋弧线飞向镜头、自旋随靠近衰减、瞬间硬定格近满幅',
    'duration_frames': 60,
    'source': 'video-shotcraft/magician-card-flourish',
    'css': {'.scene': {
        'animation': 'magician_card_flourish 2s ease-out forwards',
    }},
    'keyframes': {
        'magician_card_flourish': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('spotlight-hero-card', {
    'description': '聚光灯扫过页面锁定一张卡，斜 45° 推进后卡片弹起悬浮、光束沿轮廓两圈、贴回原位',
    'duration_frames': 60,
    'source': 'video-shotcraft/spotlight-hero-card',
    'css': {'.scene': {
        'animation': 'spotlight_hero_card 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'spotlight_hero_card': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('stroke-segment-build', {
    'description': '断笔成字——标题拆成十几段互不相连的笔画乱序逐段点亮，前 70% 不可读，末段落位瞬间语义"啪"地成立',
    'duration_frames': 60,
    'source': 'video-shotcraft/stroke-segment-build',
    'css': {'.scene': {
        'animation': 'stroke_segment_build 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'stroke_segment_build': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('text-as-mask', {
    'description': '文字视频遮罩——超粗大标题字内部透出缓慢平移的产品画面，结尾字形放大 26 倍溢出、内部画面接管全屏',
    'duration_frames': 60,
    'source': 'video-shotcraft/text-as-mask',
    'css': {'.scene': {
        'animation': 'text_as_mask 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'text_as_mask': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('edit-hook-moves', {
    'description': 'logo-sting-button 片尾钩子——片尾 logo 定住后突插 12f 彩蛋再收，预告片 button ending',
    'duration_frames': 60,
    'source': 'video-shotcraft/edit-hook-moves',
    'css': {'.scene': {
        'animation': 'edit_hook_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'edit_hook_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('neon-triple-marquee', {
    'description': '三行对向霓虹跑马灯 recap——BETTER/FASTER/STRONGER 空心描边巨字上中下排满全屏，奇偶行反向匀速无限横滚，三行按 1/3 相位轮流亮起',
    'duration_frames': 60,
    'source': 'video-shotcraft/neon-triple-marquee',
    'css': {'.scene': {
        'animation': 'neon_triple_marquee 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'neon_triple_marquee': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('outro-group-photo-launch', {
    'description': '全片元素从四面八方飞来围住字标合影，crane 落机位+舞台光+金尘做成发布会收场',
    'duration_frames': 60,
    'source': 'video-shotcraft/outro-group-photo-launch',
    'css': {'.scene': {
        'animation': 'outro_group_photo_launch 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'outro_group_photo_launch': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('ui-strip-away-outro', {
    'description': '减法式收尾——点击 Publish 后整个编辑器 UI 从外围到中心层层错峰蒸发，黑场上只剩那颗按钮滑到屏心放大，按钮再淡出交棒字标定版',
    'duration_frames': 60,
    'source': 'video-shotcraft/ui-strip-away-outro',
    'css': {'.scene': {
        'animation': 'ui_strip_away_outro 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'ui_strip_away_outro': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('ui-to-brand-morph', {
    'description': 'UI 变品牌两式——icon-flip-bloom 图标 Y 轴翻扁成竖线绽放成花形 mark + wordmark 逐字落定，与 input-morph-as',
    'duration_frames': 60,
    'source': 'video-shotcraft/ui-to-brand-morph',
    'css': {'.scene': {
        'animation': 'ui_to_brand_morph 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'ui_to_brand_morph': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('beat-cut-moves', {
    'description': '硬切当节拍乐器的两式——递进硬切串（间隔减半加速逼近）与连闪定格（三次白闪各切一个裁切）',
    'duration_frames': 60,
    'source': 'video-shotcraft/beat-cut-moves',
    'css': {'.scene': {
        'animation': 'beat_cut_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'beat_cut_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('beat-step-list-theme-cycle', {
    'description': '三通道节拍器——深色场形容词列表逐拍上移一行，视口中央固定胶囊"接住"下一个词并换色，整场底色同拍跟换；行、色、场三通道锁死同一拍点',
    'duration_frames': 60,
    'source': 'video-shotcraft/beat-step-list-theme-cycle',
    'css': {'.scene': {
        'animation': 'beat_step_list_theme_cycle 2s ease-out forwards',
    }},
    'keyframes': {
        'beat_step_list_theme_cycle': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('montage-rhythm-moves', {
    'description': '蒙太奇节奏三式——drop-blackout-slam 黑场蓄爆、wright-triple-cut 三连咔哒特写、domino-cascade 多米诺连锁入场',
    'duration_frames': 60,
    'source': 'video-shotcraft/montage-rhythm-moves',
    'css': {'.scene': {
        'animation': 'montage_rhythm_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'montage_rhythm_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('panel-grid-moves', {
    'description': '分格节奏三式——grid-flash-mosaic 九宫格闪切填墙吞屏、flip-grid-reflow 网格集体重排、comic-panel-split 漫画',
    'duration_frames': 60,
    'source': 'video-shotcraft/panel-grid-moves',
    'css': {'.scene': {
        'animation': 'panel_grid_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'panel_grid_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('rhythm-interrupt-moves', {
    'description': '打断节奏两式——jump-cut-punch-in 三级跳切推近、strobe-black-frames 频闪黑帧',
    'duration_frames': 60,
    'source': 'video-shotcraft/rhythm-interrupt-moves',
    'css': {'.scene': {
        'animation': 'rhythm_interrupt_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'rhythm_interrupt_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('sakuga-timing-shift', {
    'description': '一拍三转一拍一——元素先以每 3 帧一步的手翻书顿挫移动，高潮瞬间切成逐帧丝滑冲刺，帧率量化的突变本身就是看点',
    'duration_frames': 60,
    'source': 'video-shotcraft/sakuga-timing-shift',
    'css': {'.scene': {
        'animation': 'sakuga_timing_shift 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'sakuga_timing_shift': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('smear-multiples', {
    'description': '残像分身——卡片高速横移时拖 4 个清晰可数的半透明分身副本，落位瞬间收拢合一；motion blur 的动画式平替',
    'duration_frames': 60,
    'source': 'video-shotcraft/smear-multiples',
    'css': {'.scene': {
        'animation': 'smear_multiples 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'smear_multiples': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('spectrum-morph-ui', {
    'description': '频谱化 UI——标题下划线裂成一排竖条按频谱跳动两小节，再收拢还原成直线；音乐可视化长在 UI 上',
    'duration_frames': 60,
    'source': 'video-shotcraft/spectrum-morph-ui',
    'css': {'.scene': {
        'animation': 'spectrum_morph_ui 2s ease-out forwards',
    }},
    'keyframes': {
        'spectrum_morph_ui': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('speed-ramp-freeze', {
    'description': '帧号非线性 remap 的两款节奏手法——变速（快→0.2x 凝视→快）与定格标注（流动→定格圈注→解冻）',
    'duration_frames': 60,
    'source': 'video-shotcraft/speed-ramp-freeze',
    'css': {'.scene': {
        'animation': 'speed_ramp_freeze 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'speed_ramp_freeze': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('trailer-grammar-moves', {
    'description': '预告片语法三式——trailer-bumper 前置速剪钩子、card-footage-cadence 字卡穿插对话、smash-cut 猛切入定',
    'duration_frames': 60,
    'source': 'video-shotcraft/trailer-grammar-moves',
    'css': {'.scene': {
        'animation': 'trailer_grammar_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'trailer_grammar_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('bottom-push-stack-wipe', {
    'description': '底边上推换章——新场景连底色整屏从底边向上推入，把旧场景物理顶出画外，连推数章各配一种饱和底色，内容钉死在各自色底坐标系里随底色走',
    'duration_frames': 60,
    'source': 'video-shotcraft/bottom-push-stack-wipe',
    'css': {'.scene': {
        'animation': 'bottom_push_stack_wipe 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'bottom_push_stack_wipe': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('bubble-swarm-takeover', {
    'description': '珠光气泡群幕布转场——大小不一的气泡从画外飘入越涨越大遮满整屏，页面同步"洗白"，遮蔽峰值处藏切换，气泡向外散开后已是新场景；可混入 i18n 文字胶囊变体',
    'duration_frames': 60,
    'source': 'video-shotcraft/bubble-swarm-takeover',
    'css': {'.scene': {
        'animation': 'bubble_swarm_takeover 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'bubble_swarm_takeover': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('card-flip-reveal', {
    'description': '功能卡 3D 翻面揭示——卡片沿 Y 轴翻 180°，正面 UI 翻到侧棱最薄处闪过一道随角度移动的高光带，背面揭出大号结论数字，逐张错峰扫过整排',
    'duration_frames': 60,
    'source': 'video-shotcraft/card-flip-reveal',
    'css': {'.scene': {
        'animation': 'card_flip_reveal 2s ease-out forwards',
    }},
    'keyframes': {
        'card_flip_reveal': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('card-flock-tumble', {
    'description': '三张 UI 页卡从侧棱薄边 3D 翻飞成阶梯站定（全程清晰、样条连续丝滑），站定后保持慢转不停，快速收束吸入中心，炸出单个湍流烟雾环扩散，巨字横贯收场',
    'duration_frames': 60,
    'source': 'video-shotcraft/card-flock-tumble',
    'css': {'.scene': {
        'animation': 'card_flock_tumble 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'card_flock_tumble': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('circle-match-iris', {
    'description': '圆心匹配光圈切——光圈从页面上圆形元素的圆心炸开，圈内新页的圆形图表接在同一个圆上；匹配剪辑给光圈一个语义锚点',
    'duration_frames': 60,
    'source': 'video-shotcraft/circle-match-iris',
    'css': {'.scene': {
        'animation': 'circle_match_iris 2s ease-out forwards',
    }},
    'keyframes': {
        'circle_match_iris': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('color-block-step-wipe', {
    'description': '离散阶跃色块吞屏两式——A 中央小条按 3–5 步硬跳阶跃扩成全屏（接管后徽章两跳弹出），B 色块从角落斜向 3 步吃屏并携带一张页面卡逐跳前进',
    'duration_frames': 60,
    'source': 'video-shotcraft/color-block-step-wipe',
    'css': {'.scene': {
        'animation': 'color_block_step_wipe 2s ease-out forwards',
    }},
    'keyframes': {
        'color_block_step_wipe': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('line-carry-transition', {
    'description': '线条接力横移转场——场景 A 的进度条延伸出画，镜头跟线横移，线在移动中拐角围出场景 B 的卡框，全程无剪切',
    'duration_frames': 60,
    'source': 'video-shotcraft/line-carry-transition',
    'css': {'.scene': {
        'animation': 'line_carry_transition 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'line_carry_transition': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('page-turn-transitions', {
    'description': '整页体块转场两式——cube-rotate 立方体翻转（两页贴盒子相邻面转 90°）与 barn-door-split 对开门裂幕（旧页裂两半滑出、新页迎上）',
    'duration_frames': 60,
    'source': 'video-shotcraft/page-turn-transitions',
    'css': {'.scene': {
        'animation': 'page_turn_transitions 2s ease-out forwards',
    }},
    'keyframes': {
        'page_turn_transitions': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('paper-plane-messenger', {
    'description': '纸飞机信使转场——点击"发送"后镜头拉远脱离窗口 A，折纸飞机沿贝塞尔弧线飞出（俯仰跟随切线），镜头伴飞穿过多层视差道具，飞抵窗口 B 门前落定，B 放大接管全',
    'duration_frames': 60,
    'source': 'video-shotcraft/paper-plane-messenger',
    'css': {'.scene': {
        'animation': 'paper_plane_messenger 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'paper_plane_messenger': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('print-texture-transitions', {
    'description': '印刷质感转场——ink-bleed-reveal 墨渗揭示（须状渗边洇开吃掉旧景）',
    'duration_frames': 60,
    'source': 'video-shotcraft/print-texture-transitions',
    'css': {'.scene': {
        'animation': 'print_texture_transitions 2s ease-out forwards',
    }},
    'keyframes': {
        'print_texture_transitions': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('shot-transitions', {
    'description': '镜头交棒六式——推进流白、穿暗场直航、虚焦接力、黑场字卡、whip-pan 甩镜、mask-wipe 穿窗（含纵深款），按能量落差选型',
    'duration_frames': 60,
    'source': 'video-shotcraft/shot-transitions',
    'css': {'.scene': {
        'animation': 'shot_transitions 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'shot_transitions': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('tear-streak-transitions', {
    'description': '撕裂转场——glitch-displace 噪声撕裂（16 横条错位抖动中硬切），数字故障语义的条带级撕裂',
    'duration_frames': 60,
    'source': 'video-shotcraft/tear-streak-transitions',
    'css': {'.scene': {
        'animation': 'tear_streak_transitions 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'tear_streak_transitions': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('transition-hidden-cut', {
    'description': '藏切点转场三式——前景遮挡隐形切、对撞开屏、暖色漏光，硬切藏进遮挡/撞击/光峰的 1-3 帧里，观众看不见剪刀',
    'duration_frames': 60,
    'source': 'video-shotcraft/transition-hidden-cut',
    'css': {'.scene': {
        'animation': 'transition_hidden_cut 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'transition_hidden_cut': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('transition-travel', {
    'description': '穿越式转场两式——共享元素归位、字腔穿越，镜头钻进画面里的真实元素完成换景',
    'duration_frames': 60,
    'source': 'video-shotcraft/transition-travel',
    'css': {'.scene': {
        'animation': 'transition_travel 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'transition_travel': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('wipe-transitions', {
    'description': '几何擦除转场两式——clock-wipe 时钟扫描（雷达指针扫一圈换页）与 blinds-slice 百叶窗切条（12 竖条错峰翻换成波）',
    'duration_frames': 60,
    'source': 'video-shotcraft/wipe-transitions',
    'css': {'.scene': {
        'animation': 'wipe_transitions 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'wipe_transitions': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('cel-flash-stomp', {
    'description': '底色闪砸字——大词逐拍像图章歪着砸满屏，每词落定瞬间背景层在两个纯色间频闪数帧而文字纹丝不动；动漫必杀技字卡的 UI 翻译',
    'duration_frames': 60,
    'source': 'video-shotcraft/cel-flash-stomp',
    'css': {'.scene': {
        'animation': 'cel_flash_stomp 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'cel_flash_stomp': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('document-typewriter-reveal', {
    'description': '整页真排版文档在光标后自己"写"出来、侧栏跟进、历史条目逐个落入轨道',
    'duration_frames': 60,
    'source': 'video-shotcraft/document-typewriter-reveal',
    'css': {'.scene': {
        'animation': 'document_typewriter_reveal 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'document_typewriter_reveal': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('gradient-word-sweep', {
    'description': '黑底标语里关键词被渐变彩光从左到右快速扫过"充能"——波前字符辉光最强向后衰减，填满后字符间勾连细紫红闪电、整词稳态泛光呼吸',
    'duration_frames': 60,
    'source': 'video-shotcraft/gradient-word-sweep',
    'css': {'.scene': {
        'animation': 'gradient_word_sweep 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'gradient_word_sweep': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('marker-underline-title', {
    'description': '大标题落定后，关键词下方马克笔下划线从左到右快速描画——变宽笔形、毛糙边缘、微上斜跟随斜体字势，贴着字底',
    'duration_frames': 60,
    'source': 'video-shotcraft/marker-underline-title',
    'css': {'.scene': {
        'animation': 'marker_underline_title 2s ease-out forwards',
    }},
    'keyframes': {
        'marker_underline_title': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('paper-title-card', {
    'description': '一句话逐词压印上纸、一个词标强调色斜体、短划线收束',
    'duration_frames': 60,
    'source': 'video-shotcraft/paper-title-card',
    'css': {'.scene': {
        'animation': 'paper_title_card 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'paper_title_card': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('pill-slot-cycle', {
    'description': '句中词槽轮换——固定句干钉死不动，句尾 pill 徽章每 ~0.7s 老虎机滚一格（旧的上飞加速淡出、新的从下带模糊滑入），连换 N 个功能词后落成完整句子收束',
    'duration_frames': 60,
    'source': 'video-shotcraft/pill-slot-cycle',
    'css': {'.scene': {
        'animation': 'pill_slot_cycle 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'pill_slot_cycle': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('split-flap-title', {
    'description': '机场翻牌屏字标题——每字符上下两半机械翻牌格，翻过 2 个乱码咔哒停在目标字，左→右级联成波',
    'duration_frames': 60,
    'source': 'video-shotcraft/split-flap-title',
    'css': {'.scene': {
        'animation': 'split_flap_title 2s ease-out forwards',
    }},
    'keyframes': {
        'split_flap_title': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('text-column-converge', {
    'description': '双词对峙合拢——左"NEW"右特性词钉死在等屏边距两侧硬切轮换、全程零收缩，换到最后一词才唯一一次 ease-in-out 滑到居中咬合成短语，下方小字近乎硬切',
    'duration_frames': 60,
    'source': 'video-shotcraft/text-column-converge',
    'css': {'.scene': {
        'animation': 'text_column_converge 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'text_column_converge': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('title-demote-to-label', {
    'description': '大标题降格为节标签两式——A 大标题居中显影站稳一拍后连续缩小 0.3x 平移到左上角落成小节标签、内容区在其下生长；B 同套路但登场时带文本选中态高亮块扫入再',
    'duration_frames': 60,
    'source': 'video-shotcraft/title-demote-to-label',
    'css': {'.scene': {
        'animation': 'title_demote_to_label 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'title_demote_to_label': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('type-assembly-moves', {
    'description': '文字集结四式——split-text-stagger 逐字裂升、letterform-drift-assembly 漂移合拢、tracking-expand-r',
    'duration_frames': 60,
    'source': 'video-shotcraft/type-assembly-moves',
    'css': {'.scene': {
        'animation': 'type_assembly_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'type_assembly_moves': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('type-entrance-moves', {
    'description': '标题文字入场两式——scramble-decode 乱码解码（噪声里长出答案）与 letter-drop-physics 字符坠落（重力砸落弹跳归位），按调性二',
    'duration_frames': 60,
    'source': 'video-shotcraft/type-entrance-moves',
    'css': {'.scene': {
        'animation': 'type_entrance_moves 2s ease-out forwards',
    }},
    'keyframes': {
        'type_entrance_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('type-rhythm-sync', {
    'description': '文字随声同步两式——font-weight-pump 字重脉冲（笔画随鼓点变粗弹回）与 karaoke-fill-sync 卡拉OK填色（词随旁白逐个点亮）',
    'duration_frames': 60,
    'source': 'video-shotcraft/type-rhythm-sync',
    'css': {'.scene': {
        'animation': 'type_rhythm_sync 2s ease-out forwards',
    }},
    'keyframes': {
        'type_rhythm_sync': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('typewriter-moves', {
    'description': '打字机两式——terminal-typewriter 终端命令敲完即引爆场景切换、error-retype 误删重打的"改口"三幕剧',
    'duration_frames': 60,
    'source': 'video-shotcraft/typewriter-moves',
    'css': {'.scene': {
        'animation': 'typewriter_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'typewriter_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('word-relay-filmstrip', {
    'description': '左列黑白相间等高页面卡步进滚动、右侧衬线大词原位接力（名词恒定+动词轮换）——切词瞬间才滚动一格，词块垂直中心与当前页面卡中点精确对齐',
    'duration_frames': 60,
    'source': 'video-shotcraft/word-relay-filmstrip',
    'css': {'.scene': {
        'animation': 'word_relay_filmstrip 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'word_relay_filmstrip': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('cloner-depth-echo', {
    'description': '克隆纵队——主卡瞬间"复印"出 7 个半透明分身沿斜向纵深排开成队，停一拍后全体加速吸回本体合一+弹跳',
    'duration_frames': 60,
    'source': 'video-shotcraft/cloner-depth-echo',
    'css': {'.scene': {
        'animation': 'cloner_depth_echo 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'cloner_depth_echo': [
            {'offset': 0, 'transform': 'translateY(30px)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0)'},
        ]
    },
})

_register('deck-deal-flyin', {
    'description': '暗场金属背景里的实体牌堆特写环绕开局，拉远交给页面后一摞卡像发牌一样硬加速甩进网格，相机追着滚动、满板停半秒',
    'duration_frames': 60,
    'source': 'video-shotcraft/deck-deal-flyin',
    'css': {'.scene': {
        'animation': 'deck_deal_flyin 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'deck_deal_flyin': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('draw-svg-trace', {
    'description': '描边生长圈注——一条带笔头的墨线沿元素轮廓跑一圈把它"画"出来，闭合瞬间闪黑交棒、内容淡入；同套路可给标题画下划线',
    'duration_frames': 60,
    'source': 'video-shotcraft/draw-svg-trace',
    'css': {'.scene': {
        'animation': 'draw_svg_trace 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'draw_svg_trace': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('element-body-moves', {
    'description': '元素身体感两式——axial-stretch 轴向拉伸糖稀拉丝、contact-shadow-lift 接触阴影离面抬升',
    'duration_frames': 60,
    'source': 'video-shotcraft/element-body-moves',
    'css': {'.scene': {
        'animation': 'element_body_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'element_body_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('integration-hub-map', {
    'description': '旧页面一次性快翻 180°（侧棱瞬间亮闪）落成新中枢页，五个集成 app 图标同帧弹现、随即五条彩虹光管同帧齐连，光管内输送脉冲持续流动——"翻开新一页，生态一',
    'duration_frames': 60,
    'source': 'video-shotcraft/integration-hub-map',
    'css': {'.scene': {
        'animation': 'integration_hub_map 2s ease-out forwards',
    }},
    'keyframes': {
        'integration_hub_map': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('list-stack-press', {
    'description': '列表卡从画面底部逐张飞上摞起，每张落地压弹整摞、计数器同步跳一格',
    'duration_frames': 60,
    'source': 'video-shotcraft/list-stack-press',
    'css': {'.scene': {
        'animation': 'list_stack_press 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'list_stack_press': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('morph-from-primitive', {
    'description': '原型变形——正圆呼吸一拍（anticipation）后 SVG path 插值 24f 长成圆角卡轮廓，内容淡入',
    'duration_frames': 60,
    'source': 'video-shotcraft/morph-from-primitive',
    'css': {'.scene': {
        'animation': 'morph_from_primitive 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'morph_from_primitive': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('neon-frame-forerun', {
    'description': '强透视直角霓虹框自左缘两头奔画先行成型，页面在框内由暗转亮，同时框内组件/文字从 3D 上空带同形软影错峰贴落、随页面点亮同步完成贴合，背景霓虹管群终段熄灭让位',
    'duration_frames': 60,
    'source': 'video-shotcraft/neon-frame-forerun',
    'css': {'.scene': {
        'animation': 'neon_frame_forerun 2s ease-out forwards',
    }},
    'keyframes': {
        'neon_frame_forerun': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('neon-frame-orbit-drop', {
    'description': '霓虹框先行描框后，镜头绕页面左→右弧线旋转，页面全部组件/文字**同帧**从空中往下贴合（同形软影同步收敛）——整体登场式的框内安放',
    'duration_frames': 60,
    'source': 'video-shotcraft/neon-frame-orbit-drop',
    'css': {'.scene': {
        'animation': 'neon_frame_orbit_drop 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'neon_frame_orbit_drop': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('page-waterfall-wall', {
    'description': '页面瀑布墙——真实页面截图切成 3–4 列在 3D 后仰墙面上差速反向无限滚动，视差 + 镜头缓推做"内容多到流不完"的一览',
    'duration_frames': 60,
    'source': 'video-shotcraft/page-waterfall-wall',
    'css': {'.scene': {
        'animation': 'page_waterfall_wall 2s ease-out forwards',
    }},
    'keyframes': {
        'page_waterfall_wall': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('paper-craft-moves', {
    'description': '纸艺两式——masking-tape-slap 纸胶带拍定（悬浮微晃被"啪啪"按死）与 popup-book-rise 立体书立起（卡片沿底边错峰立墙）',
    'duration_frames': 60,
    'source': 'video-shotcraft/paper-craft-moves',
    'css': {'.scene': {
        'animation': 'paper_craft_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'paper_craft_moves': [
            {'offset': 0, 'transform': 'scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'scale(1)'},
        ]
    },
})

_register('row-embed', {
    'description': '内容行像卡片一样从空中降下、rotateX 收平、嵌入瞬间底边亮一道强调色的缝',
    'duration_frames': 60,
    'source': 'video-shotcraft/row-embed',
    'css': {'.scene': {
        'animation': 'row_embed 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'row_embed': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('runway-ground-skim', {
    'description': '低角度掠地机位下 UI 卡片群从空中一阵急雨式快速贴落（起点微错、下落大量重叠并行、着地即停零回弹），落齐后整页立起、视角转正收尾',
    'duration_frames': 60,
    'source': 'video-shotcraft/runway-ground-skim',
    'css': {'.scene': {
        'animation': 'runway_ground_skim 2s ease-out forwards',
    }},
    'keyframes': {
        'runway_ground_skim': [
            {'offset': 0, 'transform': 'none'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'none'},
        ]
    },
})

_register('skeleton-reveal', {
    'description': '草稿→骨架→内容三级显影——手绘涂鸦占位（煮沸抖动）一拍被灰条骨架窗口替换，骨架列表滚入后镜头推近、灰条逐行显影成头像+逐词文字，末词晚半拍落地',
    'duration_frames': 60,
    'source': 'video-shotcraft/skeleton-reveal',
    'css': {'.scene': {
        'animation': 'skeleton_reveal 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'skeleton_reveal': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})

_register('wall-reveal-moves', {
    'description': '整墙批量入场三式——bento 逐格点亮、网格波浪翻面、蓝图描线成形，全部原位显形不位移，与 deck-deal-flyin 的飞入位移型互补成品类矩阵',
    'duration_frames': 60,
    'source': 'video-shotcraft/wall-reveal-moves',
    'css': {'.scene': {
        'animation': 'wall_reveal_moves 2s ease-out forwards',
        'opacity': '0',
    }},
    'keyframes': {
        'wall_reveal_moves': [
            {'offset': 0, 'transform': 'translateY(30px) scale(0.8)'},
            {'offset': 0.7, 'transform': 'scale(1.05)'},
            {'offset': 1, 'transform': 'translateY(0) scale(1)'},
        ]
    },
})
