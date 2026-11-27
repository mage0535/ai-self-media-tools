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
