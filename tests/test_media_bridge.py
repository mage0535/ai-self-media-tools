import json
from pathlib import Path

from PIL import Image

from content_platform.media import MediaBridge
from content_platform.adapters.media import normalize_article_sections


def test_normalize_article_sections_merges_short_transition_into_next_substantive_section():
    sections = normalize_article_sections({"draft_meta": {"sections": [
        {"title": "A complete opening that explains the concrete reader problem."},
        {"title": "我之前也是这样。"},
        {"title": "每天打开工具，整理上下文，再反复检查输出是否跑偏。"},
        {"title": "最后用清单确认来源、负责人和截止时间。"},
    ]}}, limit=4)

    assert "我之前也是这样" in sections[1]
    assert "整理上下文" in sections[1]
    assert len(sections) == 3


def test_image_checkpoint_contract_is_declared_in_media_bridge_source():
    source = Path(MediaBridge.__module__.replace(".", "/") + ".py")
    project = Path(__file__).resolve().parents[1]
    text = (project / source).read_text(encoding="utf-8")
    assert "image_asset_checkpoints.json" in text
    assert 'saved.get("signature") == signature' in text
    assert "os.replace(temporary, checkpoint_path)" in text


def test_cover_generation_reuses_existing_verified_cover(tmp_path):
    output = tmp_path / "artifacts" / "job-1"
    output.mkdir(parents=True)
    cover = output / "cover.png"
    cover.write_bytes(b"verified-cover")
    bridge = MediaBridge({"cover": {"enabled": True}}, tmp_path)

    artifact = bridge.generate("cover", {"id": "job-1", "platforms": ["kuaishou"]})

    assert artifact["kind"] == "cover"
    assert artifact["path"] == str(cover)
    assert artifact["source"] == "existing_verified_image_artifact"


def test_video_visual_assets_never_cycle_missing_images(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    duplicate = tmp_path / "duplicate.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    duplicate.write_bytes(b"first")

    bridge = MediaBridge({}, tmp_path)
    packet = bridge._prepare_video_visual_assets(
        {
            "platforms": ["kuaishou"],
            "artifacts": [
                {"kind": "image", "path": str(first)},
                {"kind": "image", "path": str(second)},
                {"kind": "image", "path": str(duplicate)},
            ],
        },
        tmp_path / "output",
        {"selected_pipeline": "knowledge_card_video"},
    )

    assert packet["image_count"] == 2
    assert packet["scene_count"] == 2
    assert len(packet["assignments"]) == 2
    assert all(item["reused"] is False for item in packet["assignments"])


def test_xiaohongshu_knowledge_image_recovers_failed_quality_candidates(tmp_path, monkeypatch):
    script = tmp_path / "image_gen.py"
    script.write_text("# fixture", encoding="utf-8")
    bridge = MediaBridge(
        {"image": {"enabled": True, "script": str(script), "provider": "stock", "min_count": 2, "quality_recovery_attempts": 4}},
        tmp_path,
    )
    calls = []

    def complex_image(path: Path, seed: int) -> None:
        image = Image.new("RGB", (1200, 1200))
        pixels = image.load()
        for x in range(1200):
            for y in range(1200):
                pixels[x, y] = ((x * 3 + seed) % 256, (y * 5 + seed) % 256, ((x + y) * 7 + seed) % 256)
        image.save(path)

    def fake_run(command, **kwargs):
        prompt = command[2]
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        calls.append(prompt)
        if output.name == "cover.png":
            complex_image(output, 11)
        elif len([call for call in calls if "Section illustration" in call]) == 1:
            Image.new("RGB", (1200, 1200), (24, 42, 64)).save(output)
        elif len([call for call in calls if "Section illustration" in call]) == 2:
            output.write_bytes((tmp_path / "artifacts" / "xhs-recover" / "cover.png").read_bytes())
        elif len([call for call in calls if "Section illustration" in call]) == 3:
            output.write_bytes(b"not an image")
        else:
            complex_image(output, 47)
        return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

    monkeypatch.setattr("content_platform.tool_adapters.subprocess.run", fake_run)

    artifact = bridge.generate(
        "image",
        {
            "id": "xhs-recover",
            "topic": "AI workflow quality recovery",
            "body": "Slide one explains the broken candidate.\n\nSlide two explains the recovery gate.",
            "platforms": ["xiaohongshu"],
            "draft_meta": {"content_form": "carousel"},
        },
    )

    assert len(artifact["images"]) == 2
    assert artifact["quality_recovery"]["passed"] is True
    assert artifact["quality_recovery"]["retry_count"] == 3
    assert len([prompt for prompt in calls if "Section illustration" in prompt]) == 4
    assert any("Quality recovery attempt 2" in prompt for prompt in calls)
    evidence = json.loads((tmp_path / "artifacts" / "xhs-recover" / "image_quality_recovery.json").read_text(encoding="utf-8"))
    section_attempts = [item for item in evidence["attempts"] if item["role"] == "section"]
    assert [item["passed"] for item in section_attempts] == [False, False, False, True]
    assert {"low_complexity", "duplicate_checksum", "image_decode_failed"} <= {
        failure for item in section_attempts for failure in item["failures"]
    }
    assert all(Path(item["failed_candidate_path"]).is_file() for item in section_attempts[:-1])


def test_xiaohongshu_knowledge_image_stops_after_bounded_quality_retries(tmp_path, monkeypatch):
    script = tmp_path / "image_gen.py"
    script.write_text("# fixture", encoding="utf-8")
    bridge = MediaBridge(
        {"image": {"enabled": True, "script": str(script), "provider": "stock", "min_count": 1, "quality_recovery_attempts": 2}},
        tmp_path,
    )

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1200, 1200), (24, 42, 64)).save(output)
        return type("Result", (), {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""})()

    monkeypatch.setattr("content_platform.tool_adapters.subprocess.run", fake_run)

    try:
        bridge.generate(
            "image",
            {
                "id": "xhs-fail",
                "topic": "AI workflow quality recovery",
                "body": "Slide one explains the bounded retry behavior.",
                "platforms": ["xiaohongshu"],
                "draft_meta": {"content_type": "knowledge_card"},
            },
        )
    except RuntimeError as exc:
        assert "image quality recovery exhausted" in str(exc)
    else:
        raise AssertionError("expected bounded image quality recovery failure")

    evidence_path = tmp_path / "artifacts" / "xhs-fail" / "image_quality_recovery.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["passed"] is False
    assert evidence["max_attempts"] == 2
    assert len(evidence["attempts"]) == 2
    assert all("low_complexity" in item["failures"] for item in evidence["attempts"])


