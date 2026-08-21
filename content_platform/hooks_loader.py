#!/usr/bin/env python3
"""把 content-hooks 钩子库（Markdown）转换为可机器读取的 JSON 资产 + 加载器。

让自动工作流（generator/video_toolchain_runner）无需 Hermes 手动 skill_view
就能读取标题/开场/结尾钩子模板库，自动套用生成爆款标题和脚本开头。
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB_MD = ROOT / "data" / "hooks_library.md"
LIB_JSON = ROOT / "data" / "hooks_library.json"
OUT_MD = ROOT / "data" / "hooks_library.md"


def parse_hooks(md_path: Path) -> dict:
    """解析钩子库 Markdown 表格 → 结构化 JSON"""
    if not md_path.is_file():
        return {}
    text = md_path.read_text(encoding="utf-8", errors="replace")
    hooks = {"title": [], "opening": [], "ending": [], "sections": {}}
    current_section = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## ") and any(k in s for k in ["标题", "开场", "结尾"]):
            current_section = "title" if "标题" in s else ("opening" if "开场" in s else "ending")
            hooks["sections"][current_section] = s[3:].strip()
            continue
        # 表格行
        if s.startswith("|") and not s.startswith("|---") and current_section:
            # 跳过表头 | # | | 和分隔行
            if re.match(r"^\|\s*#\s*\|", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 4 and re.match(r"^[THAE][0-9]", cells[0]):
                # 表头: # | 模板句式 | 平台 | 示例 | 原理
                hook = {
                    "id": cells[0],
                    "name": cells[0],  # 如 "T1 悬念提问式"
                    "template": cells[1],       # 模板句式（真正要套用的）
                    "platforms": cells[2],      # 平台
                    "example": cells[3] if len(cells) > 3 else "",
                    "principle": cells[4] if len(cells) > 4 else "",
                }
                htype = "title" if cells[0].startswith("T") else ("opening" if cells[0].startswith("H") else "ending")
                hook["type"] = htype
                hooks[htype].append(hook)
    # 若解析不到（格式变化），用正则提取
    if not hooks["title"]:
        for m in re.finditer(r"^\|\s*(T\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", text, re.M):
            hooks["title"].append({
                "id": m.group(1), "name": m.group(2).strip(),
                "template": m.group(3).strip(), "platforms": m.group(4).strip(),
            })
    return hooks


def pick_hooks(platform: str, count: int = 3) -> list[dict]:
    """按平台筛选可用钩子（平台匹配或全平台）"""
    lib = load_hooks()
    all_hooks = lib.get("title", []) + lib.get("opening", []) + lib.get("ending", [])
    plat = str(platform or "").casefold()
    matched = []
    for h in all_hooks:
        platforms = str(h.get("platforms", ""))
        # 平台匹配：空/全平台/平台名在列表
        if not platforms or "全平台" in platforms:
            matched.append(h)
        elif plat and plat in platforms.casefold():
            matched.append(h)
    if not matched:
        # 兜底全平台钩子优先
        matched = [h for h in all_hooks if not str(h.get("platforms", "")) or "全平台" in str(h.get("platforms", ""))][:count]
    return matched[:count]


_CACHE = None


def load_hooks() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    if LIB_JSON.is_file():
        try:
            _CACHE = json.loads(LIB_JSON.read_text(encoding="utf-8"))
            return _CACHE
        except Exception:
            pass
    _CACHE = parse_hooks(LIB_MD)
    LIB_JSON.write_text(json.dumps(_CACHE, ensure_ascii=False, indent=1), encoding="utf-8")
    return _CACHE


def sync_library(hook_md_path: Path):
    """从 Hermes skill 钩子库同步到项目 data/hooks_library.md"""
    if not hook_md_path.is_file():
        return False
    content = hook_md_path.read_text(encoding="utf-8", errors="replace")
    OUT_MD.write_text(content, encoding="utf-8")
    return True


if __name__ == "__main__":
    # 从 Hermes skill 同步
    hermes_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()
    hermes_hooks = hermes_home / "skills/content/content-hooks/references/hook-template-library.md"
    hermes_2026 = hermes_home / "skills/content/content-hooks/references/2026-title-formulas-and-structures.md"
    if hermes_hooks.is_file():
        sync_library(hermes_hooks)
        print("已同步 hook-template-library.md")
    if hermes_2026.is_file():
        combined = OUT_MD.read_text(encoding="utf-8") + "\n\n" + hermes_2026.read_text(encoding="utf-8")
        OUT_MD.write_text(combined, encoding="utf-8")
        print("已合并 2026-title-formulas")
    lib = load_hooks()
    print("钩子库加载:", {k: len(v) for k, v in lib.items() if isinstance(v, list)})
    print("抖音可用标题钩子样:", pick_hooks("douyin", 3))
