#!/usr/bin/env python3
"""归档交付包：把 render/ 子目录中的规范产物复制到交付包根目录。

08-13 规范（skill: ai-self-media-tools-pipeline-execution）：
交付包根目录必须含 10 项：
  final.mp4 / cover.jpg|png / platform_source_matrix.json（或 TrendCandidate.json）/
  content_depth_plan.json / scene_manifest.json / bgm_manifest.json /
  tts_config.json + audio/（tts_seg_*.mp3 + bgm.mp3）/
  checkpoint.json / quality_report.json / publish_info.json

用法：
  python3 scripts/archive_delivery_package.py <platform> <YYYYMMDD> [--platform-root data/local_ops_<platform>]
  python3 scripts/archive_delivery_package.py --all <YYYYMMDD>   # 扫描全部平台
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 规范 JSON 候选名（render/ 或包根任一处存在即复制到包根）
JSON_CANDIDATES = {
    "platform_source_matrix.json": ["platform_source_matrix_*.json", "platform_source_matrix.json"],
    "TrendCandidate.json": ["TrendCandidate.json", "trend_candidate.json"],
    "content_depth_plan.json": ["content_depth_plan.json", "content_depth_plan_*.json"],
    "scene_manifest.json": ["scene_manifest.json"],
    "visual_recipe.json": ["visual_recipe.json"],
    "bgm_manifest.json": ["bgm_manifest.json", "bgm_source.json", "bgm_license_manifest.json"],
    "tts_config.json": ["tts_config.json", "tts_records.json", "tts_normalization_report.json"],
    "checkpoint.json": ["checkpoint.json", "render_contract.json", "shot_render_records.json"],
    "quality_report.json": ["quality_report.json", "acceptance_packet.json", "acceptance_report.json", "unified_acceptance*.json"],
    "publish_info.json": ["publish_info.json", "publishing_plan.json", "handoff_package.json"],
    "asset_provenance.json": ["asset_provenance.json", "visual_assets.json"],
    "av_alignment_check.json": ["av_alignment_check.json"],
    "pronunciation_dictionary.json": ["pronunciation_dictionary.json"],
    "version_comparison_report.json": ["version_comparison_report.json"],
}

MEDIA_CANDIDATES = {
    "final.mp4": ["final.mp4", "final_*.mp4"],
    "cover.jpg": ["cover.jpg", "cover.png", "cover_1080x1920.jpg", "cover_1920x1080.jpg"],
    "script.md": ["script_*.md", "script.md", "脚本.md"],
}


def find_first(base: Path, names: list[str], max_depth: int = 1, date_hint: str = "", recursive_dirs: bool = True) -> Path | None:
    """在 base 下找第一个匹配任一 pattern 的文件。

    max_depth=1: 只扫 base 自身 + 一层子目录（render/plan/delivery/assets 常见）。
    date_hint: 若提供（YYYYMMDD），glob pattern 优先带日期，避免跨日期误归档。
    recursive_dirs=False: 只扫 base 顶层，不进入子目录（用于平台根扫描，防兄弟日期目录）。
    """
    # 带日期提示的优先 pattern（platform_source_matrix_<date>.json）
    ordered: list[str] = list(names)
    if date_hint:
        dated = [p.replace("*", f"*{date_hint}*") if "*" in p else p for p in names]
        ordered = dated + [p for p in names if p not in dated]
    for pattern in ordered:
        if "*" in pattern:
            hits = sorted(base.glob(pattern))
            if hits:
                return hits[0]
        else:
            p = base / pattern
            if p.is_file():
                return p
    if max_depth <= 0 or not recursive_dirs:
        return None
    for sub in sorted(base.iterdir()):
        if not sub.is_dir() or sub.name in ("__pycache__", ".git"):
            continue
        # 递归一层（render/ 子目录常见），但禁止跨日期目录
        for pattern in ordered:
            if "*" in pattern:
                hits = sorted(sub.glob(pattern))
                if hits:
                    return hits[0]
            else:
                p = sub / pattern
                if p.is_file():
                    return p
    return None


def archive_platform(platform: str, date_str: str, platform_root: Path, dry_run: bool = False) -> dict:
    pkg_dir = platform_root / date_str
    render_dir = pkg_dir / "render"
    if not pkg_dir.is_dir():
        return {"platform": platform, "date": date_str, "status": "missing_package", "copied": []}
    if not render_dir.is_dir():
        render_dir = pkg_dir  # 无 render 子目录时直接在包根找

    copied: list[str] = []
    missing: list[str] = []

    # 平台目录根的 source matrix 也是候选（08-16 kuaishou 在包外）——必须限定本日期
    platform_extra_dirs = [platform_root]

    # 1. JSON 规范归档
    for target_name, candidates in JSON_CANDIDATES.items():
        target = pkg_dir / target_name
        if target.is_file():
            continue  # 已存在
        source = find_first(pkg_dir, candidates, date_hint=date_str)
        if source is None and render_dir != pkg_dir:
            source = find_first(render_dir, candidates, date_hint=date_str)
        if source is None:
            for extra in platform_extra_dirs:
                if extra != pkg_dir:
                    # 平台根只扫顶层（不递归兄弟日期目录），且必须带本日期
                    source = find_first(extra, candidates, date_hint=date_str, recursive_dirs=False)
                    if source:
                        break
        if source and source != target:
            # 防跨日期误归档：候选源路径必须含本日期或已是规范名
            src_str = str(source)
            if date_str in src_str or src_str.endswith(target_name):
                if not dry_run:
                    shutil.copy2(source, target)
                copied.append(f"{target_name} <- {source.relative_to(ROOT)}")
            else:
                missing.append(f"{target_name} (源跨日期: {source.name})")
        else:
            missing.append(target_name)

    # 2. 媒体归档
    for target_name, candidates in MEDIA_CANDIDATES.items():
        target = pkg_dir / target_name
        if target.is_file():
            continue
        source = find_first(pkg_dir, candidates, date_hint=date_str)
        if source is None and render_dir != pkg_dir:
            source = find_first(render_dir, candidates, date_hint=date_str)
        if source is None:
            for extra in platform_extra_dirs:
                if extra != pkg_dir:
                    source = find_first(extra, candidates, date_hint=date_str, recursive_dirs=False)
                    if source:
                        break
        if source and source != target:
            src_str = str(source)
            if date_str in src_str or src_str.endswith(target_name):
                if not dry_run:
                    shutil.copy2(source, target)
                copied.append(f"{target_name} <- {source.relative_to(ROOT)}")
            else:
                missing.append(f"{target_name} (源跨日期: {source.name})")
        else:
            missing.append(target_name)

    # 3. audio/ 目录（tts_seg_*.mp3 + bgm.mp3）
    audio_dir = pkg_dir / "audio"
    tts_sources = sorted((render_dir or pkg_dir).glob("tts_seg_*.mp3"))
    bgm_sources = list((render_dir or pkg_dir).glob("bgm*.mp3"))
    audio_present = audio_dir.is_dir() and any(audio_dir.iterdir())
    if tts_sources or bgm_sources:
        if not audio_present:
            if not dry_run:
                audio_dir.mkdir(parents=True, exist_ok=True)
                for src in tts_sources:
                    shutil.copy2(src, audio_dir / src.name)
                for src in bgm_sources:
                    shutil.copy2(src, audio_dir / src.name)
            copied.append(f"audio/ ({len(tts_sources)} tts + {len(bgm_sources)} bgm)")
        elif dry_run:
            copied.append("audio/ already present")
    else:
        missing.append("audio/")

    return {
        "platform": platform,
        "date": date_str,
        "status": "ok" if not missing else "partial",
        "copied": copied,
        "missing": missing,
        "dry_run": dry_run,
    }


def archive_delivery_package_direct(output_dir: Path) -> dict:
    """Runner 直接调用入口：自动识别平台与日期并归档规范产物到包根。

    output_dir 为渲染输出目录（通常是 <platform_root>/<YYYYMMDD>/render），
    归档目标是其父目录（交付包根）。
    """
    output_dir = Path(output_dir).resolve()
    pkg_dir = output_dir.parent
    platform_root = pkg_dir.parent
    platform = platform_root.name.replace("local_ops_", "") if platform_root.name.startswith("local_ops_") else platform_root.name
    date_str = pkg_dir.name
    result = archive_platform(platform, date_str, platform_root, dry_run=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", nargs="?", default="")
    parser.add_argument("date", nargs="?", default="")
    parser.add_argument("--all", action="store_true", help="扫描全部 data/local_ops_*")
    parser.add_argument("--platform-root", default="", help="平台目录（默认 data/local_ops_<platform>）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.all:
        results = []
        for pkg in sorted((ROOT / "data").glob("local_ops_*")):
            for date_dir in sorted(pkg.glob("20*")):
                if not date_dir.is_dir():
                    continue
                platform = pkg.name.replace("local_ops_", "")
                if platform in ("gzh", "domestic", "international", "intl_supplement", "wechat_today", "xhs_probe"):
                    continue
                results.append(archive_platform(platform, date_dir.name, pkg, dry_run=args.dry_run))
    elif args.platform and args.date:
        platform_root = Path(args.platform_root) if args.platform_root else ROOT / "data" / f"local_ops_{args.platform}"
        results = [archive_platform(args.platform, args.date, platform_root, dry_run=args.dry_run)]
    else:
        parser.print_help()
        return 2

    for r in results:
        print(f"\n[{r['status']}] {r['platform']}/{r['date']}")
        for c in r["copied"]:
            print(f"  ✅ {c}")
        if r["missing"]:
            print(f"  ⚠️ 仍缺: {', '.join(r['missing'])}")
        if not r["copied"] and not r["missing"]:
            print("  无变更")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
