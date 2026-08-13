from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_overnight_entrypoint_uses_bounded_catchup_and_fail_closed_acceptance():
    text = (ROOT / "scripts" / "run_overnight_batch.sh").read_text(encoding="utf-8")
    assert 'OVERNIGHT_ADMISSION_WINDOW_MINUTES:-60' in text
    assert 'overnight-acceptance --result' in text
    assert 'overnight_acceptance_failed' in text
