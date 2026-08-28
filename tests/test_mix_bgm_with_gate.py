from scripts.mix_bgm_with_gate import _bgm_gain_plan


def test_quiet_real_recording_is_normalized_to_audible_mix_range():
    gain, effective = _bgm_gain_plan(-39.6, 0.45)

    assert gain == 17.6
    assert -30 < effective < -28


def test_normal_source_does_not_receive_unnecessary_gain():
    gain, effective = _bgm_gain_plan(-20.0, 0.45)

    assert gain == 0
    assert effective < -20
