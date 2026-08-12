import sys
from pathlib import Path
from types import SimpleNamespace

from scripts import hermes_wechat_adapter


def test_generated_image_helpers_accept_image_gen_engine_output_key(tmp_path, monkeypatch):
    class FakeImageGen:
        @staticmethod
        def generate(prompt, platform=None, output_path=""):
            Path(output_path).write_bytes(b"image")
            return {"status": "ok", "output": output_path, "provider": "fake"}

    monkeypatch.setitem(sys.modules, "image_gen_engine", FakeImageGen)
    packet = {
        "title": "Adapter image generation",
        "cover_design": {"visual_subject": "workflow checklist"},
        "section_image_map": [{"section": "case", "purpose": "show the case"}],
    }

    cover = hermes_wechat_adapter._generate_image(packet, tmp_path, "cover")
    inline = hermes_wechat_adapter._generate_section_image(packet, tmp_path, packet["section_image_map"][0], 1)

    assert cover == tmp_path / "cover.jpg"
    assert inline == tmp_path / "inline_1.jpg"
    assert cover.is_file()
    assert inline.is_file()


def test_generated_image_path_keeps_legacy_path_key(tmp_path):
    image = tmp_path / "legacy.jpg"
    image.write_bytes(b"image")

    assert hermes_wechat_adapter._generated_image_path({"path": str(image)}, tmp_path / "fallback.jpg") == image


def test_publish_license_gate_blocks_missing_title(tmp_path):
    result = hermes_wechat_adapter._run_publish_license_gate({}, tmp_path / "missing.py")

    assert result["passed"] is False
    assert "title_missing" in result["failures"]


def test_publish_license_gate_fails_closed_on_invalid_json(tmp_path):
    gate = tmp_path / "license.py"
    gate.write_text("print('not-json')\n", encoding="utf-8")

    result = hermes_wechat_adapter._run_publish_license_gate({"title": "Valid title"}, gate)

    assert result["passed"] is False
    assert "license_output_invalid" in result["failures"][0]


def test_publish_license_gate_fails_closed_when_script_missing(tmp_path):
    result = hermes_wechat_adapter._run_publish_license_gate({"title": "Valid title"}, tmp_path / "missing.py")

    assert result["passed"] is False
    assert "license_script_missing" in result["failures"]


def test_publish_packet_blocks_before_wechat_when_license_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("CN_PROXY", "socks5://127.0.0.1:1080")
    calls = [
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=1, stdout='{"passed": false, "failures": ["test_failure"]}', stderr=""),
    ]
    monkeypatch.setattr(hermes_wechat_adapter.subprocess, "run", lambda *args, **kwargs: calls.pop(0))
    packet = {"title": "AI自动化实测：10个平台工具测评"}

    result = hermes_wechat_adapter.publish_packet(packet, tmp_path)

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "WeChat publish license blocked" in result["error"]
