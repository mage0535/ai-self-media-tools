import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import image_gen


def test_image_gen_skip_gates_requires_explicit_authorization(tmp_path, monkeypatch, capsys):
    output = tmp_path / "image.png"
    monkeypatch.delenv("IMAGE_GEN_ALLOW_SKIP_GATES", raising=False)
    monkeypatch.setattr(sys, "argv", ["image_gen.py", "--prompt", "cover", "--output", str(output), "--skip-preflight"])

    code = image_gen.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "image gate skip is disabled" in captured.err


def test_image_gen_skip_gates_authorized_for_audited_runs(tmp_path, monkeypatch):
    output = tmp_path / "image.png"
    monkeypatch.setenv("IMAGE_GEN_ALLOW_SKIP_GATES", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        ["image_gen.py", "--prompt", "cover", "--output", str(output), "--skip-preflight", "--skip-visual-gate"],
    )

    def fake_generate_image(**kwargs):
        Path(kwargs["output"]).write_bytes(b"image")
        return {"provider": "fake", "output": str(kwargs["output"])}

    with patch("scripts.image_gen.generate_image", side_effect=fake_generate_image), patch("scripts.image_gen._run_optional_gate") as gate:
        code = image_gen.main()

    assert code == 0
    gate.assert_not_called()


def test_image_gen_normalizes_short_prompts_before_gates_and_generation(tmp_path, monkeypatch):
    output = tmp_path / "image.png"
    monkeypatch.setattr(sys, "argv", ["image_gen.py", "--prompt", "AI workflow", "--output", str(output)])

    def fake_generate_image(**kwargs):
        assert "clear main subject" in kwargs["prompt"]
        assert "soft natural lighting" in kwargs["prompt"]
        Path(kwargs["output"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 3000)
        return {"provider": "fake", "output": str(kwargs["output"])}

    with patch("scripts.image_gen.generate_image", side_effect=fake_generate_image), patch("scripts.image_gen._run_optional_gate") as gate:
        code = image_gen.main()

    assert code == 0
    gate.assert_called()


def test_image_gen_accepts_sensenova_edit_with_real_input_image(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\nreal-input")
    output = tmp_path / "edited.png"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "image_gen.py",
            "--prompt",
            "keep the original subject and improve the lighting",
            "--input-image",
            str(source),
            "--output",
            str(output),
            "--provider",
            "sensenova",
            "--size",
            "768x1024",
        ],
    )

    def fake_generate_image(**kwargs):
        assert kwargs["provider"] == "sensenova"
        assert Path(kwargs["input_image"]).read_bytes() == source.read_bytes()
        assert kwargs["size"] == "768x1024"
        output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"e" * 3000)
        return {
            "provider": "sensenova",
            "mode": "edit",
            "provenance": {"input_image_sha256": "a" * 64, "route": "explicit_provider"},
        }

    with patch("scripts.image_gen.generate_image", side_effect=fake_generate_image), patch("scripts.image_gen._run_optional_gate"):
        try:
            code = image_gen.main()
        except SystemExit as exc:
            pytest.fail(f"SenseNova provider should be accepted by the CLI, got argparse exit {exc.code}")

    captured = capsys.readouterr()
    payload = __import__("json").loads(captured.out)
    assert code == 0
    assert payload["provider"] == "sensenova"
    assert payload["mode"] == "edit"
    assert payload["provenance"]["input_image_sha256"] == "a" * 64


def test_image_gen_no_text_prompt_without_input_image_stays_generate_route(tmp_path, monkeypatch, capsys):
    output = tmp_path / "generated.png"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "image_gen.py",
            "--prompt",
            "clean editorial cover, no text",
            "--output",
            str(output),
            "--provider",
            "pixazo",
        ],
    )

    def fake_generate_image(**kwargs):
        assert kwargs["provider"] == "pixazo"
        assert kwargs["input_image"] is None
        output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"p" * 3000)
        return {"provider": "pixazo", "mode": "generate", "route_decision": "generate_without_reference"}

    with patch("scripts.image_gen.generate_image", side_effect=fake_generate_image), patch("scripts.image_gen._run_optional_gate"):
        try:
            code = image_gen.main()
        except SystemExit as exc:
            pytest.fail(f"Pixazo provider should be accepted by the CLI, got argparse exit {exc.code}")

    payload = __import__("json").loads(capsys.readouterr().out)
    assert code == 0
    assert payload["mode"] == "generate"
    assert payload["route_decision"] == "generate_without_reference"
