from content_platform import audio_plan_resolver


def test_library_start_rotates_per_job(tmp_path, monkeypatch):
    # Every video used the first library track; the start now rotates with the job identity.
    picked = []

    def fake_resolve(source, settings, platform, output):
        picked.append(source["audio_path"])
        return {"status": "resolved", "audio_path": source["audio_path"]}

    monkeypatch.setattr(audio_plan_resolver, "_resolve_record", fake_resolve)
    sources = [{"audio_path": f"track-{i}"} for i in range(16)]
    config = {"audio_plan_resolver": {"sources": sources}}
    for i in range(40):
        audio_plan_resolver.resolve_audio_plan(config, {"id": f"job{i:04d}", "platforms": ["kuaishou"]}, tmp_path)
    assert len(set(picked)) > 8


def test_library_falls_through_to_next_track_after_failure(tmp_path, monkeypatch):
    tried = []

    def fake_resolve(source, settings, platform, output):
        tried.append(source["audio_path"])
        if len(tried) == 1:
            raise audio_plan_resolver.AudioInputError("native_bgm_quality_gate_failed")
        return {"status": "resolved", "audio_path": source["audio_path"]}

    monkeypatch.setattr(audio_plan_resolver, "_resolve_record", fake_resolve)
    config = {"audio_plan_resolver": {"sources": [{"audio_path": "a"}, {"audio_path": "b"}]}}
    result = audio_plan_resolver.resolve_audio_plan(config, {"id": "job0001", "platforms": ["douyin_pet"]}, tmp_path)
    assert result["status"] == "resolved" and len(tried) == 2 and tried[0] != tried[1]
