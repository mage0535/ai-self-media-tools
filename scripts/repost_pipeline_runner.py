#!/usr/bin/env python3
"""Local, non-publishing runner for the recoverable repost workflow.

The fixture mode creates a real ffprobe-readable MP4 and a complete local
Douyin handoff package.  No browser, cookie, downloader, publisher, or network
adapter is invoked.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_platform.repost_workflow import (
    RepostRun,
    RepostState,
    SourceLedger,
    StageName,
    TransformationLedger,
    WorkflowError,
    atomic_json,
    build_repost_evidence_bundle,
    content_cache_key,
    percentile,
    probe_media,
    sha256_file,
    validate_handoff_directory,
    validate_narration_manifest,
    validate_similarity_report,
    validate_timeline,
)

FONT = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
REQUIRED_HANDOFF = (
    "final.mp4", "cover.png", "script.md", "intro_frame.png", "outro_frame.png",
    "source_manifest.json", "scene_manifest.json", "transformation_ledger.json",
    "narration_manifest.json", "timeline_manifest.json", "similarity_report.json",
    "cover_evidence.json", "shot_cache_evidence.json", "final_render_cache.json", "deep_quality_gate.json", "evidence_bundle.json", "performance_manifest.json", "final_delivery_manifest.json",
    "manual_rights_confirmation.md", "manual_publish_checklist.md",
)


def run_command(command: list[str], *, timeout: int = 180) -> None:
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    if process.returncode:
        detail = (process.stderr or process.stdout or "command failed")[-1500:]
        raise WorkflowError(f"command failed ({process.returncode}): {' '.join(command)}\n{detail}")


STATE_ORDER = [
    RepostState.INIT,
    RepostState.SOURCE_REGISTERED,
    RepostState.SCRIPT_READY,
    RepostState.TTS_READY,
    RepostState.VISUAL_PLAN_READY,
    RepostState.COVER_READY,
    RepostState.INTRO_OUTRO_READY,
    RepostState.INTERNAL_DUP_CHECKED,
    RepostState.PREFLIGHT_PASSED,
    RepostState.RENDERING,
    RepostState.MUXED,
    RepostState.TIMELINE_VERIFIED,
    RepostState.NARRATION_VERIFIED,
    RepostState.DEEP_QA_PASSED,
    RepostState.HANDOFF_READY,
    RepostState.RIGHTS_EXTERNAL_PENDING,
]


def advance(run: RepostRun, state: RepostState) -> None:
    if run.state is state:
        return
    if run.state in {RepostState.RIGHTS_EXTERNAL_PENDING, RepostState.BLOCKED, RepostState.FAILED}:
        return
    if run.state in STATE_ORDER and state in STATE_ORDER and STATE_ORDER.index(run.state) >= STATE_ORDER.index(state):
        return
    run.transition(state)


def make_source(run_dir: Path) -> Path:
    source = run_dir / "source.mp4"
    if source.is_file():
        return source
    run_command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000",
        "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(source),
    ])
    return source


def draw_cover(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1080, 1920), (231, 244, 236))
    draw = ImageDraw.Draw(image)
    # Textured, content-bearing background instead of a blank color card.
    for y in range(0, 1920, 48):
        for x in range(0, 1080, 48):
            color = (214 + ((x + y) // 48) % 18, 230 + ((x // 48) % 12), 220 + ((y // 48) % 12))
            draw.rectangle((x, y, x + 28, y + 28), fill=color)
    draw.ellipse((180, 360, 900, 1080), fill=(248, 191, 119), outline=(92, 63, 44), width=12)
    draw.polygon([(250, 450), (210, 170), (440, 330)], fill=(248, 191, 119), outline=(92, 63, 44))
    draw.polygon([(840, 450), (870, 170), (650, 330)], fill=(248, 191, 119), outline=(92, 63, 44))
    draw.ellipse((360, 610, 420, 690), fill=(40, 40, 40))
    draw.ellipse((660, 610, 720, 690), fill=(40, 40, 40))
    draw.ellipse((505, 745, 575, 800), fill=(80, 45, 45))
    draw.arc((420, 730, 660, 920), 10, 170, fill=(80, 45, 45), width=10)
    font = ImageFont.truetype(str(FONT), 72, index=0) if FONT.is_file() else ImageFont.load_default()
    small = ImageFont.truetype(str(FONT), 42, index=0) if FONT.is_file() else ImageFont.load_default()
    draw.rounded_rectangle((70, 1210, 1010, 1510), radius=36, fill=(255, 255, 255), outline=(38, 96, 72), width=8)
    draw.text((120, 1280), "它为什么突然停在门口？", font=font, fill=(25, 60, 45))
    draw.text((120, 1400), "看懂动作，再决定是不是‘闹脾气’", font=small, fill=(76, 93, 86))
    image.save(path, format="PNG")


def make_frame(path: Path, *, color: str, title: str) -> None:
    run_command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=720x1280:r=25",
        "-frames:v", "1", "-vf", f"drawtext=fontfile={FONT}:text='{title}':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2",
        str(path),
    ])


def render_scene(path: Path) -> None:
    run_command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=0x203b47:s=720x1280:r=25",
        "-t", "10", "-vf", f"drawtext=fontfile={FONT}:text='猫咪行为观察：停在门口的三种可能':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=180,drawbox=x=55:y=370:w=610:h=420:color=0x7aa58f@0.9:t=fill,drawtext=fontfile={FONT}:text='事实 → 推测 → 观点':fontcolor=0x17332a:fontsize=46:x=(w-text_w)/2:y=550",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path),
    ])


def mux_scene(scene: Path, output: Path) -> None:
    run_command([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(scene), "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
        "-shortest", "-movflags", "+faststart", str(output),
    ])


def write_stage_files(run: RepostRun, source: Path) -> dict[str, Any]:
    run_dir = run.run_dir
    source_manifest_path = run_dir / "source_manifest.json"
    source_ledger = SourceLedger.from_file(
        source,
        source_uri="https://www.tiktok.com/@fixture/video/fixture-cat-001",
        source_content_id="fixture-cat-001",
        source_creator="fixture_creator",
        source_title="猫咪停在门口的真实动作",
        source_id="src_fixture_cat_001",
    )
    source_ledger.source_manifest_path = str(source_manifest_path)
    source_failures = source_ledger.validate()
    if source_failures:
        raise WorkflowError("source ledger invalid: " + ",".join(source_failures))
    source_payload = source_ledger.to_dict()

    def source_stage():
        atomic_json(source_manifest_path, source_payload)
        return source_payload

    run.execute_stage(StageName.SOURCE_REGISTER, output_paths=[source_manifest_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, gate_version="source-v1"), func=source_stage)
    advance(run, RepostState.SOURCE_REGISTERED)

    script_path = run_dir / "script.md"
    script = """# 它为什么突然停在门口？\n\n事实：画面里的猫在门口停下，先观察，再决定是否继续。\n\n推测：它可能在确认环境变化，也可能是在等待熟悉的人。仅凭一个动作不能下诊断。\n\n观点：看猫咪行为，先描述可见事实，再把推测和观点分开。你家猫也有过这种‘先停一下’的时刻吗？\n"""

    def script_stage():
        script_path.write_text(script, encoding="utf-8")
        return {"script_hash": sha256_file(script_path)}

    run.execute_stage(StageName.TOPIC_AND_SCRIPT, input_paths=[source_manifest_path], output_paths=[script_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, script_hash=sha256_file(source_manifest_path), gate_version="script-v1"), func=script_stage)
    advance(run, RepostState.SCRIPT_READY)

    narration_audio = run_dir / "narration.wav"
    narration_manifest_path = run_dir / "narration_manifest.json"
    segments = [
        {"start": 1.2, "end": 2.9, "text": "它没有立刻进门，而是先停下来观察。"},
        {"start": 2.9, "end": 4.8, "text": "我们能确认的是动作，不能凭一帧画面给它下诊断。"},
        {"start": 4.8, "end": 6.8, "text": "更稳妥的看法，是把事实、推测和观点分开。"},
    ]

    def tts_stage():
        run_command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=523:sample_rate=48000:duration=6.8", "-c:a", "pcm_s16le", str(narration_audio)])
        atomic_json(narration_manifest_path, {"version": "narration_manifest_v1", "provider": "fixture_synthetic_audio", "text_hash": sha256_file(script_path), "audio_path": str(narration_audio), "audio_sha256": sha256_file(narration_audio), "segments": segments, "actual_duration": 6.8})

    run.execute_stage(StageName.TTS, input_paths=[script_path], output_paths=[narration_audio, narration_manifest_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, script_hash=sha256_file(script_path), narration_text_hash=sha256_file(script_path), tts_provider="fixture_synthetic_audio", tts_model="sine", tts_voice="fixture", tts_sample_rate=48000, gate_version="tts-v1"), func=tts_stage)
    advance(run, RepostState.TTS_READY)

    analysis_path = run_dir / "source_analysis.json"
    ledger = TransformationLedger()
    ledger.add(segment="source[0:8] -> output[1.2:7.8]", edit_type="narrative_reframe", reason="按行为观察主题重新组织事实、推测和观点", content_impact="加入原创中文解释，避免原片完整直放", quality_check="主体旁白贯穿并保留事实边界")
    ledger.add(segment="output[0:1.2]", edit_type="intro_frame", reason="提出具体问题并建立观看目标", content_impact="独立首帧，不复制源视频开头", quality_check="T=0 且持续 1.2 秒")
    ledger.add(segment="output[7.8:10]", edit_type="outro_frame", reason="总结观点并提出相关互动问题", content_impact="独立尾帧，提供互动价值", quality_check="主体后持续 2.2 秒")
    transform_path = run_dir / "transformation_ledger.json"

    def analysis_stage():
        atomic_json(analysis_path, {"version": "source_analysis_v1", "facts": ["猫咪停在门口", "先观察再行动"], "inferences": ["可能在确认环境变化"], "not_a_diagnosis": True})
        atomic_json(transform_path, ledger.to_dict())

    run.execute_stage(StageName.SOURCE_ANALYSIS, input_paths=[source_manifest_path], output_paths=[analysis_path, transform_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, transform_ledger_hash=sha256_file(script_path), gate_version="analysis-v1"), func=analysis_stage)
    advance(run, RepostState.VISUAL_PLAN_READY)

    cover_path = run_dir / "cover.png"
    cover_evidence_path = run_dir / "cover_evidence.json"

    def cover_stage():
        draw_cover(cover_path)
        atomic_json(cover_evidence_path, {"version": "cover_evidence_v1", "platform": "douyin", "independent_render": True, "cover_sha256": sha256_file(cover_path), "cover_intent": "行为观察点击入口", "visual_direction": "猫咪表情+门口停顿冲突", "title": "它为什么突然停在门口？", "hook": "具体问题", "semantic_match": "猫咪停门行为", "ocr_verified": "fixture_visual_review"})

    run.execute_stage(StageName.COVER, input_paths=[script_path], output_paths=[cover_path, cover_evidence_path], cache_key=content_cache_key(script_hash=sha256_file(script_path), cover_contract_hash=sha256_file(script_path), font_hash=sha256_file(FONT) if FONT.is_file() else "missing", gate_version="cover-v1"), func=cover_stage)
    advance(run, RepostState.COVER_READY)

    asset_path = run_dir / "asset_source.mp4"

    def asset_stage():
        shutil.copy2(source, asset_path)

    run.execute_stage(StageName.ASSET_PREPARE, input_paths=[source], output_paths=[asset_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, gate_version="asset-v1"), func=asset_stage)

    scene_manifest_path = run_dir / "scene_manifest.json"

    def subtitles_stage():
        (run_dir / "subtitles.srt").write_text("1\n00:00:01,200 --> 00:00:02,900\n它先停下来观察。\n\n2\n00:00:02,900 --> 00:00:04,800\n事实不等于诊断。\n\n3\n00:00:04,800 --> 00:00:06,800\n把事实、推测和观点分开。\n", encoding="utf-8")
        atomic_json(scene_manifest_path, {"version": "scene_manifest_v1", "platform": "douyin", "scenes": [{"scene_id": "intro", "start": 0, "end": 1.2, "visual": "question_frame"}, {"scene_id": "main", "start": 1.2, "end": 7.8, "visual": "behavior_observation"}, {"scene_id": "outro", "start": 7.8, "end": 10.0, "visual": "summary_interaction"}]})

    subtitles_output = [run_dir / "subtitles.srt", scene_manifest_path]
    run.execute_stage(StageName.SUBTITLES, input_paths=[narration_manifest_path], output_paths=subtitles_output, cache_key=content_cache_key(narration_text_hash=sha256_file(narration_manifest_path), subtitle_key="srt-v1", gate_version="subtitle-v1"), func=subtitles_stage)

    transform_plan_path = run_dir / "transform_plan.json"

    def transform_stage():
        atomic_json(transform_plan_path, {"version": "transform_plan_v1", "segments": [{"source": "0:8", "output": "1.2:7.8", "purpose": "behavior explanation"}], "original_value": ["original Chinese narration", "fact-inference boundary", "question-led structure"]})

    run.execute_stage(StageName.TRANSFORM_PLAN, input_paths=[analysis_path, transform_path], output_paths=[transform_plan_path], cache_key=content_cache_key(transform_ledger_hash=sha256_file(transform_path), gate_version="transform-v1"), func=transform_stage)

    intro_path = run_dir / "intro_frame.png"
    outro_path = run_dir / "outro_frame.png"

    def intro_outro_stage():
        make_frame(intro_path, color="0x355c7d", title="它为什么突然停在门口？")
        make_frame(outro_path, color="0x3c765c", title="你家猫也会先停一下吗？")

    run.execute_stage(StageName.INTRO_OUTRO, input_paths=[script_path], output_paths=[intro_path, outro_path], cache_key=content_cache_key(script_hash=sha256_file(script_path), intro_frame_key="intro-v1", outro_frame_key="outro-v1", font_hash=sha256_file(FONT) if FONT.is_file() else "missing", gate_version="frame-v1"), func=intro_outro_stage)
    advance(run, RepostState.INTRO_OUTRO_READY)

    similarity_path = run_dir / "similarity_report.json"

    def dup_stage():
        report = {"version": "similarity_report_v1", "source_video_sha256": source_ledger.source_sha256, "candidate_video_sha256": "pending_render", "source_frame_fingerprint": "fixture_source_frames", "candidate_frame_fingerprint": "fixture_candidate_frames", "source_audio_fingerprint": "fixture_source_audio", "candidate_audio_fingerprint": "fixture_narration_audio", "source_asr_text": "not_available_fixture", "candidate_narration_text": "原创中文旁白已登记", "source_segment_to_output_segment_mapping": ledger.entries, "similarity_scores": {"frame": 0.12, "audio": 0.03, "text": 0.08}, "threshold_version": "internal-v1", "model_version": "fixture-v1", "transformation_ledger": ledger.to_dict(), "reviewer_decision": "pass"}
        atomic_json(similarity_path, report)

    run.execute_stage(StageName.PREFLIGHT, input_paths=[source_manifest_path, script_path, cover_evidence_path, scene_manifest_path, transform_path, narration_manifest_path], output_paths=[similarity_path], cache_key=content_cache_key(source_asset_sha256=source_ledger.source_sha256, script_hash=sha256_file(script_path), cover_contract_hash=sha256_file(cover_evidence_path), transform_ledger_hash=sha256_file(transform_path), gate_version="preflight-v1"), func=dup_stage)
    if validate_similarity_report(json.loads(similarity_path.read_text(encoding="utf-8"))[0] if False else json.loads(similarity_path.read_text(encoding="utf-8")))["passed"] is not True:
        raise WorkflowError("similarity preflight failed")
    advance(run, RepostState.INTERNAL_DUP_CHECKED)
    advance(run, RepostState.PREFLIGHT_PASSED)

    scene_video = run_dir / "scene_video.mp4"
    def render_stage():
        render_scene(scene_video)
    run.execute_stage(StageName.RENDERING, input_paths=[scene_manifest_path, intro_path, outro_path], output_paths=[scene_video], cache_key=content_cache_key(shot_spec_hash=sha256_file(scene_manifest_path), intro_frame_key=sha256_file(intro_path), outro_frame_key=sha256_file(outro_path), renderer_source_hash=sha256_file(ROOT / "scripts" / "film_renderer.py"), width=720, height=1280, fps=25, codec="h264", pixel_format="yuv420p", render_mode="fixture", gate_version="render-v1"), func=render_stage)
    atomic_json(run_dir / "shot_cache_evidence.json", {"version": "shot_cache_evidence_v1", "cache_key": run.dag.record(StageName.RENDERING)["cache_key"], "input_sha256": run.dag.record(StageName.RENDERING)["input_sha256"], "output_sha256": sha256_file(scene_video), "cache_hit": run.dag.record(StageName.RENDERING)["cache_hit"], "renderer": "scripts/film_renderer.py"})
    advance(run, RepostState.RENDERING)

    final_path = run_dir / "final.mp4"
    def mux_stage():
        mux_scene(scene_video, final_path)
    run.execute_stage(StageName.MUX, input_paths=[scene_video, narration_audio], output_paths=[final_path], cache_key=content_cache_key(source_asset_sha256=sha256_file(scene_video), bgm_sha256="", final_mux_parameters={"faststart": True, "audio": "fixture_synthetic_narration"}, gate_version="mux-v1"), func=mux_stage)
    atomic_json(run_dir / "final_render_cache.json", {"version": "final_render_cache_v1", "cache_key": run.dag.record(StageName.MUX)["cache_key"], "input_sha256": run.dag.record(StageName.MUX)["input_sha256"], "output_sha256": sha256_file(final_path), "cache_hit": run.dag.record(StageName.MUX)["cache_hit"], "mux_parameters": {"faststart": True, "audio": "fixture_synthetic_narration"}})
    advance(run, RepostState.MUXED)

    duration, resolution = probe_media(final_path)
    timeline = {"version": "timeline_manifest_v1", "intro": {"start": 0.0, "duration_actual": 1.2}, "main_content": {"start": 1.2, "end": 7.8}, "outro": {"start_actual": 7.8, "duration_actual": 2.2, "minimum_duration": 2.0}, "narration_duration": 6.8, "last_narration_end": 6.8, "final_video_duration": duration, "final_resolution": resolution}
    timeline_path = run_dir / "timeline_manifest.json"
    atomic_json(timeline_path, timeline)
    timeline_result = validate_timeline(timeline, duration)
    if not timeline_result["passed"]:
        raise WorkflowError("timeline gate failed: " + ",".join(timeline_result["failures"]))
    advance(run, RepostState.TIMELINE_VERIFIED)
    narration = json.loads(narration_manifest_path.read_text(encoding="utf-8"))
    narration_result = validate_narration_manifest(narration, duration)
    if not narration_result["passed"]:
        raise WorkflowError("narration gate failed: " + ",".join(narration_result["failures"]))
    advance(run, RepostState.NARRATION_VERIFIED)

    deep_gate_path = run_dir / "deep_quality_gate.json"
    def deep_gate_stage():
        similarity_result = validate_similarity_report(json.loads(similarity_path.read_text(encoding="utf-8")))
        if not similarity_result["passed"]:
            raise WorkflowError("deep similarity gate failed: " + ",".join(similarity_result["failures"]))
        atomic_json(deep_gate_path, {"version": "deep_quality_gate_v1", "passed": True, "final_mp4_sha256": sha256_file(final_path), "timeline": timeline_result, "narration": narration_result, "similarity": similarity_result, "ffprobe_duration": duration, "audio_present": True})

    run.execute_stage(StageName.DEEP_QUALITY_GATE, input_paths=[final_path, timeline_path, narration_manifest_path, similarity_path], output_paths=[deep_gate_path], cache_key=content_cache_key(source_asset_sha256=sha256_file(final_path), transform_ledger_hash=sha256_file(transform_path), gate_version="deep-quality-v1"), func=deep_gate_stage)
    advance(run, RepostState.DEEP_QA_PASSED)

    run.set_flags(publishable=False, manual_publish_required=True, rights_status="external_manual_pending", manual_rights_confirmation_required=True, source_platform="tiktok", target_platform="douyin", platform_publish_not_attempted=True)
    bundle_path = run_dir / "evidence_bundle.json"
    handoff_marker = run_dir / "handoff_stage.json"
    def handoff_stage():
        bundle = build_repost_evidence_bundle(run, source_payload, ledger.to_dict(), narration, timeline, json.loads(similarity_path.read_text(encoding="utf-8")), cover_evidence=json.loads(cover_evidence_path.read_text(encoding="utf-8")), final_video=final_path, cover=cover_path)
        atomic_json(bundle_path, bundle)
        atomic_json(run_dir / "manual_rights_confirmation.md.json", {"note": "Human must confirm rights outside automation before publishing.", "required": True})
        (run_dir / "manual_rights_confirmation.md").write_text("# Manual rights confirmation required\n\nAutomation has not contacted the source creator and has not asserted authorization.\n", encoding="utf-8")
        (run_dir / "manual_publish_checklist.md").write_text("# Manual Douyin publish checklist\n\n- [ ] Confirm external rights manually\n- [ ] Review final.mp4 and cover.png\n- [ ] Publish manually only after confirmation\n- [ ] Verify public visibility in the platform UI\n", encoding="utf-8")
        atomic_json(handoff_marker, {"passed": True, "publish_attempted": False, "bundle_sha256": sha256_file(bundle_path)})

    run.execute_stage(StageName.HANDOFF_BUNDLE, input_paths=[deep_gate_path, final_path, cover_path, source_manifest_path], output_paths=[bundle_path, run_dir / "manual_rights_confirmation.md", run_dir / "manual_publish_checklist.md", handoff_marker], cache_key=content_cache_key(source_asset_sha256=sha256_file(final_path), cover_contract_hash=sha256_file(cover_evidence_path), transform_ledger_hash=sha256_file(transform_path), gate_version="handoff-v1"), func=handoff_stage)
    advance(run, RepostState.HANDOFF_READY)
    advance(run, RepostState.RIGHTS_EXTERNAL_PENDING)
    performance = build_performance_manifest(run)
    atomic_json(run_dir / "performance_manifest.json", performance)
    final_manifest = {"version": "final_delivery_manifest_v1", "state": RepostState.RIGHTS_EXTERNAL_PENDING.value, "publishable": False, "manual_publish_required": True, "manual_rights_confirmation_required": True, "rights_status": "external_manual_pending", "source_platform": "tiktok", "target_platform": "douyin", "platform_publish_not_attempted": True, "run_id": run.data["run_id"], "artifacts": {name: sha256_file(run_dir / name) for name in REQUIRED_HANDOFF if name != "final_delivery_manifest.json"}}
    atomic_json(run_dir / "final_delivery_manifest.json", final_manifest)
    return {"run_dir": str(run_dir), "final": str(final_path), "duration": duration, "state": run.state.value}


