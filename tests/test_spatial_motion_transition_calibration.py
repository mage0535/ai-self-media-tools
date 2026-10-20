from content_platform.video_artifact import _exclude_short_global_transition_bursts


def test_renderer_xfade_range_is_excluded_as_short_transition():
    background = [0.002] * 10 + [0.036, 0.038, 0.037] + [0.002] * 10
    moving_area = [0.02] * 10 + [0.14, 0.16, 0.15] + [0.02] * 10

    result = _exclude_short_global_transition_bursts(background, moving_area, sample_fps=4)

    assert result["clusters"] == [[10, 12]]
    assert {9, 10, 11, 12, 13} <= set(result["excluded_indices"])


def test_moderate_sustained_background_motion_is_not_excluded():
    background = [0.036] * 12
    moving_area = [0.15] * 12

    result = _exclude_short_global_transition_bursts(background, moving_area, sample_fps=4)

    assert result["clusters"] == [[0, 11]]
    assert result["excluded_indices"] == []
