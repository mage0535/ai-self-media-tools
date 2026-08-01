import subprocess
import sys


def test_onboard_check_runs_without_secret_output():
    result = subprocess.run(
        [sys.executable, "scripts/onboard_operator.py", "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "OPENAI_API_KEY=" not in combined
    assert "Cookie:" not in combined
    assert "Privacy reminder" in combined


def test_onboard_platform_guide_lists_kuaishou_steps():
    result = subprocess.run(
        [sys.executable, "scripts/onboard_operator.py", "--platform", "kuaishou"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode in {0, 1}
    assert "Kuaishou" in result.stdout
    assert "social-auto-upload" in result.stdout
    assert "validate_kuaishou_auto_packet.py" in result.stdout
