from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_cli_entrypoint_is_pinned_to_lf_checkout():
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "bin/content-platform text eol=lf" in attributes
