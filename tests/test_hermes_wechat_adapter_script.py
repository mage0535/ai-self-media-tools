import sys
from pathlib import Path

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
