import sys
from pathlib import Path
from unittest.mock import patch

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
