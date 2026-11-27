"""Unit tests for RTX NVENC encoder selection, Vulkan Chromium GPU args,
HyperFrames/Remotion deterministic spring runtime, and word-level kinetic ASS subtitles."""

from unittest.mock import patch

from content_platform import normal_film_audio as nfa
from content_platform import video_gpu_motion as vgm


def test_video_encoder_args_prefers_nvenc_when_probe_succeeds_and_falls_back_to_libx264(monkeypatch):
    vgm.clear_hwaccel_cache()
    monkeypatch.setenv("FILM_HWACCEL", "auto")
    with patch.object(vgm, "_probe_nvenc_profile", return_value=True):
        args = vgm.video_encoder_args(crf=20, preset="medium", profile="baseline")
    assert "-c:v" in args and args[args.index("-c:v") + 1] == "h264_nvenc"
    assert args[args.index("-profile:v") + 1] == "baseline"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"

    # Explicit CPU override must force libx264 even if NVENC probe would succeed.
    cpu_args = vgm.video_encoder_args(crf=21, preset="medium", profile="baseline", mode="cpu")
    assert cpu_args[cpu_args.index("-c:v") + 1] == "libx264"
    assert cpu_args[cpu_args.index("-crf") + 1] == "21"

    # Automatic fallback to libx264 when NVENC probe fails.
    with patch.object(vgm, "_probe_nvenc_profile", return_value=False):
        fb_args = vgm.video_encoder_args(crf=20, preset="medium", profile="baseline", mode="auto")
    assert fb_args[fb_args.index("-c:v") + 1] == "libx264"


def test_chromium_launch_args_respects_gpu_presence_and_off_override():
    assert vgm.chromium_launch_args(mode="off") == ["--no-sandbox"]
    vk = vgm.chromium_launch_args(mode="vulkan")
    assert "--use-gl=angle" in vk
    assert "--use-angle=vulkan" in vk
    assert "--enable-features=Vulkan" in vk
    assert "--ignore-gpu-blocklist" in vk


def test_inject_kinetic_runtime_is_idempotent_and_exposes_hyperframes_and_remotion_primitives():
    html = "<!DOCTYPE html><html><body><div data-start='0.2'>hi</div></body></html>"
    once = vgm.inject_kinetic_runtime(html)
    twice = vgm.inject_kinetic_runtime(once)
    assert once == twice
    assert "window.__spring" in once
    assert "window.__interpolate" in once
    assert "window.__seekFrame" in once
    assert "data-start" in once
    assert once.endswith("</body></html>")


def test_timed_caption_cues_preserves_word_boundaries_and_builds_kinetic_ass():
    text = "两只高智商猫会合作开柜子"
    words = [
        {"word": "两只", "start": 0.0, "end": 0.35},
        {"word": "高智商", "start": 0.35, "end": 0.85},
        {"word": "猫会", "start": 0.85, "end": 1.25},
        {"word": "合作", "start": 1.25, "end": 1.65},
        {"word": "开柜子", "start": 1.65, "end": 2.20},
    ]
    cues = nfa.timed_caption_cues(text, words, start=1.0, max_chars_per_line=8, max_lines=2)
    assert len(cues) == 1
    cue = cues[0]
    assert "".join(cue["lines"]) == text
    assert len(cue["words"]) >= 5
    assert "".join(w["text"] for w in cue["words"]) == text
    assert cue["words"][0]["start"] == 1.0
    assert cue["words"][-1]["end"] == 3.2

    ass_text = vgm.build_kinetic_ass_subtitles(
        [{"segment": 1, "cues": cues}],
        width=1080,
        height=1920,
        font_size=44,
        margin_v=140,
    )
    assert "PlayResX: 1080" in ass_text
    assert "PlayResY: 1920" in ass_text
    assert "Style: Kinetic,Noto Sans CJK SC,44" in ass_text
    assert "\\c&H004FD5FF\\fscx106\\fscy106" in ass_text
    dialogues = [ln for ln in ass_text.splitlines() if ln.startswith("Dialogue:")]
    assert len(dialogues) == len(cue["words"])


def test_bitrate_encoder_and_platform_subtitle_specs_and_progress_bar(monkeypatch):
    vgm.clear_hwaccel_cache()
    monkeypatch.setenv("FILM_HWACCEL", "auto")
    with patch.object(vgm, "_probe_nvenc_profile", return_value=True):
        nv_b = vgm.video_bitrate_encoder_args(video_kbps=240)
    assert nv_b[nv_b.index("-c:v") + 1] == "h264_nvenc"
    assert nv_b[nv_b.index("-b:v") + 1] == "240k"
    assert nv_b[nv_b.index("-maxrate") + 1] == "480k"

    cpu_b = vgm.video_bitrate_encoder_args(video_kbps=240, mode="cpu")
    assert cpu_b[cpu_b.index("-c:v") + 1] == "libx264"

    ks = vgm.platform_subtitle_spec("kuaishou", 1080, 1920)
    bili = vgm.platform_subtitle_spec("bilibili", 1920, 1080)
    assert ks["margin_v"] == 300
    assert bili["margin_v"] == 92
    assert bili["max_chars"] == 28

    html = "<!DOCTYPE html><html><body><div>hello</div></body></html>"
    with_bar = vgm.inject_kinetic_runtime(
        html, progress_start=0.25, progress_end=0.5, shot_duration=3.0, include_progress_bar=True
    )
    assert 'id="hermes-global-progress"' in with_bar
    assert 'data-progress-start="0.2500"' in with_bar
    # Topic layout pages must never receive the global progress overlay
    topic_html = '<!DOCTYPE html><html><body data-topic-layout="true"><div>topic</div></body></html>'
    without_bar = vgm.inject_kinetic_runtime(
        topic_html, progress_start=0.25, progress_end=0.5, shot_duration=3.0, include_progress_bar=True
    )
    assert 'id="hermes-global-progress"' not in without_bar


