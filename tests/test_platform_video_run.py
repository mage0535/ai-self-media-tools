from __future__ import annotations


def test_platform_video_runs_have_independent_paths_and_identity(tmp_path):
    from content_platform.platform_video_run import build_platform_video_run

    kuaishou = build_platform_video_run(data_dir=tmp_path, job_id="job-1", platform="kuaishou")
    youtube = build_platform_video_run(data_dir=tmp_path, job_id="job-1", platform="youtube_shorts")
    assert kuaishou.platform_run_id != youtube.platform_run_id
    assert kuaishou.output_dir != youtube.output_dir
    assert kuaishou.evidence_dir != youtube.evidence_dir
    assert kuaishou.profile_revision != youtube.profile_revision


def test_platform_profile_change_changes_run_identity(tmp_path):
    from content_platform.platform_video_run import build_platform_video_run

    short = build_platform_video_run(data_dir=tmp_path, job_id="job-1", platform="youtube_shorts")
    long_form = build_platform_video_run(data_dir=tmp_path, job_id="job-1", platform="youtube_long_form")
    assert short.platform_run_id != long_form.platform_run_id
    assert "youtube_shorts" in short.platform_run_id
    assert "youtube_long_form" in long_form.platform_run_id


def test_media_bridge_rejects_shared_multi_platform_video_output(tmp_path):
    import pytest
    from content_platform.media import MediaBridge

    script = tmp_path / "renderer.py"
    script.write_text("# fixture", encoding="utf-8")
    bridge = MediaBridge({"video": {"enabled": True, "script": str(script)}}, tmp_path)
    job = {"id": "job-1", "topic": "AI", "title": "AI", "body": "body", "platforms": ["kuaishou", "youtube_shorts"]}
    with pytest.raises(RuntimeError, match="shared multi-platform output is forbidden"):
        bridge.generate("video", job)


def test_pipeline_video_orchestrator_isolates_platform_failures():
    from content_platform.pipeline import Pipeline

    class Store:
        def get_job(self, _job_id):
            return {"id": "job-1", "platforms": ["kuaishou", "youtube_shorts"], "draft_meta": {}}
        def add_artifact(self, *_args):
            return None
        def record_event(self, *_args):
            return None

    class Media:
        def generate(self, _kind, job):
            if job["platforms"] == ["youtube_shorts"]:
                raise RuntimeError("renderer failed")
            return {"kind": "video", "path": "/tmp/kuaishou/final.mp4", "checksum": "sha-k"}

    class Runner:
        def run(self, _step, callback, **_kwargs):
            return callback()
        def skipped(self, *_args, **_kwargs):
            return None
        def block(self, *_args, **_kwargs):
            raise AssertionError("video should be enabled")

    class Self:
        config = {"media": {"video": {"enabled": True}}}
        store = Store()
        media = Media()
        _media_required = Pipeline._media_required

    result = Pipeline._generate_video_per_platform(Self(), "job-1", Runner(), ["validate_image_requirements"])
    assert len(result) == 1
    assert result[0]["checksum"] == "sha-k"