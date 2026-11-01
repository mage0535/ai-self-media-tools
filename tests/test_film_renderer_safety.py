import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import film_renderer


ROOT = Path(__file__).resolve().parents[1]


def test_film_renderer_uses_bounded_playwright_recording_and_cleanup():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert 'wait_until="load"' in source
    assert "_record_shot(name, html_path, duration, out, frame_driven=frame_driven)" in source
    assert "element_render_timeout_seconds(duration)" in source
    assert "frame_driven: bool = False" in source
    assert "requestAnimationFrame(tick)" in source
    assert "await asyncio.wait_for(context.close()" in source
    assert "await asyncio.wait_for(browser.close()" in source


def test_default_policy_requires_cinematic_motion(monkeypatch):
    monkeypatch.delenv("FILM_QUALITY_PROFILE", raising=False)
    monkeypatch.delenv("FILM_MOTION_MODE", raising=False)
    monkeypatch.delenv("FILM_ALLOW_DEGRADED", raising=False)

    policy = film_renderer.resolve_render_policy()

    assert policy == {"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False}


def test_element_frame_render_timeout_covers_high_resolution_long_scenes():
    assert film_renderer.element_render_timeout_seconds(10.82) >= 90
    assert film_renderer.RENDERER_VERSION == "cinematic-v11-stable-copy-safe-layout10"


def test_safe_motion_requires_explicit_degraded_opt_in(monkeypatch):
    monkeypatch.setenv("FILM_QUALITY_PROFILE", "degraded")
    monkeypatch.setenv("FILM_MOTION_MODE", "safe")
    monkeypatch.delenv("FILM_ALLOW_DEGRADED", raising=False)

    with pytest.raises(ValueError, match="FILM_ALLOW_DEGRADED"):
        film_renderer.resolve_render_policy()


def test_changed_render_contract_invalidates_stale_shots(tmp_path):
    old_contract = {"renderer_version": "cinematic-v1", "motion_mode": "cinematic"}
    (tmp_path / "render_contract.json").write_text(json.dumps(old_contract), encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    stale_shot = shots / "shot_01A.mp4"
    stale_shot.write_bytes(b"stale")
    stale_final = tmp_path / "final.mp4"
    stale_final.write_bytes(b"stale")

    changed = film_renderer.prepare_render_contract(
        tmp_path,
        {"renderer_version": "cinematic-v2", "motion_mode": "cinematic"},
    )

    assert changed is True
    assert not stale_shot.exists()
    assert not stale_final.exists()


def test_subtitle_position_change_only_invalidates_final_composite(tmp_path):
    old_contract = {
        "renderer_version": "cinematic-v2",
        "motion_mode": "cinematic",
        "subtitle_y_up": 300,
    }
    (tmp_path / "render_contract.json").write_text(json.dumps(old_contract), encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    stable_shot = shots / "shot_01A.mp4"
    stable_shot.write_bytes(b"stable-shot")
    html = tmp_path / "html"
    html.mkdir()
    (html / "shot_01A.html").write_text("stable-html", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "cue.txt").write_text("old subtitle", encoding="utf-8")
    mixed = tmp_path / "mixed_v2.mp4"
    mixed.write_bytes(b"stable-mixed")
    final = tmp_path / "final.mp4"
    final.write_bytes(b"old-final")

    changed = film_renderer.prepare_render_contract(
        tmp_path,
        {**old_contract, "subtitle_y_up": 270},
    )

    assert changed is True
    assert stable_shot.exists()
    assert (html / "shot_01A.html").exists()
    assert mixed.exists()
    assert not sub.exists()
    assert not final.exists()
    evidence = json.loads((tmp_path / "render_invalidation_evidence.json").read_text())
    assert evidence == {"scope": "final_composite", "changed_keys": ["subtitle_y_up"]}


def test_scene_input_change_preserves_shots_for_scene_key_recheck(tmp_path):
    old_contract = {
        "renderer_version": "cinematic-v2", "motion_mode": "cinematic",
        "cards_sha256": "old", "subtitle_y_up": 270,
    }
    (tmp_path / "render_contract.json").write_text(json.dumps(old_contract), encoding="utf-8")
    (tmp_path / "shots").mkdir()
    shot = tmp_path / "shots" / "shot_01A.mp4"
    shot.write_bytes(b"stable-shot")
    (tmp_path / "shot_cache").mkdir()
    cache = tmp_path / "shot_cache" / "s01.json"
    cache.write_text("{}", encoding="utf-8")
    (tmp_path / "visual_xfade.mp4").write_bytes(b"stale-composite")
    (tmp_path / "final.mp4").write_bytes(b"stale-final")

    film_renderer.prepare_render_contract(tmp_path, {**old_contract, "cards_sha256": "new"})

    assert shot.exists()
    assert cache.exists()
    assert not (tmp_path / "visual_xfade.mp4").exists()
    assert not (tmp_path / "final.mp4").exists()
    evidence = json.loads((tmp_path / "render_invalidation_evidence.json").read_text())
    assert evidence["scope"] == "scene_cache_recheck"


def test_cinematic_quality_rejects_still_fallback():
    evidence = film_renderer.build_render_quality_evidence(
        policy={"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False},
        shot_records=[{"name": "shot_01A", "renderer": "still-motion", "fallback": True}],
        motion={"mean_delta": 0.03, "active_ratio": 0.9, "peak_count": 5, "passed": True},
    )

    assert evidence["passed"] is False
    assert "cinematic_fallback_used" in evidence["failures"]


def test_element_motion_quality_gate_accepts_local_motion_without_camera_drift():
    evidence = film_renderer.build_render_quality_evidence(
        policy={"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False},
        shot_records=[
            {"name": "shot_01A", "renderer": "playwright-video", "fallback": False},
            {"name": "shot_01B", "renderer": "playwright-frame-video", "fallback": False},
        ],
        motion={
            "passed": False,
            "mean_delta": 0.049,
            "active_ratio": 0.175,
            "sustained_motion_ratio": 0.29,
            "peak_count": 17,
        },
        spatial_motion={
            "passed": True,
            "background_stable": True,
            "background_active_ratio": 0.02,
            "business_roi_active_ratio": 0.075,
            "moving_area_ratio_p95": 0.036,
            "failures": [],
        },
    )

    assert evidence["passed"] is True
    assert evidence["motion_gate_mode"] == "element_motion"
    assert evidence["failures"] == []


def test_element_motion_gate_rejects_full_frame_drift_even_when_motion_is_high():
    evidence = film_renderer.build_render_quality_evidence(
        policy={"quality_profile": "high", "motion_mode": "cinematic", "allow_degraded": False},
        shot_records=[{"name": "shot_01B", "renderer": "playwright-frame-video", "fallback": False}],
        motion={"passed": True, "mean_delta": 0.05, "active_ratio": 0.9, "sustained_motion_ratio": 0.9, "peak_count": 50},
        spatial_motion={
            "passed": False,
            "background_stable": False,
            "background_active_ratio": 0.84,
            "business_roi_active_ratio": 0.5,
            "moving_area_ratio_p95": 0.92,
            "failures": ["background_motion_forbidden", "global_motion_area_excessive"],
        },
    )

    assert evidence["passed"] is False
    assert "background_motion_forbidden" in evidence["failures"]
    assert "global_motion_area_excessive" in evidence["failures"]


def test_audio_spec_requires_44100hz_stereo():
    assert film_renderer.validate_audio_spec({"sample_rate": 24000, "channels": 1})["passed"] is False
    assert film_renderer.validate_audio_spec({"sample_rate": 44100, "channels": 2})["passed"] is True


def test_cached_media_duration_is_bound_to_audio_sha(tmp_path, monkeypatch):
    audio = tmp_path / "tts.mp3"
    audio.write_bytes(b"audio-v1")
    digest = film_renderer._sha256_file(audio)

    def unexpected_probe(_path):
        raise AssertionError("matching audio SHA must reuse cached duration")

    monkeypatch.setattr(film_renderer, "_duration", unexpected_probe)
    assert film_renderer.cached_media_duration(
        audio, {"audio_sha256": digest, "duration_seconds": 5.25}
    ) == pytest.approx(5.25)

    monkeypatch.setattr(film_renderer, "_duration", lambda _path: 6.5)
    audio.write_bytes(b"audio-v2")
    assert film_renderer.cached_media_duration(
        audio, {"audio_sha256": digest, "duration_seconds": 5.25}
    ) == pytest.approx(6.5)


def test_timeline_uses_real_transition_boundaries():
    starts, total = film_renderer.calculate_timeline([2.0, 2.0, 2.0], [0.35, 0.0])

    assert starts == [0.0, 1.65, 3.65]
    assert total == 5.65


def test_segment_shot_budget_covers_internal_crossfade_and_audio_margin():
    a_duration, b_duration = film_renderer.segment_shot_durations(9.38, element_motion=False)

    assert a_duration + b_duration - film_renderer.XFADE_DUR_LONG >= 9.53


def test_cinematic_templates_keep_background_static_for_local_motion():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "animation: kb 6s linear infinite alternate" not in source
    assert "style.transform = 'scale(1.14)" not in source
    assert "style.transform = 'scale(1.15)" not in source
    assert "style.transform = 'scale(1.13)" not in source
    assert "bg.style.transform=" not in source
    assert "zoompan=z='min(zoom+0.0008,1.06)'" not in source
    assert "veil.style.opacity=" not in source
    assert '"motion_evidence_version": MOTION_EVIDENCE_VERSION' in source


def test_prompt_lab_b_shot_uses_its_own_mode_and_purpose():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "contract_mode=mode_a" not in source
    assert "shot_purpose=purpose_a" in source
    assert "shot_purpose=purpose_b" in source
    assert "select_contract_b_mode(" in source


def test_predictive_maintenance_b_shot_keeps_scene_semantics_and_end_hold_never_fades_black():
    modes = [
        "before_after_split", "input_branch", "source_trace", "error_fix_compare",
        "evidence_timeline", "checklist_lock", "flow_track", "result_audit",
    ]
    for index, mode in enumerate(modes, start=1):
        selected = film_renderer.select_contract_b_mode(
            mode, index, f"predictive_maintenance_{mode}_v2", modes
        )
        assert selected == f"{mode}_detail"
        detail_html = film_renderer.build_prompt_lab_shot(
            index, f"场景{index}", "证据细节", str(Path(__file__)), mode,
            "设备预测性维护", template_id=f"predictive_maintenance_{mode}_v2",
            contract_mode=selected, shot_purpose="detail",
        )
        assert "pm-detail-layout" in detail_html
        assert "pm-detail-proof" in detail_html


def test_predictive_maintenance_b_detail_survives_contract_mode_binding(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    html = film_renderer.build_prompt_lab_shot(
        7,
        "处置由人决定",
        "设备预测性维护",
        str(background),
        "flow_track_detail",
        "设备预测性维护",
        template_id="predictive_maintenance_flow_track_v3",
        group_motion=["local_highlight"],
        contract_mode="flow_track",
        shot_purpose="same scene detail proof",
    )
    assert "pm-decision-matrix" in html
    assert "pm-detail-layout" in html
    assert "选择人：维修责任人" in html

    assert film_renderer.TRANSITION_MAP["end_hold"] == "dissolve"


def test_topic_runtime_gate_selects_predictive_root_and_checks_subtitle_band():
    source = Path("scripts/film_renderer.py").read_text(encoding="utf-8")
    assert "document.body.dataset.predictiveLayout === 'true'" in source
    assert "predictive ? '.pm-layout' : '.industrial-overlay'" in source
    assert "predictive_children" in source
    assert "predictive_content_in_subtitle_band" in source


def test_industrial_handoff_modes_render_distinct_semantic_dom(tmp_path):
    background = tmp_path / "factory.jpg"
    background.write_bytes(b"research-driven-factory-background")
    required = {
        "decision_interrupt": "decision-interrupt",
        "capture_rig_exploded_view": "capture-rig",
        "dataset_annotation_board": "dataset-board",
        "anomaly_heatmap_inspection": "heatmap-inspection",
        "risk_queue_flow": "risk-queue",
        "human_review_console": "handoff-console",
        "failure_boundary_triptych": "boundary-triptych",
        "execution_audit_receipt": "execution-audit",
    }

    rendered = {}
    for index, (mode, marker) in enumerate(required.items(), start=1):
        html = film_renderer.build_prompt_lab_shot(
            index,
            "工业质检人工接管",
            "高风险和不确定样本不能由模型单独做最终处置。",
            str(background),
            mode,
            "研究驱动镜头",
            contract_mode=mode,
            shot_purpose=f"{mode}:proof",
        )
        assert marker in html
        assert '<div class="body-copy">' not in html
        rendered[mode] = html

    assert len(set(rendered.values())) == len(required)


def test_industrial_handoff_detail_modes_never_fall_back_to_generic_prompt_lab(tmp_path):
    from scripts import film_renderer

    background = tmp_path / "background.png"
    background.write_bytes(b"industrial-background")
    required = {
        "decision_interrupt_detail": "decision-detail",
        "capture_rig_exploded_view_detail": "capture-detail",
        "dataset_annotation_board_detail": "governance-detail",
        "anomaly_heatmap_inspection_detail": "evidence-detail",
        "risk_queue_flow_detail": "risk-detail",
        "human_review_console_detail": "disposition-detail",
        "failure_boundary_triptych_detail": "trigger-detail",
        "execution_audit_receipt_detail": "receipt-detail",
    }
    for index, (mode, marker) in enumerate(required.items(), start=1):
        html = film_renderer.build_prompt_lab_shot(
            index, "工业质检人工接管", "必须展示证据和动作。", str(background),
            mode, "研究驱动镜头", contract_mode=mode, shot_purpose=f"{mode}:proof",
        )
        assert marker in html
        assert '<div class="body-copy">' not in html

    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")
    assert "select_contract_b_mode(" in source


def test_screenshot_shots_keep_moving_after_their_entrance_animation():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "@keyframes screenshotFloat" in source
    assert "screenshotFloat 5.2s linear 0.9s infinite alternate" in source


def test_cinematic_establishing_shots_use_multiple_compositions_and_pet_documentary_mode():
    source = (ROOT / "scripts" / "film_renderer.py").read_text(encoding="utf-8")

    assert "content_styles = [" in source
    assert "title_sizes = [80, 64, 70, 62, 76, 58, 72, 66]" in source
    assert 'platform).casefold() == "douyin_pet"' in source
    assert "platform=args.platform" in source


def test_visual_treatment_rejects_scene_without_required_directives(tmp_path):
    plan = {
        "version": "visual_treatment_plan_v1",
        "scenes": [{"scene_id": "s01", "display_purpose": "hook"}],
    }
    path = tmp_path / "visual_treatment_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        film_renderer.load_visual_treatment_plan(path, expected_scene_count=1)


def test_visual_treatment_maps_plan_to_real_renderer_choices(tmp_path):
    asset = tmp_path / "proof.png"
    asset.write_bytes(b"asset")
    plan = {
        "version": "visual_treatment_plan_v1",
        "scenes": [{
            "scene_id": "s01",
            "display_purpose": "show proof",
            "real_asset": str(asset),
            "camera_language": "left_dolly",
            "subject_motion": "action_path",
            "text_motion": "before_after_wipe",
            "transition": "left_swipe",
            "rhythm_beat": {"emphasis": "proof"},
            "interaction_prompt": "comment",
        }],
    }
    path = tmp_path / "visual_treatment_plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")

    scene = film_renderer.load_visual_treatment_plan(path, expected_scene_count=1)[0]
    applied = film_renderer.resolve_scene_treatment(scene)

    assert applied["camera_index"] == 1
    assert applied["element_shot"] == "step_light"
    assert applied["transition"] == "smoothleft"
    assert applied["asset_sha256"] == film_renderer._sha256_file(asset)


def test_visual_treatment_never_selects_unsupported_xfade_transition():
    supported = {"fadeblack", "smoothleft", "circleopen", "slideleft", "wipeleft", "smoothup", "revealright", "dissolve"}

    assert set(film_renderer.TRANSITION_MAP.values()).issubset(supported)


def test_visual_treatment_builder_creates_complete_unique_scene_plan(tmp_path):
    backgrounds = []
    for index in range(8):
        path = tmp_path / f"bg_{index:02d}.jpg"
        path.write_bytes(f"background-{index}".encode())
        backgrounds.append(path)

    generated = film_renderer.ensure_visual_treatment_plan(tmp_path, backgrounds)
    scenes = film_renderer.load_visual_treatment_plan(generated, expected_scene_count=8)

    assert generated.is_file()
    assert len({scene["camera_language"] for scene in scenes}) >= 6
    assert len({scene["transition"] for scene in scenes}) >= 4


def test_high_quality_profile_does_not_accept_a_failed_script_gate():
    assert film_renderer.script_gate_passed(0, "high") is True
    assert film_renderer.script_gate_passed(1, "high") is False
    assert film_renderer.script_gate_passed(1, "degraded") is True


def test_film_renderer_retries_edge_tts_and_rejects_empty_audio(tmp_path, monkeypatch):
    output = tmp_path / "voice.mp3"
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        if len(calls) == 2:
            output.write_bytes(b"audio" * 4096)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setenv("FILM_TTS_RETRY_DELAY_SECONDS", "0")
    with patch("scripts.film_renderer.subprocess.run", side_effect=fake_run):
        attempts = film_renderer.synthesize_edge_tts("人工智能", output, "zh-CN-YunjianNeural")

    assert attempts == 2
    assert len(calls) == 2
    assert output.stat().st_size > 10_000


def test_chinese_subtitle_chunks_preserve_every_character_without_ellipsis():
    text = "系统记录5项：操作者、时间、原因、模型、规则版本。收藏清单。评论区说说：你会强制接管哪种情况？"

    chunks = film_renderer.subtitle_chunks(text, max_chars_per_line=15, max_lines=2)

    assert len(chunks) >= 2
    assert all(len(line) <= 15 for chunk in chunks for line in chunk)
    assert all(1 <= len(chunk) <= 2 for chunk in chunks)
    assert "…" not in "".join("".join(chunk) for chunk in chunks)
    assert "".join("".join(chunk) for chunk in chunks) == text


def test_industrial_content_containers_are_static_and_motion_tokens_are_not_visible(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    html = film_renderer.build_prompt_lab_shot(
        5,
        "4类信号，必须交给人",
        "低置信度、新缺陷、规则冲突、高风险件。",
        str(background),
        "risk_queue_flow",
        "工业AI",
        template_id="risk_queue_spatial_v1",
        group_motion=["orbit_select", "temperature_shift"],
        contract_mode="risk_queue_flow",
        shot_purpose="risk routing",
    )

    assert "querySelectorAll('.industrial-overlay').forEach" not in html
    assert "querySelectorAll('.uncertain-target,.rig-nodes,.dataset-board" not in html
    assert ">绿件</span>" not in html
    assert ">黄件</span>" not in html
    assert ">红件</span>" not in html
    assert 'class="contract-motion motion-orbit_select"' in html
    assert 'class="contract-motion motion-temperature_shift"' in html
    assert ".topic-scan-motion" in html
    assert "data-container-motion=\"none\"" in html
    assert "bg.style.transform=" not in html
    assert "document.querySelector('.content').style.transform" not in html
    assert "document.querySelector('.head').style.transform" not in html


def test_predictive_maintenance_uses_eight_distinct_outer_compositions_and_cta(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    modes = {
        "before_after_split": "pm-device-diagnostic",
        "input_branch": "pm-sensor-topology",
        "source_trace": "pm-baseline-proof",
        "error_fix_compare": "pm-signal-columns",
        "evidence_timeline": "pm-evidence-handoff",
        "checklist_lock": "pm-field-review",
        "flow_track": "pm-decision-matrix",
        "result_audit": "pm-result-workorder",
    }
    rendered = []
    for index, (mode, marker) in enumerate(modes.items(), start=1):
        html = film_renderer.build_prompt_lab_shot(
            index, f"场景{index}", "设备预测性维护证据", str(background), mode, "设备预测性维护",
            template_id=f"predictive_maintenance_{mode}_v2",
            group_motion=["local_highlight"], contract_mode=mode,
            shot_purpose=f"predictive maintenance scene {index}",
        )
        assert marker in html
        assert 'data-predictive-layout="true"' in html
        rendered.append(html)

    assert len(set(modes.values())) == 8
    assert "pm-independent-cta" in rendered[-1]
    assert "收藏四步" in rendered[-1]
    assert "转给管设备的同事" in rendered[-1]


def test_industrial_detail_copy_is_complete_and_matches_four_handoff_triggers(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    heatmap = film_renderer.build_prompt_lab_shot(
        4, "只画框，不算证据", "保留原图、热区、类别和不确定性。", str(background),
        "anomaly_heatmap_inspection_detail", "工业AI", group_motion=["wipe_reveal"],
        contract_mode="anomaly_heatmap_inspection_detail",
    )
    boundary = film_renderer.build_prompt_lab_shot(
        7, "这4种情况，强制接管", "新材质、强反光、相机偏移、新SKU。", str(background),
        "failure_boundary_triptych", "工业AI", group_motion=["error_mark"],
        contract_mode="failure_boundary_triptych",
    )
    boundary_detail = film_renderer.build_prompt_lab_shot(
        7, "这4种情况，强制接管", "新材质、强反光、相机偏移、新SKU。", str(background),
        "failure_boundary_triptych_detail", "工业AI", group_motion=["error_mark"],
        contract_mode="failure_boundary_triptych_detail",
    )
    execution_detail = film_renderer.build_prompt_lab_shot(
        8, "执行后，责任怎么追？", "操作者、时间、原因、模型和规则版本。收藏清单。评论区说说。", str(background),
        "execution_audit_receipt_detail", "工业AI", group_motion=["check_each"],
        contract_mode="execution_audit_receipt_detail",
    )

    assert all(label in heatmap for label in ("裂纹边缘", "热区定位", "原图坐标已保存"))
    for html in (boundary, boundary_detail):
        assert all(label in html for label in ("新材质", "强反光", "相机偏移", "新 SKU"))
        assert "失焦" not in html
    assert "收藏这份人工接管清单" in execution_detail
    assert "你会先强制接管哪一种" in execution_detail
    assert "cta-panel" in execution_detail
    assert "classList.toggle('is-cta'" in execution_detail


def test_douyin_subtitles_move_down_thirty_pixels_without_entering_bottom_ui():
    assert film_renderer.default_subtitle_y_up("douyin_ai", 720, 1280) == 270
    assert film_renderer.default_subtitle_y_up("douyin", 720, 1280) == 270
    assert film_renderer.default_subtitle_y_up("tiktok", 720, 1280) == 350
    assert film_renderer.default_subtitle_y_up("douyin_ai", 1280, 720) == 0


def test_all_industrial_detail_shots_have_independent_narrative_copy(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    expected = {
        "decision_interrupt_detail": "AI一旦犹豫，先停工件，再交权",
        "capture_rig_exploded_view_detail": "接管不是凭感觉，先排除输入漂移",
        "dataset_annotation_board_detail": "机器照标准找错，人负责定义标准",
        "anomaly_heatmap_inspection_detail": "只给一个“NG”，不叫证据",
        "risk_queue_flow_detail": "AI不知道自己不知道，才最危险",
        "human_review_console_detail": "人不是再看一遍，而是承担处置",
        "failure_boundary_triptych_detail": "输入边界一变，自动判定必须让路",
        "execution_audit_receipt_detail": "每次人工改判，都必须留下责任链",
    }
    for index, (mode, sentence) in enumerate(expected.items(), 1):
        html = film_renderer.build_prompt_lab_shot(
            index, "title", "spoken subtitle", str(background), mode,
            "工业AI", group_motion=["local_highlight"], contract_mode=mode,
        )
        assert 'class="narrative-copy"' in html
        assert sentence in html
        assert "<strong>" in html and "<span>" in html
        assert ".narrative-copy" in html
        assert "querySelectorAll('.narrative-copy')" not in html


def test_contract_body_copy_overrides_industrial_detail_narrative(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    html = film_renderer.build_prompt_lab_shot(
        4, "title", "spoken subtitle", str(background),
        "anomaly_heatmap_inspection_detail", "工业AI",
        contract_mode="anomaly_heatmap_inspection_detail",
        body_copy={"strong": "合同中的强结论", "explanation": "合同中的证据说明"},
    )
    assert "合同中的强结论" in html
    assert "合同中的证据说明" in html
    assert "只给一个“NG”，不叫证据。" not in html


def test_topic_layout_gate_rejects_narrative_collision_and_drift():
    valid = {
        "first": {"x": 48, "y": 470, "right": 672, "bottom": 700, "transform": "none"},
        "second": {"x": 48, "y": 470, "right": 672, "bottom": 700, "transform": "none"},
        "content_text": "人工接管证据链必须完整保留并且能够追责",
        "motion_text": [""],
        "narrative_first": {"x": 48, "y": 250, "right": 672, "bottom": 410, "transform": "none"},
        "narrative_second": {"x": 48, "y": 250, "right": 672, "bottom": 410, "transform": "none"},
        "narrative_text": "机器照标准找错人负责定义标准质检与工艺共同完成定标",
    }
    assert film_renderer.assess_topic_layout_samples(valid, 720, 1280) == []
    invalid = json.loads(json.dumps(valid))
    invalid["narrative_first"]["bottom"] = 490
    invalid["narrative_second"]["y"] = 260
    failures = film_renderer.assess_topic_layout_samples(invalid, 720, 1280)
    assert "narrative_card_collision" in failures
    assert "narrative_drift" in failures


def test_topic_layout_gate_rejects_overflow_drift_and_visible_motion_text():
    valid = {
        "first": {"x": 48, "y": 420, "right": 672, "bottom": 720, "transform": "none"},
        "second": {"x": 48, "y": 420, "right": 672, "bottom": 720, "transform": "none"},
        "content_text": "低置信度样本等待人工决定",
        "motion_text": ["", ""],
    }
    assert film_renderer.assess_topic_layout_samples(valid, 720, 1280) == []

    invalid = json.loads(json.dumps(valid))
    invalid["first"]["bottom"] = 900
    invalid["second"]["x"] = 64
    invalid["motion_text"] = ["ORBIT_SELECT"]
    failures = film_renderer.assess_topic_layout_samples(invalid, 720, 1280)
    assert "content_outside_safe_zone" in failures
    assert "container_drift" in failures
    assert "visible_floating_motion_text" in failures


def test_industrial_topic_a_and_b_shots_use_frame_driven_semantic_motion():
    scene_contract = [{"visual_mode": "decision_interrupt"}]
    shot_types = {1: "tile_activate"}

    assert film_renderer.should_frame_drive_shot("shot_01A", scene_contract, shot_types) is True
    assert film_renderer.should_frame_drive_shot("shot_01B", scene_contract, shot_types) is True
    assert film_renderer.should_frame_drive_shot(
        "shot_01A", [{"visual_mode": "generic_card"}], shot_types
    ) is False
    assert film_renderer.should_frame_drive_shot(
        "shot_01B", [{"visual_mode": "generic_card"}], shot_types
    ) is True


def test_industrial_pipeline_uses_hard_cuts_and_flash_gate_rejects_short_blank_frames():
    contract = [{"visual_mode": "decision_interrupt"}, {"visual_mode": "capture_rig_exploded_view"}]
    assert film_renderer.uses_industrial_hard_cuts(contract) is True
    evidence = film_renderer.assess_luminance_flash_samples(
        [80.0, 82.0, 235.0, 81.0, 79.0, 18.0, 8.0, 16.0, 82.0], fps=25.0
    )
    assert evidence["passed"] is False
    assert evidence["bright_flash_frames"] == [2]
    assert evidence["dark_gap_ranges"]
    clean = film_renderer.assess_luminance_flash_samples([80.0] * 50, fps=25.0)
    assert clean["passed"] is True


def test_concat_prep_filter_replaces_isolated_white_first_frame_without_shortening():
    clean = film_renderer.concat_prep_filter(0, replace_first_frame=False, fps=25)
    repaired = film_renderer.concat_prep_filter(3, replace_first_frame=True, fps=25)

    assert clean == "[0:v]setpts=PTS-STARTPTS[v0]"
    assert "trim=start_frame=1" in repaired
    assert "tpad=start_mode=clone:start_duration=0.040000" in repaired
    assert repaired.endswith("[v3]")


def test_luminance_flash_gate_fails_closed_when_decoder_returns_no_frames(monkeypatch, tmp_path):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"not-empty")

    class Result:
        returncode = 1
        stderr = "decoder failed"

    monkeypatch.setattr(film_renderer.subprocess, "run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(film_renderer.subprocess, "check_output", lambda *args, **kwargs: "25/1")

    evidence = film_renderer.measure_luminance_flash_evidence(video)

    assert evidence["passed"] is False
    assert "luminance_decode_failed" in evidence["failures"]
    assert "luminance_frames_missing" in evidence["failures"]


def _make_cache_test_video(path: Path, color: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            f"color=c={color}:s=64x96:r=25:d=0.4", "-an", "-c:v", "libx264",
            "-profile:v", "baseline", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        timeout=30,
    )


def test_scene_key_is_content_addressed_and_ignores_final_composite_parameters(tmp_path):
    html_a = tmp_path / "a.html"
    html_b = tmp_path / "b.html"
    background = tmp_path / "bg.jpg"
    html_a.write_text("<p>A</p>", encoding="utf-8")
    html_b.write_text("<p>B</p>", encoding="utf-8")
    background.write_bytes(b"background-v1")
    runtime = {"renderer_sha256": "a" * 64, "font_sha256": "b" * 64, "browser_sha256": "c" * 64, "gate_sha256": "d" * 64, "width": 64, "height": 96, "fps": 25}
    shots = [
        {"name": "shot_01A", "html_path": html_a, "duration": 0.4, "render_mode": "playwright-video"},
        {"name": "shot_01B", "html_path": html_b, "duration": 0.4, "render_mode": "playwright-frame-video"},
    ]

    first, payload = film_renderer.build_scene_key("s01", shots, background, runtime)
    second, _ = film_renderer.build_scene_key("s01", shots, background, {**runtime, "subtitle_y_up": 271})
    background.write_bytes(b"background-v2")
    changed, _ = film_renderer.build_scene_key("s01", shots, background, runtime)

    assert first == second
    assert first != changed
    assert payload["shots"][0]["html_sha256"] == film_renderer._sha256_file(html_a)


def test_scene_cache_requires_atomic_pair_and_rejects_tampered_shot(tmp_path):
    out = tmp_path
    (out / "shots").mkdir()
    html_a = out / "a.html"
    html_b = out / "b.html"
    background = out / "bg.jpg"
    html_a.write_text("A", encoding="utf-8")
    html_b.write_text("B", encoding="utf-8")
    background.write_bytes(b"background")
    runtime = {"renderer_sha256": "a" * 64, "font_sha256": "b" * 64, "browser_sha256": "c" * 64, "gate_sha256": "d" * 64, "width": 64, "height": 96, "fps": 25}
    shots = [
        {"name": "shot_01A", "html_path": html_a, "duration": 0.4, "render_mode": "playwright-video"},
        {"name": "shot_01B", "html_path": html_b, "duration": 0.4, "render_mode": "playwright-frame-video"},
    ]
    key, payload = film_renderer.build_scene_key("s01", shots, background, runtime)
    for shot in shots:
        _make_cache_test_video(out / "shots" / f"{shot['name']}.mp4", "blue")
    film_renderer.commit_scene_cache(out, "s01", key, payload, shots)

    hit = film_renderer.inspect_scene_cache(out, "s01", key, payload)
    assert hit["hit"] is True
    assert [row["name"] for row in hit["records"]] == ["shot_01A", "shot_01B"]

    (out / "shots" / "shot_01A.mp4").write_bytes(b"tampered")
    miss = film_renderer.inspect_scene_cache(out, "s01", key, payload)
    assert miss["hit"] is False
    assert miss["reason"] == "artifact_sha_mismatch"
    assert not (out / "shots" / "shot_01A.mp4").exists()
    assert not (out / "shots" / "shot_01B.mp4").exists()


def test_scene_cache_lightweight_validation_skips_ffprobe(tmp_path, monkeypatch):
    out = tmp_path
    (out / "shots").mkdir()
    html_a = out / "a.html"
    html_b = out / "b.html"
    html_a.write_text("A")
    html_b.write_text("B")
    background = out / "background.jpg"
    background.write_bytes(b"background")
    runtime = {"renderer_sha256": "a" * 64, "font_sha256": "b" * 64, "browser_sha256": "c" * 64, "gate_sha256": "d" * 64, "width": 64, "height": 96, "fps": 25}
    shots = [
        {"name": "shot_01A", "html_path": html_a, "duration": 0.4, "render_mode": "playwright-frame-video", "fallback": False},
        {"name": "shot_01B", "html_path": html_b, "duration": 0.4, "render_mode": "playwright-frame-video", "fallback": False},
    ]
    key, payload = film_renderer.build_scene_key("s01", shots, background, runtime)
    for shot in shots:
        _make_cache_test_video(out / "shots" / f"{shot['name']}.mp4", "blue")
    film_renderer.commit_scene_cache(out, "s01", key, payload, shots)

    def unexpected_probe(_path):
        raise AssertionError("lightweight final-cache path must not invoke ffprobe")

    monkeypatch.setattr(film_renderer, "_probe_cached_shot", unexpected_probe)
    hit = film_renderer.inspect_scene_cache(out, "s01", key, payload, verify_media=False)
    assert hit["hit"] is True


def test_cinema_gate_card_sample_time_stays_inside_short_shot():
    assert film_renderer.card_sample_time(1.2) == pytest.approx(0.6)
    assert film_renderer.card_sample_time(4.0) == pytest.approx(1.5)


def test_final_render_cache_binds_final_and_every_required_evidence(tmp_path):
    final = tmp_path / "final.mp4"
    final.write_bytes(b"final-v1")
    evidence_paths = []
    for name in film_renderer.FINAL_CACHE_EVIDENCE_FILES:
        path = tmp_path / name
        path.write_text(json.dumps({"passed": True, "name": name}), encoding="utf-8")
        evidence_paths.append(path)
    final_key = film_renderer.build_final_render_key(
        {"renderer_version": "v1"}, ["scene-a", "scene-b"], ["tts-a"], "bgm-a", "embedded_licensed_bgm"
    )
    film_renderer.commit_final_render_cache(tmp_path, final_key, final, evidence_paths)

    assert film_renderer.inspect_final_render_cache(tmp_path, final_key)["hit"] is True
    evidence_paths[2].write_text("tampered", encoding="utf-8")
    miss = film_renderer.inspect_final_render_cache(tmp_path, final_key)
    assert miss["hit"] is False
    assert miss["reason"] == "evidence_sha_mismatch"


def test_stable_first_paint_waits_for_fonts_images_and_two_animation_frames():
    import asyncio

    class Page:
        def __init__(self):
            self.scripts = []

        async def evaluate(self, script, *args):
            self.scripts.append(script)
            return None

    page = Page()
    asyncio.run(film_renderer._wait_for_stable_first_paint(page))
    source = "\n".join(page.scripts)
    assert "document.fonts.ready" in source
    assert ".decode()" in source
    assert source.count("requestAnimationFrame") >= 2


def test_frame_driven_render_skips_unpainted_t_zero_state():
    assert film_renderer.frame_render_time(0, 25, 2.0) == 0.04
    assert film_renderer.frame_render_time(49, 25, 2.0) == 2.0


def test_leading_bright_run_is_trimmed_only_after_a_nonbright_frame_exists():
    assert film_renderer.should_trim_leading_bright_frame([235.0, 72.0]) is True
    assert film_renderer.should_trim_leading_bright_frame([235.0, 230.0]) is False
    assert film_renderer.should_trim_leading_bright_frame([235.0, 236.0, 234.0, 72.0]) is True
    assert film_renderer.leading_bright_run_length([235.0, 236.0, 234.0, 72.0]) == 3
    assert film_renderer.should_trim_leading_bright_frame([85.0, 84.0]) is False


def test_scene_cache_is_committed_before_final_composition_gates():
    source = Path("scripts/film_renderer.py").read_text(encoding="utf-8")
    local_commit = source.index("# Persist locally verified A/B scene checkpoints")
    composition = source.index("# Industrial explainer: text survives only when temporal ownership is exclusive.")
    assert local_commit < composition



def test_general_pet_beats_use_pet_observation_layout(tmp_path):
    background = tmp_path / "bg.jpg"
    background.write_bytes(b"image")
    for mode in sorted(film_renderer.PET_GENERAL_MODES):
        for shot_mode in (mode, mode + "_detail"):
            html = film_renderer.build_prompt_lab_shot(
                1, "两只猫一起开柜门", "两只猫一起开柜门", str(background), shot_mode, "宠物",
                template_id=f"{mode}_v1", group_motion=["push_in"],
            )
            assert "pet-observation" in html
            assert "萌宠日常观察" in html or shot_mode.endswith("_detail")
            assert "流程要点" not in html and "SUBJECT" not in html
