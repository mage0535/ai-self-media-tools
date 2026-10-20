#!/usr/bin/env python3
"""
shotcraft_transition_v2.py — video-shotcraft 转场/收尾镜头卡 CSS 动画引擎（v2 补充）

来源：video-shotcraft (5.3k star) references/shots/transition/ 与 references/shots/outro/
本文件将 5 张转场类镜头卡翻译为 HTML+CSS 动画定义，适配知识卡片视频管线
（HTML → Playwright → FFmpeg），1080x1920 竖屏与 1280x720 横屏通用。

已收录卡片（与 shotcraft_moves.py 的 121 种运动镜头互补，均为转场/收尾类）：
  gradient-transition            渐变背景三段换型（linear→radial→conic）
  grain-dissolve                 文字砂化→噪点凝聚成发光短标（outro 收尾）
  mosaic-reframe                 12 瓦片三套排版连续变形（网格→feature mosaic→对角瀑布）
  cube-navigation                3D 立方体六面逐面导航（相机推拉 + 法线明暗）
  white-flash-logo-simplify-cut  液态渐变字标 → 冲白过曝 → 扁平字标定格

缓动映射（Remotion Easing → CSS cubic-bezier）：
  inQuad      -> cubic-bezier(0.55, 0.085, 0.68, 0.53)   # 快速冲入
  outCubic    -> cubic-bezier(0.215, 0.61, 0.355, 1)     # 缓出落定
  inOutCubic  -> cubic-bezier(0.645, 0.045, 0.355, 1)    # 对称缓动
  outQuad     -> cubic-bezier(0.25, 0.46, 0.45, 0.94)    # 轻缓落定

使用方式：
  from scripts.shotcraft_transition_v2 import SHOT_CARD_REGISTRY
  meta = SHOT_CARD_REGISTRY["cube-navigation"]   # {description, duration_frames, css, keyframes}

已知坑（翻译时的取舍）：
  - CSS 无法逐帧插值 gradient 字符串（每帧重写 background 触发 repaint），
    gradient-transition 用「三层独立渐变层 + 窄窗口 opacity 交叉淡化」还原；
  - feTurbulence/feDisplacementMap 无法被 CSS keyframes 插值，
    grain-dissolve 用「SVG 颗粒滤镜层 + translate 抖动 + blur 包络」近似砂化沸腾；
  - cube-navigation 的法线明暗依赖 rig 旋转矩阵，CSS 侧用
    perspective + transform-style:preserve-3d 的 rig 包装层还原，
    面亮度用 filter:brightness 关键帧近似（按段窗口对齐相机位姿）。
"""

import json
import math
import random

# ═══════════════════════════════════════════
# 转场镜头卡注册表
# ═══════════════════════════════════════════

SHOT_CARD_REGISTRY = {}


def _register(name, meta):
    SHOT_CARD_REGISTRY[name] = meta
    return meta


# ── gradient-transition ────────────────────
# 180f@30fps ≈ 6.0s：linear 0–2.4s · radial 2–4.2s · conic 4–6s
# 动效核心：三层各持一种渐变类型，同一时刻只有一层主导，
#           交叉淡化窗口很窄（0.08）；linear 角度 40°→230° 扫过，
#           radial 圆心对角迁移 + 半径 45%→85% 扩张，conic from 角 0→300° 旋转。
# 已知坑：CSS 渐变字符串每帧重写触发 repaint → 用三层 + opacity 交叉淡化；
#         前景内容请压 opacity 0.6–0.8 或叠暗色 scrim。

