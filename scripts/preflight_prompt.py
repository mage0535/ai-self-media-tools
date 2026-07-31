#!/usr/bin/env python3
"""
Prompt 质量门禁 — 生成前验证 prompt 是否包含必要要素

用法:
  python3 preflight_prompt.py --prompt "A cat on a desk..." --type image
  python3 preflight_prompt.py --prompt "写一封邮件..." --type copy

退出码: 0=通过, 1=不通过
"""
import argparse, re, sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 各类型的必要要素关键词
REQUIRED = {
    "image": {
        "label": "生图",
        "elements": {
            "主体/Subject": ["cat", "dog", "person", "man", "woman", "robot", "chip", "computer",
                          "laptop", "desk", "office", "city", "mountain", "forest", "ocean",
                          "flower", "food", "car", "phone", "screen", "code", "device",
                          "hand", "eye", "face", "building", "room", "interior", "product",
                          "circuit", "server", "chip", "glowing", "portrait",
                          "猫", "狗", "人", "电脑", "书桌", "桌子", "手机", "办公室",
                          "城市", "山", "森林", "花", "食物", "车", "建筑", "房间"],
            "环境/Environment": ["in", "on", "at", "studio", "outdoor", "indoor", "nature",
                             "background", "setting", "surrounded", "scene", "location",
                             "workspace", "desk", "table", "floor", "street", "park",
                             "在", "里", "上", "中", "环境", "背景", "室内", "户外", "自然"],
            "光线/Lighting": ["lighting", "light", "sunlight", "golden hour", "neon", "soft",
                          "ambient", "backlight", "moody", "bright", "dim", "warm",
                          "cool", "natural light", "studio lighting", "dramatic",
                          "光线", "阳光", "灯光", "暖光", "自然光", "柔和", "明亮", "黄昏"],
            "风格/Style": ["style", "photorealistic", "cinematic", "minimal", "vintage",
                       "modern", "abstract", "macro", "wide angle", "portrait",
                       "landscape", "8k", "photography", "illustration", "render",
                       "3d", "sketch", "art", "magazine", "professional",
                       "风格", "写实", "摄影", "插画", "电影感", "3D", "渲染"],
            "构图/Composition": ["shot", "close-up", "wide", "angle", "view", "perspective",
                            "composition", "frame", "foreground", "background",
                            "depth of field", "focus", "centered", "rule of thirds",
                            "构图", "特写", "广角", "俯视", "视角", "景深"],
        }
    },
    "copy": {
        "label": "文案",
        "elements": {
            "角色/Role": ["act as", "you are", "as a", "copywriter", "writer", "expert",
                       "specialist", "consultant", "advisor", "marketer"],
            "上下文/Context": ["audience", "target", "for", "selling", "promoting", "audience",
                          "customer", "reader", "user", "client"],
            "任务/Task": ["write", "create", "generate", "draft", "compose", "produce",
                      "develop", "craft"],
            "框架/Framework": ["PAS", "AIDA", "BAB", "framework", "structure", "formula",
                           "problem", "solution", "attention", "interest", "action",
                           "before", "after", "bridge"],
            "约束/Constraints": ["words", "tone", "style", "keep it", "under", "within",
                            "maximum", "format", "不包括", "不要", "语气", "字以内"],
        }
    },
    "video": {
        "label": "视频脚本",
        "elements": {
            "钩子/Hook": ["hook", "attention", "吸引", "开头", "前3秒", "first 3",
                       "grab", "stop"],
            "框架/Framework": ["PAS", "AIDA", "hook", "problem", "solution", "story",
                           "教程", "种草", "观点", "hook"],
            "平台/Platform": ["douyin", "tiktok", "bilibili", "youtube", "kuaishou",
                          "小红书", "视频号", "shorts", "reels"],
            "约束/Constraints": ["秒", "seconds", "时长", "口语", "tone", "语气"],
        }
    }
}

def check_prompt(prompt: str, ptype: str) -> tuple[bool, list[str]]:
    """检查 prompt 是否包含必要要素"""
    if ptype not in REQUIRED:
        return True, ["未知类型，跳过检查"]

    prompt_lower = prompt.lower()
    rules = REQUIRED[ptype]
    missing = []

    for elem_name, keywords in rules["elements"].items():
        found = any(kw.lower() in prompt_lower for kw in keywords)
        if not found:
            missing.append(elem_name)

    total = len(rules["elements"])
    found = total - len(missing)
    score = found / total * 100

    return score >= 60, [
        f"[{rules['label']}] 要素覆盖: {found}/{total} ({score:.0f}%)",
        f"  通过线: ≥60%",
    ] + ([f"  ❌ 缺失: {', '.join(missing)}"] if missing else ["  ✅ 全部要素齐备"])

def main():
    parser = argparse.ArgumentParser(description="Prompt 质量门禁")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--type", choices=["image", "copy", "video"], default="image")
    args = parser.parse_args()

    ok, lines = check_prompt(args.prompt, args.type)
    for l in lines:
        print(l)

    if not ok:
        print(f"\n❌ 不通过 — prompt 缺少必要要素，请补充后再生成")
        sys.exit(1)
    print(f"\n✅ 通过")
    sys.exit(0)

if __name__ == "__main__":
    main()