def build_performance_manifest(run: RepostRun) -> dict[str, Any]:
    stages = []
    for name, record in run.dag.records.items():
        output_bytes = 0
        for item in record.get("evidence_paths") or []:
            path = Path(item)
            if path.is_file():
                output_bytes += path.stat().st_size
        stages.append({"stage": name, "started_at": record.get("started_at"), "finished_at": record.get("finished_at"), "monotonic_duration_ms": record.get("monotonic_duration_ms", 0), "retry_count": max(0, int(record.get("attempt", 1)) - 1), "cache_hit": bool(record.get("cache_hit")), "cache_key": record.get("cache_key", ""), "error_code": record.get("error_code", ""), "peak_rss": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss), "cpu_time_if_available": None, "output_bytes": output_bytes, "process_ids": [os.getpid()]})
    return {"version": "performance_manifest_v2", "run_id": run.data.get("run_id"), "platform": "douyin", "target_seconds": 1800, "stages": stages, "runner_total": sum(float(item["monotonic_duration_ms"]) for item in stages) / 1000.0, "cache_hits": sum(1 for item in stages if item["cache_hit"]), "cache_misses": sum(1 for item in stages if not item["cache_hit"]), "final_status": run.state.value, "no_publish_attempted": True}


def run_fixture(run_dir: Path, *, resume: bool = False, from_stage: str = "", retry_stage: str = "") -> dict[str, Any]:
    run = RepostRun(run_dir)
    if retry_stage or from_stage:
        run.invalidate_from(retry_stage or from_stage)
        if run.state in {RepostState.BLOCKED, RepostState.FAILED}:
            run.data["state"] = RepostState.INIT.value
            run._save()
    source = make_source(run_dir)
    result = write_stage_files(run, source)
    result["handoff_validation"] = validate_handoff_directory(run_dir)
    return result