_register("gradient-transition", {
    "description": "背景在 linear/radial/conic 三类 CSS 渐变间平滑过渡——角度、色标、中心、半径逐参数插值，段间窄窗口交叉淡化换类型，给静态排版段落提供'活着'的背景层",
    "duration_frames": 180,
    "css": {
        ".scene": {
            "animation": "grad-scene 6s ease-in-out forwards",
            "overflow": "hidden",
            "background": "#0a0a12",
        },
        ".grad-layer": {
            "position": "absolute",
            "inset": "0",
            "will-change": "opacity, transform, background-position",
        },
        # linear 段（t=0–0.4 主导）：角度扫过用超大背景 + background-position 平移近似
        ".grad-linear": {
            "background": "linear-gradient(40deg, hsl(224 80% 60%), hsl(330 70% 45%) 40%, hsl(40 85% 55%) 70%, hsl(224 80% 60%))",
            "background-size": "320% 320%",
            "animation": "grad-linear 6s ease-in-out forwards",
            "opacity": "0",
        },
        # radial 段（t=0.33–0.7 主导）：圆心对角迁移 + 半径扩张 → translate + scale
        ".grad-radial": {
            "background": "radial-gradient(circle at 50% 50%, hsl(190 85% 55%) 0%, hsl(240 60% 35%) 40%, #05050c 78%)",
            "background-size": "150% 150%",
            "animation": "grad-radial 6s ease-in-out forwards",
            "opacity": "0",
        },
        # conic 段（t=0.66–1 主导）：from 角 0→300° 旋转 → 放大层整体 rotate
        ".grad-conic": {
            "background": "conic-gradient(from 0deg, hsl(0 90% 60%), hsl(60 95% 55%), hsl(150 85% 50%), hsl(210 90% 55%), hsl(280 85% 55%), hsl(330 90% 55%), hsl(0 90% 60%))",
            "background-size": "120% 120%",
            "animation": "grad-conic 6s ease-in-out forwards",
            "opacity": "0",
            "transform-origin": "center center",
        },
        # 玻璃 pill 标签（demo 用；实用时删掉）
        ".grad-pill": {
            "position": "absolute",
            "top": "48%",
            "left": "50%",
            "transform": "translate(-50%, -50%)",
            "padding": "10px 26px",
            "border-radius": "999px",
            "background": "rgba(255,255,255,0.12)",
            "border": "1px solid rgba(255,255,255,0.25)",
            "backdrop-filter": "blur(12px)",
            "color": "#fff",
            "font-size": "20px",
            "letter-spacing": "4px",
            "animation": "grad-pill 6s ease-in-out forwards",
        },
    },
    "keyframes": {
        "grad-scene": [
            {"offset": 0, "filter": "brightness(1)"},
            {"offset": 1, "filter": "brightness(1)"},
        ],
        # linear 主导 0–0.4；0.33 起让位 radial（交叉淡化窗口 0.08）
        "grad-linear": [
            {"offset": 0, "opacity": 1, "background-position": "0% 50%", "transform": "scale(1)"},
            {"offset": 0.4, "opacity": 1, "background-position": "100% 50%", "transform": "scale(1.05)"},
            {"offset": 0.42, "opacity": 0, "background-position": "100% 50%", "transform": "scale(1.08)"},
            {"offset": 1, "opacity": 0, "background-position": "100% 50%", "transform": "scale(1.08)"},
        ],
        # radial 主导 0.33–0.7：圆心 28%,66%→72%,32% 对角迁移 + 半径 45%→85%
        "grad-radial": [
            {"offset": 0, "opacity": 0, "transform": "translate(-22%, 16%) scale(0.6)"},
            {"offset": 0.33, "opacity": 0, "transform": "translate(-22%, 16%) scale(0.6)"},
            {"offset": 0.41, "opacity": 1, "transform": "translate(-12%, 8%) scale(0.7)"},
            {"offset": 0.5, "opacity": 1, "transform": "translate(0%, 0%) scale(0.85)"},
            {"offset": 0.7, "opacity": 1, "transform": "translate(22%, -16%) scale(1.1)"},
            {"offset": 0.78, "opacity": 0, "transform": "translate(22%, -16%) scale(1.15)"},
            {"offset": 1, "opacity": 0, "transform": "translate(22%, -16%) scale(1.15)"},
        ],
        # conic 主导 0.66–1：from 角 0→300° 旋转（单次播放留 60° 缺口避免回到原点感）
        "grad-conic": [
            {"offset": 0, "opacity": 0, "transform": "rotate(0deg) scale(1.3)"},
            {"offset": 0.66, "opacity": 0, "transform": "rotate(0deg) scale(1.3)"},
            {"offset": 0.74, "opacity": 1, "transform": "rotate(60deg) scale(1.25)"},
            {"offset": 1, "opacity": 1, "transform": "rotate(300deg) scale(1.2)"},
        ],
        # pill 标签：跟随主导段切换文案（LINEAR/RADIAL/CONIC 用 opacity 轮换近似）
        "grad-pill": [
            {"offset": 0, "opacity": 1},
            {"offset": 0.36, "opacity": 0},
            {"offset": 0.40, "opacity": 1},
            {"offset": 0.68, "opacity": 0},
            {"offset": 0.72, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
    },
})


# ── grain-dissolve ─────────────────────────
# 60f@30fps ≈ 2.0s：砂化 0.26–0.56s · 凝聚 1.2–1.42s · 凝固回落收尾
# 动效核心：整行字爆裂成沸腾颗粒（displacement scale 0→52 + blur 0→1.1px，
#           seed 逐帧换 → 用 translate 抖动近似），噪点云急速凝聚成更大号发光短字标。
# 已知坑：feTurbulence/feDisplacementMap 无法被 CSS 插值 → 用颗粒覆盖层 +
#         抖动 + blur 包络近似；辉光回落别到 0，留柔光余温。

_register("grain-dissolve", {
    "description": "整行字爆裂成沸腾颗粒噪点，噪点云急速凝聚成更大号发光短字标，位移衰减归零定格——'一句话浓缩成一个词'的收尾能量聚合拍（outro 卡点）",
    "duration_frames": 60,
    "css": {
        ".scene": {
            "animation": "grain-scene 2s ease-in-out forwards",
            "background": "#07070d",
            "overflow": "hidden",
        },
        # 整行字（33px）：前 0.13 干净停留 → 砂化沸腾 → 凝聚窗口内淡出
        ".grain-line": {
            "position": "absolute",
            "left": "50%",
            "top": "38%",
            "transform": "translate(-50%, -50%)",
            "color": "#fff",
            "font-size": "33px",
            "font-weight": "600",
            "letter-spacing": "2px",
            "white-space": "nowrap",
            "animation": "grain-burst 2s cubic-bezier(0.215, 0.61, 0.355, 1) forwards",
            "will-change": "transform, filter, opacity",
        },
        # 发光短字标（54px 粗体）：凝聚窗口淡入 + 位移衰减归零 + 辉光呼吸
        ".grain-label": {
            "position": "absolute",
            "left": "50%",
            "top": "38%",
            "transform": "translate(-50%, -50%)",
            "color": "#fff",
            "font-size": "54px",
            "font-weight": "800",
            "letter-spacing": "1px",
            "white-space": "nowrap",
            "animation": "grain-condense 2s cubic-bezier(0.645, 0.045, 0.355, 1) forwards",
            "opacity": "0",
            "will-change": "transform, filter, opacity",
        },
        # 颗粒噪点覆盖层：background-position 快速平移 + 透明度随砂化窗口呼吸（沸腾近似）
        ".grain-overlay": {
            "position": "absolute",
            "inset": "0",
            "background-image": (
                "repeating-conic-gradient(rgba(255,255,255,0.14) 0% 0.6%, "
                "transparent 0.6% 1.4%, rgba(255,255,255,0.08) 1.4% 2.2%, "
                "transparent 2.2% 3.6%)"
            ),
            "background-size": "7px 7px",
            "animation": "grain-boil 2s steps(8) forwards",
            "opacity": "0",
            "mix-blend-mode": "screen",
            "pointer-events": "none",
        },
        # 斜纹选区框：随 burst 浮现、凝聚前撤掉（0.55–0.64）
        ".grain-frame": {
            "position": "absolute",
            "left": "50%",
            "top": "38%",
            "width": "520px",
            "height": "96px",
            "transform": "translate(-50%, -50%) rotate(45deg)",
            "border": "2px dashed rgba(255,255,255,0.55)",
            "background": "repeating-linear-gradient(45deg, rgba(255,255,255,0.10) 0 6px, transparent 6px 12px)",
            "animation": "grain-frame 2s ease-out forwards",
            "opacity": "0",
            "pointer-events": "none",
        },
    },
    "keyframes": {
        "grain-scene": [
            {"offset": 0, "filter": "brightness(1)"},
            {"offset": 1, "filter": "brightness(1)"},
        ],
        # 砂化：0.13–0.28 沸腾冲高（outCubic），0.60–0.71 交叉淡出（inOutCubic 凝聚段）
        "grain-burst": [
            {"offset": 0, "transform": "translate(-50%, -50%) translate(0, 0)", "filter": "blur(0px)", "opacity": 1},
            {"offset": 0.13, "transform": "translate(-50%, -50%) translate(0, 0)", "filter": "blur(0px)", "opacity": 1},
            # 沸腾：抖动幅度递增模拟 displacement scale 0→52
            {"offset": 0.2, "transform": "translate(calc(-50% + 6px), calc(-50% - 4px))", "filter": "blur(0.6px)", "opacity": 1},
            {"offset": 0.28, "transform": "translate(calc(-50% - 9px), calc(-50% + 7px))", "filter": "blur(1.1px)", "opacity": 1},
            {"offset": 0.45, "transform": "translate(calc(-50% + 7px), calc(-50% + 5px))", "filter": "blur(0.9px)", "opacity": 1},
            # 凝聚窗口交叉淡化（0.60–0.71，inOutCubic）
            {"offset": 0.6, "transform": "translate(-50%, -50%) translate(0, 0)", "filter": "blur(0.8px)", "opacity": 1},
            {"offset": 0.71, "transform": "translate(-50%, -50%) translate(0, 0)", "filter": "blur(0px)", "opacity": 0},
            {"offset": 1, "transform": "translate(-50%, -50%) translate(0, 0)", "filter": "blur(0px)", "opacity": 0},
        ],
        # 凝聚：短标从颗粒云中心放大淡入，位移衰减归零，辉光冲高后回落留余温
        "grain-condense": [
            {"offset": 0, "transform": "translate(-50%, -50%) translate(0, 10px) scale(1.5)", "filter": "blur(2px) drop-shadow(0 0 4px rgba(255,255,255,0.3))", "opacity": 0},
            {"offset": 0.68, "transform": "translate(-50%, -50%) translate(0, 4px) scale(1.2)", "filter": "blur(0.5px) drop-shadow(0 0 12px rgba(255,255,255,0.5))", "opacity": 0.6},
            {"offset": 0.78, "transform": "translate(-50%, -50%) translate(0, 0) scale(1.0)", "filter": "blur(0px) drop-shadow(0 0 24px rgba(255,255,255,0.7))", "opacity": 1},
            {"offset": 0.9, "transform": "translate(-50%, -50%) translate(0, 0) scale(0.99)", "filter": "blur(0px) drop-shadow(0 0 14px rgba(255,255,255,0.5))", "opacity": 1},
            {"offset": 1, "transform": "translate(-50%, -50%) translate(0, 0) scale(1)", "filter": "blur(0px) drop-shadow(0 0 12px rgba(255,255,255,0.45))", "opacity": 1},
        ],
        # 沸腾噪声：steps 逐帧跳动（近似 seed 换帧率 floor(t*46)）
        "grain-boil": [
            {"offset": 0, "opacity": 0, "background-position": "0px 0px"},
            {"offset": 0.13, "opacity": 0.15, "background-position": "0px 0px"},
            {"offset": 0.28, "opacity": 0.85, "background-position": "-42px 18px"},
            {"offset": 0.45, "opacity": 0.7, "background-position": "24px -30px"},
            {"offset": 0.6, "opacity": 0.5, "background-position": "-12px 6px"},
            {"offset": 0.71, "opacity": 0, "background-position": "0px 0px"},
            {"offset": 1, "opacity": 0, "background-position": "0px 0px"},
        ],
        # 选区框：0.13–0.28 浮现，0.55–0.64 撤掉（必须早于凝聚完成）
        "grain-frame": [
            {"offset": 0, "opacity": 0, "transform": "translate(-50%, -50%) rotate(45deg) scale(0.9)"},
            {"offset": 0.2, "opacity": 0.9, "transform": "translate(-50%, -50%) rotate(45deg) scale(1)"},
            {"offset": 0.5, "opacity": 0.9, "transform": "translate(-50%, -50%) rotate(45deg) scale(1)"},
            {"offset": 0.64, "opacity": 0, "transform": "translate(-50%, -50%) rotate(45deg) scale(1.05)"},
            {"offset": 1, "opacity": 0, "transform": "translate(-50%, -50%) rotate(45deg) scale(1.05)"},
        ],
    },
})


# ── mosaic-reframe ─────────────────────────
# 180f@30fps ≈ 6.0s：浮现 0–0.6s · A→B 1.6–2.5s · hold · B→C 3.7–4.8s
# 动效核心：12 张瓦片在规则网格(4×3)、feature mosaic(6×4 首片占大位)、
#           对角瀑布(x 递增 + rot −15°+3°/片)三套排版间连续变形；
#           x/y/w/h/rot 五通道独立插值，逐片微 stagger 0.007（≈2 帧）。
# 已知坑：不能换成 transform:scale 整体缩放；C 段瓦片有意越出画框，别加 padding。
#          宽高动画引发子元素重排 → 占位内容用百分比定位，真实图片用 object-fit:cover。

_register("mosaic-reframe", {
    "description": "12 张瓦片在规则网格、feature mosaic、对角瀑布串三种排版间连续变形，位置宽高各自插值、逐片微错峰，段间留 hold——'同一批内容多种看法'的陈列转场",
    "duration_frames": 180,
    "css": {
        ".scene": {
            "animation": "mosaic-scene 6s ease-in-out forwards",
            "background": "#0c0c14",
            "overflow": "hidden",
            "position": "relative",
        },
        # 12 片瓦片统一基座：百分比定位 + overflow hidden 圆角容器（内容不裁坏）
        ".mosaic-tile": {
            "position": "absolute",
            "border-radius": "10px",
            "overflow": "hidden",
            "background": "linear-gradient(160deg, hsl(224 70% 55%), hsl(268 60% 40%))",
            "will-change": "transform, width, height, opacity",
            "animation": "mosaic-tile 6s cubic-bezier(0.215, 0.61, 0.355, 1) forwards, mosaic-enter 0.6s cubic-bezier(0.215, 0.61, 0.355, 1) forwards",
        },
        # 开场浮现：逐片错峰（i*0.012 ≈ 每片 2–3 帧），scale 0.82→1 + opacity
        ".mosaic-tile:nth-child(2)": {"animation-delay": "0s, 0.05s"},
        ".mosaic-tile:nth-child(3)": {"animation-delay": "0s, 0.10s"},
        ".mosaic-tile:nth-child(4)": {"animation-delay": "0s, 0.15s"},
        ".mosaic-tile:nth-child(5)": {"animation-delay": "0s, 0.20s"},
        ".mosaic-tile:nth-child(6)": {"animation-delay": "0s, 0.25s"},
        ".mosaic-tile:nth-child(7)": {"animation-delay": "0s, 0.30s"},
        ".mosaic-tile:nth-child(8)": {"animation-delay": "0s, 0.35s"},
        ".mosaic-tile:nth-child(9)": {"animation-delay": "0s, 0.40s"},
        ".mosaic-tile:nth-child(10)": {"animation-delay": "0s, 0.45s"},
        ".mosaic-tile:nth-child(11)": {"animation-delay": "0s, 0.50s"},
        ".mosaic-tile:nth-child(12)": {"animation-delay": "0s, 0.55s"},
        # 首片 zIndex 抬高 + 专属动画（mosaic 段 3×2 大位 + 瀑布领头）
        ".mosaic-tile:first-child": {
            "z-index": "2",
            "animation": "mosaic-tile-first 6s cubic-bezier(0.215, 0.61, 0.355, 1) forwards, mosaic-enter 0.6s cubic-bezier(0.215, 0.61, 0.355, 1) forwards",
            "animation-delay": "0s, 0s",
        },
        # 瓦片内占位内容（渐变底 + 圆点 + 双信息条）
        ".mosaic-tile::after": {
            "content": "''",
            "position": "absolute",
            "inset": "8%",
            "border-radius": "8px",
            "background": "radial-gradient(circle at 30% 30%, rgba(255,255,255,0.35) 0 6%, transparent 6%), linear-gradient(180deg, rgba(255,255,255,0.22) 0 18%, transparent 18% 100%)",
            "background-size": "100% 100%, 100% 100%",
        },
    },
    "keyframes": {
        "mosaic-scene": [
            {"offset": 0, "filter": "brightness(1)"},
            {"offset": 1, "filter": "brightness(1)"},
        ],
        # 开场浮现：i*0.012 错峰 + scale 0.82→1 + opacity（outCubic）
        "mosaic-enter": [
            {"offset": 0, "opacity": 0, "transform": "scale(0.82)"},
            {"offset": 1, "opacity": 1, "transform": "scale(1)"},
        ],
        # 三套布局连续变形：
        #   A（0–0.26）4×3 规则网格（92% 内容区 + 4% 边距）
        #   A→B（0.26–0.42）feature mosaic：6×4 单元格，首片占 3×2 大位
        #   hold（0.42–0.62）读版面
        #   B→C（0.62–0.80）对角瀑布：x=1+i*6.4%, y=-7+i*7.6%, rot=-15+i*3°
        #   hold（0.80–1）落定；C 段有意越出画框（y 从 −7% 到 91%），裁切是构图一部分
        "mosaic-tile": [
            # A：4×3 网格（瓦片宽 22%、高 28%）
            {"offset": 0, "transform": "translate(0%, 0%) rotate(0deg)", "width": "22%", "height": "28%", "opacity": 1},
            {"offset": 0.26, "transform": "translate(0%, 0%) rotate(0deg)", "width": "22%", "height": "28%", "opacity": 1},
            # A→B：feature mosaic（默认 14%×14% 单元格，首片 3×2 由 :first-child 叠加覆盖）
            {"offset": 0.34, "transform": "translate(0%, 0%) rotate(0deg)", "width": "14%", "height": "14%", "opacity": 1},
            {"offset": 0.42, "transform": "translate(0%, 0%) rotate(0deg)", "width": "14%", "height": "14%", "opacity": 1},
            # hold B（0.42–0.62）
            {"offset": 0.62, "transform": "translate(0%, 0%) rotate(0deg)", "width": "14%", "height": "14%", "opacity": 1},
            # B→C：对角瀑布（x 递增 + rot −15°+3°/片，逐片微 stagger 由延迟近似）
            {"offset": 0.71, "transform": "translate(6%, 7%) rotate(6deg)", "width": "16%", "height": "20%", "opacity": 1},
            {"offset": 0.8, "transform": "translate(12%, 14%) rotate(12deg)", "width": "18%", "height": "22%", "opacity": 1},
            # hold C（0.80–1）落定
            {"offset": 1, "transform": "translate(12%, 14%) rotate(12deg)", "width": "18%", "height": "22%", "opacity": 1},
        ],
        # 首片：mosaic 大位（3×2 单元格 ≈ 44%×28%）——由 :first-child 的专属动画叠加
        "mosaic-tile-first": [
            {"offset": 0, "transform": "translate(0%, 0%) rotate(0deg)", "width": "22%", "height": "28%", "opacity": 1},
            {"offset": 0.26, "transform": "translate(0%, 0%) rotate(0deg)", "width": "22%", "height": "28%", "opacity": 1},
            {"offset": 0.34, "transform": "translate(0%, 0%) rotate(0deg)", "width": "44%", "height": "28%", "opacity": 1},
            {"offset": 0.62, "transform": "translate(0%, 0%) rotate(0deg)", "width": "44%", "height": "28%", "opacity": 1},
            {"offset": 0.71, "transform": "translate(6%, 7%) rotate(6deg)", "width": "46%", "height": "32%", "opacity": 1},
            {"offset": 1, "transform": "translate(12%, 14%) rotate(12deg)", "width": "46%", "height": "32%", "opacity": 1},
        ],
    },
})

# ── cube-navigation ────────────────────────
# 180f@30fps ≈ 6.0s：五段相机步进，每段约 0.7s + hold
# 动效核心：内容贴满 3D 立方体六面，相机正面特写→拉远等轴→转面推近交替步进；
#           每面按法线朝向实时算明暗（brightness 0.5–1.12 + saturate）。
# 已知坑：相机动的是 rig（translateZ + rotateX/rotateY 顺序固定），别动每个面；
#         等轴必须同时有 rx 和 ry；明暗下限 <0.4 背面全黑丢体积感。

_register("cube-navigation", {
    "description": "内容贴满 3D 立方体六面，相机正面特写→拉远等轴看棱角→转面推近交替步进，每面按朝向实时明暗——多模块产品的'逐面导航'空间化串讲",
    "duration_frames": 180,
    "css": {
        ".scene": {
            "perspective": "760px",
            "perspective-origin": "50% 50%",
            "background": "#0a0a12",
            "overflow": "hidden",
        },
        # 相机 rig：translateZ + rotateX/rotateY 顺序固定（法线明暗依赖此旋转矩阵）
        ".cube-rig": {
            "position": "absolute",
            "inset": "0",
            "display": "flex",
            "align-items": "center",
            "justify-content": "center",
            "transform-style": "preserve-3d",
            "animation": "cube-rig 6s cubic-bezier(0.645, 0.045, 0.355, 1) forwards, cube-fadein 0.5s ease-out forwards",
            "will-change": "transform",
        },
        # 立方体：S=190px，六面 rotateX/Y(±90/180°) translateZ(95px)
        ".cube": {
            "position": "relative",
            "width": "190px",
            "height": "190px",
            "transform-style": "preserve-3d",
        },
        ".cube-face": {
            "position": "absolute",
            "inset": "0",
            "display": "flex",
            "flex-direction": "column",
            "align-items": "center",
            "justify-content": "center",
            "gap": "10px",
            "border": "1px solid rgba(255,255,255,0.25)",
            "border-radius": "8px",
            "backface-visibility": "hidden",
            "color": "#fff",
            "font-weight": "700",
            "font-size": "22px",
            "letter-spacing": "2px",
            "animation": "cube-lit 6s cubic-bezier(0.645, 0.045, 0.355, 1) forwards",
            "will-change": "filter",
        },
        # 六面独立色相（面身份的第一识别）：224/268/330/190/154/34
        ".cube-face:nth-child(1)": {"background": "hsl(224 60% 45%)", "transform": "rotateY(0deg) translateZ(95px)"},
        ".cube-face:nth-child(2)": {"background": "hsl(268 55% 42%)", "transform": "rotateY(90deg) translateZ(95px)"},
        ".cube-face:nth-child(3)": {"background": "hsl(330 55% 42%)", "transform": "rotateY(180deg) translateZ(95px)"},
        ".cube-face:nth-child(4)": {"background": "hsl(190 60% 40%)", "transform": "rotateY(-90deg) translateZ(95px)"},
        ".cube-face:nth-child(5)": {"background": "hsl(154 50% 38%)", "transform": "rotateX(90deg) translateZ(95px)"},
        ".cube-face:nth-child(6)": {"background": "hsl(34 70% 42%)", "transform": "rotateX(-90deg) translateZ(95px)"},
        # 面内占位内容：标题 + 4 条信息条 + 角标 glyph
        ".cube-face::after": {
            "content": "''",
            "position": "absolute",
            "inset": "12%",
            "background": "linear-gradient(180deg, rgba(255,255,255,0.28) 0 8%, transparent 8% 22%, rgba(255,255,255,0.18) 22% 30%, transparent 30% 44%, rgba(255,255,255,0.18) 44% 52%, transparent 52% 66%, rgba(255,255,255,0.18) 66% 74%, transparent 74%)",
            "border-radius": "6px",
        },
    },
    "keyframes": {
        "cube-fadein": [
            {"offset": 0, "opacity": 0},
            {"offset": 1, "opacity": 1},
        ],
        # 相机 6 个关键位姿（五段窗口 + hold）：
        #   0–0.10 正面特写 d=235（translateZ 235px）
        #   0.10–0.24 等轴拉远 rx−22/ry−38 d=−130（露三面）
        #   0.30–0.44 右面特写 ry−90
        #   0.50–0.62 等轴 rx−25/ry−52
        #   0.66–0.78 背面特写 ry−180
        #   0.84–0.97 等轴收尾
        # 特写与等轴 d 值差约 365px，推近拉远占透视变化大头
        "cube-rig": [
            {"offset": 0, "transform": "translateZ(235px) rotateX(0deg) rotateY(0deg)"},
            {"offset": 0.1, "transform": "translateZ(235px) rotateX(0deg) rotateY(0deg)"},
            {"offset": 0.24, "transform": "translateZ(-130px) rotateX(-22deg) rotateY(-38deg)"},
            {"offset": 0.3, "transform": "translateZ(-130px) rotateX(-22deg) rotateY(-38deg)"},
            {"offset": 0.44, "transform": "translateZ(235px) rotateX(0deg) rotateY(-90deg)"},
            {"offset": 0.5, "transform": "translateZ(235px) rotateX(0deg) rotateY(-90deg)"},
            {"offset": 0.62, "transform": "translateZ(-130px) rotateX(-25deg) rotateY(-52deg)"},
            {"offset": 0.66, "transform": "translateZ(-130px) rotateX(-25deg) rotateY(-52deg)"},
            {"offset": 0.78, "transform": "translateZ(235px) rotateX(0deg) rotateY(-180deg)"},
            {"offset": 0.84, "transform": "translateZ(235px) rotateX(0deg) rotateY(-180deg)"},
            {"offset": 0.97, "transform": "translateZ(-130px) rotateX(-27deg) rotateY(-45deg)"},
            {"offset": 1, "transform": "translateZ(-130px) rotateX(-27deg) rotateY(-45deg)"},
        ],
        # 法线明暗近似：面转向相机时变亮（brightness 1.12），背离时沉下去（0.5）
        "cube-lit": [
            {"offset": 0, "filter": "brightness(1.12) saturate(1.2)"},
            {"offset": 0.24, "filter": "brightness(0.7) saturate(0.9)"},
            {"offset": 0.44, "filter": "brightness(1.12) saturate(1.2)"},
            {"offset": 0.62, "filter": "brightness(0.7) saturate(0.9)"},
            {"offset": 0.78, "filter": "brightness(1.12) saturate(1.2)"},
            {"offset": 0.97, "filter": "brightness(0.75) saturate(0.95)"},
            {"offset": 1, "filter": "brightness(0.75) saturate(0.95)"},
        ],
    },
})


# ── white-flash-logo-simplify-cut ──────────
# 108f@30fps ≈ 3.6s：静置流光 0–1.2s · 冲白 1.2–1.5s · 扁平定格 1.7–2.7s
# 动效核心：彩色液态渐变字标静置流光（backgroundPosition t*100% + 柔光扫掠 ±30px），
#           一拍冲白过曝（inQuad 加速冲入，blur 0→5px + brightness ×2.2 的 sin 脉冲），
#           白层保持不退，白底上扁平版字标淡入定格（scale 0.96→1）。
# 已知坑：白层是'冲入后保持'不是闪一下回黑；mix-blend-mode:screen 的柔光层
#         在白底上不可见属预期；冲白配 SFX 是必选项（无声白闪读作丢帧）。

_register("white-flash-logo-simplify-cut", {
    "description": "彩色液态渐变字标静置流光，画面一拍冲白过曝，白底上扁平版字标淡入定格——一次闪白完成'质感降维'的品牌收束转场",
    "duration_frames": 108,
    "css": {
        ".scene": {
            "animation": "flash-scene 3.6s ease-in-out forwards",
            "background": "#0a0a12",
            "overflow": "hidden",
            "position": "relative",
        },
        # 液态字标层（62px）：background-size 320%，background-position 全程缓慢流动
        ".liquid-mark": {
            "position": "absolute",
            "left": "50%",
            "top": "42%",
            "transform": "translate(-50%, -50%)",
            "font-size": "62px",
            "font-weight": "800",
            "letter-spacing": "2px",
            "white-space": "nowrap",
            "background": "linear-gradient(90deg, hsl(0 90% 60%), hsl(45 95% 55%), hsl(150 85% 50%), hsl(210 90% 55%), hsl(280 85% 55%), hsl(330 90% 55%), hsl(0 90% 60%))",
            "background-size": "320% 100%",
            "-webkit-background-clip": "text",
            "background-clip": "text",
            "color": "transparent",
            "animation": "liquid-flow 3.6s linear forwards, liquid-burn 3.6s cubic-bezier(0.55, 0.085, 0.68, 0.53) forwards",
            "will-change": "background-position, filter",
        },
        # 柔光扫掠层：220×120 径向柔光 blur 6px + screen 混合，横移 ±30px
        ".liquid-glow": {
            "position": "absolute",
            "left": "50%",
            "top": "42%",
            "width": "220px",
            "height": "120px",
            "transform": "translate(-50%, -50%) translateX(-30px)",
            "background": "radial-gradient(ellipse, rgba(255,255,255,0.75) 0%, rgba(255,255,255,0) 70%)",
            "filter": "blur(6px)",
            "mix-blend-mode": "screen",
            "animation": "glow-sweep 3.6s ease-in-out forwards",
            "opacity": "0.9",
            "pointer-events": "none",
        },
        # 白层：冲入后保持不退（后半场全程白底）
        ".flash-white": {
            "position": "absolute",
            "inset": "0",
            "background": "#ffffff",
            "animation": "flash-white 3.6s cubic-bezier(0.55, 0.085, 0.68, 0.53) forwards",
            "opacity": "0",
            "pointer-events": "none",
        },
        # 扁平字标（58px，比液态略小一号 = 落定收束暗示；GRAD_A/B/C 可换项目品牌三色）
        ".flat-mark": {
            "position": "absolute",
            "left": "50%",
            "top": "42%",
            "transform": "translate(-50%, -50%) scale(0.96)",
            "font-size": "58px",
            "font-weight": "800",
            "letter-spacing": "2px",
            "white-space": "nowrap",
            "background": "linear-gradient(90deg, hsl(224 85% 55%), hsl(268 70% 50%), hsl(330 80% 55%))",
            "-webkit-background-clip": "text",
            "background-clip": "text",
            "color": "transparent",
            "animation": "flat-in 3.6s cubic-bezier(0.215, 0.61, 0.355, 1) forwards",
            "opacity": "0",
            "will-change": "transform, opacity",
        },
    },
    "keyframes": {
        "flash-scene": [
            {"offset": 0, "filter": "brightness(1)"},
            {"offset": 1, "filter": "brightness(1)"},
        ],
        # 液态流光：backgroundPosition = t*100%（0→100% 全程缓动流动）
        "liquid-flow": [
            {"offset": 0, "background-position": "0% 0%"},
            {"offset": 1, "background-position": "100% 0%"},
        ],
        # 过曝脉冲：冲白窗口内 blur 0→5px + brightness 1→2.2（sin 包络 → 峰值一帧）
        # 冲白后液态层被白层盖住，脉冲随白层一起'烧穿'
        "liquid-burn": [
            {"offset": 0, "filter": "brightness(1) blur(0px)"},
            {"offset": 0.34, "filter": "brightness(1) blur(0px)"},
            {"offset": 0.38, "filter": "brightness(1.6) blur(3px)"},
            {"offset": 0.42, "filter": "brightness(2.2) blur(5px)"},
            {"offset": 0.48, "filter": "brightness(1.2) blur(1px)"},
            {"offset": 0.52, "filter": "brightness(1) blur(0px)"},
            {"offset": 1, "filter": "brightness(1) blur(0px)"},
        ],
        # 柔光扫掠：±30px 横移；随冲白同步熄灭（1-flashK），不残留在白底上
        "glow-sweep": [
            {"offset": 0, "transform": "translate(-50%, -50%) translateX(-30px)", "opacity": 0.9},
            {"offset": 0.17, "transform": "translate(-50%, -50%) translateX(30px)", "opacity": 0.9},
            {"offset": 0.34, "transform": "translate(-50%, -50%) translateX(-30px)", "opacity": 0.9},
            {"offset": 0.42, "transform": "translate(-50%, -50%) translateX(0px)", "opacity": 0},
            {"offset": 1, "transform": "translate(-50%, -50%) translateX(0px)", "opacity": 0},
        ],
        # 白层：0.34–0.42 加速冲入（inQuad 快进慢不退），之后保持不退
        "flash-white": [
            {"offset": 0, "opacity": 0},
            {"offset": 0.34, "opacity": 0},
            {"offset": 0.42, "opacity": 1},
            {"offset": 1, "opacity": 1},
        ],
        # 扁平字标：0.48–0.74 淡入 + scale 0.96→1（outCubic）；与冲白间隔 0.06 白屏静默是呼吸位
        "flat-in": [
            {"offset": 0, "opacity": 0, "transform": "translate(-50%, -50%) scale(0.96)"},
            {"offset": 0.48, "opacity": 0, "transform": "translate(-50%, -50%) scale(0.96)"},
            {"offset": 0.74, "opacity": 1, "transform": "translate(-50%, -50%) scale(1)"},
            {"offset": 1, "opacity": 1, "transform": "translate(-50%, -50%) scale(1)"},
        ],
    },
})


# ═══════════════════════════════════════════
# 注册统计
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print(f"shotcraft_transition_v2: 已注册 {len(SHOT_CARD_REGISTRY)} 张转场镜头卡")
    for name, meta in SHOT_CARD_REGISTRY.items():
        print(f"  - {name}: {meta['duration_frames']}f | {meta['description'][:48]}...")
