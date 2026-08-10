# Operations Policy Contract

This is the human-readable counterpart to `config/operations_policy_facts.json`. The channel rulebook validator compares the declared facts below with that machine-readable policy before an operations handoff.

wechat_articles_per_week: 2
newspic_dual_track: true
vertical_resolution: 1080x1920
short_max_seconds: 60
layered_motion: true

Use `scripts/ops_run.py` to record each platform topic before generation. A repeated direction is blocked unless the run records the prior platform, a genuinely different angle, and the reason a follow-up is useful.

Use `scripts/verify_video_artifact.py` for every final short-video handoff. The final encoded file and renderer manifest must show an actual 1080x1920 render, matching subtitles, meaningful card titles, and measurable frame movement.