def test_openmotion_craft_rules_and_motion_blueprint_and_adaptive_fallback(tmp_path):
    # 1) OpenMotion director craft rules + video_planning_producer payload integration
    from content_platform.run_contract import build_run_contract
    from content_platform.video_planning_producer import analysis_payload

    assert vgm.OPENMOTION_DIRECTOR_CRAFT_RULES["version"] == "openmotion_craft_v1"
    rule_ids = {r["id"] for r in vgm.OPENMOTION_DIRECTOR_CRAFT_RULES["rules"]}
    assert {"visual_event_not_slide", "cross_shot_continuity", "bounded_dead_air_and_rhythm", "perceptual_audio_visual_anchors"} <= rule_ids

    contract = build_run_contract("kuaishou")
    payload = analysis_payload(contract, "AI 复盘", [])
    assert payload["content_blueprint"]["motion_craft_rules"]["version"] == "openmotion_craft_v1"

    # 2) Motion.md observation-grounded blueprint compiler
    samples = [
        {
            "content_id": "bv_demo_01",
            "breakdown": {
                "transition": {"observed": {"cuts_per_minute": 24, "observed": ["hard_cut", "wipeleft"]}},
                "motion": {"observed": ["handheld_push", "snap_zoom"]},
                "video_structure": {"observed": ["hook", "proof", "cta"]},
                "hook": {"observed": "3秒抛出反差结论"},
            },
        },
        {
            "content_id": "yt_demo_02",
            "breakdown": {
                "transition": {"observed": {"cuts_per_minute": 20, "observed": ["hard_cut"]}},
                "motion": {"observed": ["top_down_reveal"]},
                "video_structure": {"observed": ["problem", "result"]},
                "hook": {"observed": "先看前后对比"},
            },
        },
    ]
    bp = vgm.compile_motion_blueprint_md(samples, lane="real_world_ai_implementation", target_platform="kuaishou")
    assert bp["version"] == "motion_blueprint_v1"
    assert bp["source_count"] == 2
    assert bp["avg_cuts_per_minute"] == 22.0
    assert bp["recommended_shot_seconds"] == 2.73
    assert "hard_cut" in bp["observed_transitions"]
    assert "# Motion.md Blueprint (kuaishou / real_world_ai_implementation)" in bp["markdown"]
    assert "visual_event_not_slide" in bp["markdown"]

    # 3) Upgraded GSAP/OpenMotion kinetic primitives inside KINETIC_MOTION_RUNTIME_JS
    html = "<!DOCTYPE html><html><body><div data-start='0.2' data-motion-kind='reveal-clip'>hi</div></body></html>"
    injected = vgm.inject_kinetic_runtime(html)
    assert "window.__ease = EASE" in injected
    assert "reveal-clip" in injected
    assert "scale-punch" in injected
    assert "slide-lock" in injected
    assert "focus-breathe" in injected
    assert "metric-roll" in injected

    # 4) Adaptive concurrency step-down & transient browser error detection + dead-air/AV anchor audit
    assert vgm.is_transient_browser_capture_error("net::ERR_NO_BUFFER_SPACE at page.goto") is True
    assert vgm.is_transient_browser_capture_error("Target page, context or browser has been closed") is True
    assert vgm.is_transient_browser_capture_error("SyntaxError: unexpected token") is False
    assert vgm.next_retry_concurrency(4) == 2
    assert vgm.next_retry_concurrency(2) == 1
    assert vgm.next_retry_concurrency(1) == 1

    audit = vgm.audit_motion_pacing_and_anchors(
        starts_global=[0.0, 2.0, 5.0, 7.5],
        shot_durations=[2.0, 3.0, 2.5, 3.5],
        alignment_records=[
            {"segment": 1, "scene_duration": 5.0, "tts_duration": 4.2},
            {"segment": 2, "scene_duration": 6.0, "tts_duration": 3.5},
        ],
        transition_times=[5.0],
        max_idle_hold_seconds=1.6,
    )
    assert audit["version"] == "motion_craft_audit_v1"
    assert audit["all_anchors_aligned"] is True
    assert audit["pacing_contrast"]["contrast_ratio"] == 1.75
    assert audit["dead_air_warnings"] == ["segment_02_idle_hold_2.50s"]