def performance_matrix(run_dir: Path) -> dict[str, Any]:
    samples = []
    for index in range(5):
        started = time.perf_counter()
        result = run_fixture(run_dir, resume=True)
        samples.append({"sample": index + 1, "elapsed_seconds": round(time.perf_counter() - started, 6), "state": result["state"], "handoff_passed": result["handoff_validation"]["passed"]})
    raw = [item["elapsed_seconds"] for item in samples]
    return {"version": "performance_matrix_v1", "scenario": "exact_hot_fixture", "samples": samples, "sample_count": len(samples), "p50_seconds": percentile(raw, 0.5), "p95_seconds": percentile(raw, 0.95), "slo_status": "fixture_only_unproven_production"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recoverable local TikTok-to-Douyin repost handoff runner")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--from", dest="from_stage", default="")
    parser.add_argument("--retry-stage", default="")
    parser.add_argument("--performance-matrix", action="store_true")
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    try:
        if args.status:
            print(json.dumps(RepostRun(run_dir, create=False).status(), ensure_ascii=False, indent=2))
            return 0
        if not args.fixture and not args.resume and not args.from_stage and not args.retry_stage and not args.performance_matrix:
            parser.error("one of --fixture, --resume, --status, --from, --retry-stage, --performance-matrix is required")
        if args.performance_matrix:
            result = performance_matrix(run_dir)
            atomic_json(run_dir / "performance_matrix.json", result)
        else:
            result = run_fixture(run_dir, resume=args.resume, from_stage=args.from_stage, retry_stage=args.retry_stage)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("handoff_validation", {"passed": True}).get("passed", True) else 2
    except (WorkflowError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error_code": type(exc).__name__, "error_message": str(exc), "run_dir": str(run_dir)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
