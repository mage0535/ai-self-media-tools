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


def test_image_gen_pet_prompt_does_not_inject_workspace_environment():
    normalized = image_gen._normalize_image_prompt(
        "photorealistic cat relaxing in sunny grass, natural outdoor pet photography, vertical composition, no text"
    )

    assert "modern editorial workspace environment" not in normalized
    assert "cat" in normalized.casefold()


def test_image_gen_topic_specific_finance_prompt_does_not_inject_generic_environment():
    normalized = image_gen._normalize_image_prompt(
        "现代财务办公桌，笔记本电脑、发票和文件夹，暖光，真实摄影，无文字"
    )

    assert "modern editorial workspace environment" not in normalized
    assert "topic-matched environment relevant to the described subject" not in normalized
    assert "财务办公桌" in normalized


def test_image_gen_indoor_pet_prompt_gets_indoor_environment():
    normalized = image_gen._normalize_image_prompt(
        "photorealistic cat relaxing on a cushion indoors, soft window light, cinematic photography, no text"
    )

    assert "natural indoor pet environment" in normalized
    assert "natural outdoor pet environment" not in normalized


def test_image_gen_compiles_read_only_prompt_bundle_and_returns_fingerprint(tmp_path, monkeypatch):
    output = tmp_path / "image.png"
    monkeypatch.setattr(
        sys,
        "argv",
        ["image_gen.py", "--prompt", "AI workflow", "--platform", "douyin_ai", "--output", str(output)],
    )

    def fake_generate_image(**kwargs):
        Path(kwargs["output"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 3000)
        return {"provider": "fake", "output": str(kwargs["output"])}

    bundle = {
        "fingerprint": "bundle123",
        "quality_contract": {"aspect_ratio": "9:16"},
    }
    with patch("scripts.image_gen.compile_prompt_bundle", return_value=bundle) as compiler, patch(
        "scripts.image_gen.validate_prompt_bundle", return_value={"passed": True, "errors": [], "warnings": []}
    ) as validator, patch("scripts.image_gen.generate_image", side_effect=fake_generate_image), patch(
        "scripts.image_gen._run_optional_gate"
    ):
        code = image_gen.main()

    assert code == 0
    compiler.assert_called_once()
    validator.assert_called_once_with(bundle)
