import json
from pathlib import Path

from PIL import Image

from content_platform.media import MediaBridge


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