def test_image_prompts_compile_content_intent_and_clean_section_titles():
    job = {
        "topic": "AI workflow content system",
        "platforms": ["xiaohongshu"],
        "draft_meta": {
            "sections": [
                {"id": "section_1", "title": "每天切换五个平台浪费两小时", "role": "hook"},
                {"id": "section_2", "title": "把选题写作配图串成工作流", "role": "method"},
            ],
        },
    }

    prompts = MediaBridge._image_prompts(job, 3)

    assert prompts[0]["intent"] == "cinematic_cover"
    assert [item["intent"] for item in prompts[1:]] == ["real_scene", "real_scene"]
    assert "每天切换五个平台浪费两小时" in prompts[1]["prompt"]
    assert "section_1" not in prompts[1]["prompt"]
    assert "'role':" not in prompts[1]["prompt"]


def test_asset_provenance_preserves_retouch_source_chain(tmp_path):
    image = tmp_path / "cover.png"
    image.write_bytes(b"image")
    MediaBridge._persist_asset_provenance(
        tmp_path,
        [{
            "path": str(image), "role": "cover", "checksum": "final-sha",
            "source_url": "generated:sense_nova", "license": "generated_for_project",
            "original_license": "Pexels",
            "generation_evidence": {"provider": "sense_nova", "provenance": {
                "original_provider": "pexels", "original_source_url": "https://www.pexels.com/photo/example",
                "original_license": "Pexels", "original_path": "/private/original.png",
            }},
        }],
        [{"role": "cover", "section": "cover", "purpose": "cover", "prompt": "cover"}],
        "ScriptImageProvider",
        {"topic": "AI workflow", "platforms": ["xiaohongshu"], "draft_meta": {}},
    )

    payload = json.loads((tmp_path / "asset_provenance.json").read_text(encoding="utf-8"))
    derivative = payload["assets"][0]["derivative_provenance"]
    assert derivative["original_provider"] == "pexels"
    assert derivative["original_source_url"] == "https://www.pexels.com/photo/example"
    assert derivative["original_license"] == "Pexels"


def test_xiaohongshu_cover_normalization_preserves_platform_target_size():
    assert MediaBridge._cover_minimum(["xiaohongshu"]) == 1080
    assert MediaBridge._cover_minimum(["rednote"]) == 1080
    assert MediaBridge._cover_minimum(["wechat"]) == 1200


def test_wechat_article_requires_cover_plus_three_inline_images():
    assert MediaBridge._required_image_count({"platforms": ["wechat"], "body": "article"}, {}) == 4
