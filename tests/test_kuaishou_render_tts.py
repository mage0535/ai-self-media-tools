import asyncio
import json
import sys
import time
from types import SimpleNamespace

from scripts import kuaishou_render


def test_card_tts_retries_transient_no_audio_and_writes_auditable_config(tmp_path, monkeypatch):
    attempts = []

    class FakeCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, output):
            attempts.append((self.text, self.voice))
            if len(attempts) == 1:
                raise RuntimeError("temporary no audio")
            with open(output, "wb") as handle:
                handle.write(b"audio" * 4096)

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FakeCommunicate))
    monkeypatch.setenv("KUAISHOU_TTS_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setattr(kuaishou_render, "_media_duration", lambda *_args, **_kwargs: 2.5)

    result = asyncio.run(kuaishou_render.gen_tts(tmp_path, [{"tts": "AI 调用 API 生成 TTS 音频"}]))

    config = json.loads((tmp_path / "tts_config.json").read_text(encoding="utf-8"))
    assert result["rendered"] == 1
    assert len(attempts) == 2
    assert config["segments"][0]["display_text"] == "AI 调用 API 生成 TTS 音频"
    assert config["segments"][0]["tts_text"] != config["segments"][0]["display_text"]
    assert (tmp_path / "tts" / "tts_01.mp3").stat().st_size > 10_000
    fingerprint = json.loads((tmp_path / "tts_fingerprint.json").read_text(encoding="utf-8"))
    assert fingerprint["duration_seconds"] == 2.5
    assert fingerprint["sample_rate"] == 44100
    assert fingerprint["channels"] == 2
    assert fingerprint["unhandled_latin_tokens"] == []


def test_card_tts_times_out_each_attempt_instead_of_hanging(tmp_path, monkeypatch):
    class HungCommunicate:
        def __init__(self, text, voice):
            self.text = text
            self.voice = voice

        async def save(self, output):
            await asyncio.sleep(1)

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=HungCommunicate))
    monkeypatch.setenv("KUAISHOU_TTS_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("KUAISHOU_TTS_ATTEMPT_TIMEOUT_SECONDS", "0.01")

    try:
        asyncio.run(kuaishou_render.gen_tts(tmp_path, [{"tts": "等待超时测试"}]))
    except RuntimeError as exc:
        assert "timeout" in str(exc)
    else:  # pragma: no cover - makes an unexpected successful network wait explicit
        raise AssertionError("hung TTS call must fail closed")


def test_bgm_download_fails_before_opening_network_when_budget_is_exhausted(tmp_path, monkeypatch):
    calls = []

    def should_not_open(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("expired BGM budget must not open a network request")

    monkeypatch.setattr(kuaishou_render.urllib.request, "urlopen", should_not_open)
    monkeypatch.setattr(kuaishou_render, "_ACTIVE_BGM_DEADLINE", time.monotonic() - 1)

    try:
        kuaishou_render._download_candidate_bgm(
            {"download_url": "https://example.invalid/audio.mp3"},
            tmp_path / "bgm.mp3",
        )
    except TimeoutError as exc:
        assert "budget" in str(exc)
    else:  # pragma: no cover - makes a deadline regression explicit
        raise AssertionError("expired BGM budget must fail closed")
    assert calls == []


def test_bgm_download_limits_each_candidate_without_consuming_global_budget(tmp_path, monkeypatch):
    candidate = {
        "provider": "pixabay_music",
        "download_url": "https://cdn.example/acoustic-guitar.mp3",
        "source_url": "https://pixabay.example/acoustic-guitar",
        "title": "Acoustic guitar instrumental",
        "artist": "artist",
        "license": "Pixabay Content License",
        "tags": "acoustic guitar instrumental",
        "license_verified": True,
    }
    candidate_deadlines = []

    def fake_download(_candidate, output):
        candidate_deadlines.append(kuaishou_render._ACTIVE_BGM_CANDIDATE_DEADLINE)
        output.write_bytes(b"audio" * 200_000)

    started = time.monotonic()
    monkeypatch.setenv("BGM_RESOLUTION_MAX_SECONDS", "90")
    monkeypatch.setenv("BGM_CANDIDATE_MAX_SECONDS", "3")
    monkeypatch.setenv("BGM_FINGERPRINT_REGISTRY", str(tmp_path / "bgm_registry.json"))
    monkeypatch.setattr(kuaishou_render, "_online_bgm_candidates", lambda _style: [candidate])
    monkeypatch.setattr(kuaishou_render, "_download_candidate_bgm", fake_download)

    kuaishou_render.download_bgm(tmp_path, "acoustic guitar")

    assert len(candidate_deadlines) == 1
    assert candidate_deadlines[0] is not None
    assert 0 < candidate_deadlines[0] - started <= 3.5


def test_default_bgm_candidate_budget_is_short_enough_to_skip_dead_sources():
    assert kuaishou_render.DEFAULT_BGM_CANDIDATE_MAX_SECONDS <= 15


def test_bgm_resolver_continues_after_first_candidate_timeout(tmp_path, monkeypatch):
    rows = [
        {"provider": "openverse_audio", "download_url": "https://one.invalid/a.mp3", "source_url": "https://source.test/one", "title": "Piano one", "license": "CC BY", "tags": "piano instrumental", "license_verified": True, "asset_id": "one"},
        {"provider": "openverse_audio", "download_url": "https://two.test/b.mp3", "source_url": "https://source.test/two", "title": "Piano two", "license": "CC BY", "tags": "piano instrumental", "license_verified": True, "asset_id": "two"},
    ]
    attempts = []

    def candidates(_style):
        for row in rows:
            yield row

    def download(row, output):
        attempts.append(row["asset_id"])
        if row["asset_id"] == "one":
            raise TimeoutError("dead source")
        output.write_bytes(b"audio" * 200_000)

    monkeypatch.setenv("BGM_FINGERPRINT_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(kuaishou_render, "_online_bgm_candidates", candidates)
    monkeypatch.setattr(kuaishou_render, "_download_candidate_bgm", download)

    kuaishou_render.download_bgm(tmp_path, "piano")

    assert attempts == ["one", "two"]
    assert kuaishou_render._ACTIVE_BGM_CANDIDATE_DEADLINE is None


def test_wikimedia_candidates_require_open_license_and_real_audio(monkeypatch):
    monkeypatch.setattr(kuaishou_render, "_request_json", lambda *_args, **_kwargs: {
        "query": {"pages": {
            "1": {"pageid": 1, "title": "File:Piano instrumental.ogg", "imageinfo": [{
                "url": "https://upload.wikimedia.org/piano.ogg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Piano_instrumental.ogg", "mime": "audio/ogg",
                "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}, "Artist": {"value": "<b>Artist</b>"}},
            }]},
            "2": {"pageid": 2, "title": "File:Closed song.ogg", "imageinfo": [{
                "url": "https://upload.wikimedia.org/closed.ogg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Closed_song.ogg", "mime": "audio/ogg",
                "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
            }]},
        }}
    })

    rows = kuaishou_render._wikimedia_commons_candidates("piano instrumental")

    assert len(rows) == 1
    assert rows[0]["provider"] == "wikimedia_commons_audio"
    assert rows[0]["license"] == "CC BY 4.0"
    assert rows[0]["artist"] == "Artist"


def test_bgm_download_skips_registered_sources_before_network_download(tmp_path, monkeypatch):
    used = {
        "provider": "openverse_audio",
        "download_url": "https://cdn.example/used.mp3",
        "source_url": "https://freesound.org/sounds/used",
        "title": "Used upright piano",
        "artist": "artist",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "tags": "upright piano instrumental",
        "license_verified": True,
        "asset_id": "used",
    }
    fresh = {
        **used,
        "download_url": "https://cdn.example/fresh.mp3",
        "source_url": "https://freesound.org/sounds/fresh",
        "title": "Fresh upright piano",
        "asset_id": "fresh",
    }
    registry = tmp_path / "bgm_registry.json"
    registry.write_text(
        json.dumps({"tracks": [{"fingerprint": "old", "source_url": used["source_url"]}]}),
        encoding="utf-8",
    )
    downloads = []

    def fake_download(candidate, output):
        downloads.append(candidate["source_url"])
        output.write_bytes(b"audio" * 200_000)

    monkeypatch.setenv("BGM_FINGERPRINT_REGISTRY", str(registry))
    monkeypatch.setattr(kuaishou_render, "_online_bgm_candidates", lambda _style: [used, used, fresh])
    monkeypatch.setattr(kuaishou_render, "_download_candidate_bgm", fake_download)

    kuaishou_render.download_bgm(tmp_path, "upright piano")

    assert downloads == [fresh["source_url"]]


def test_bgm_queries_prioritize_requested_instruments_before_broad_fallbacks():
    queries = kuaishou_render._bgm_queries("muted percussion and low strings")

    assert queries[0] == "muted percussion and low strings music instrumental"
    assert "orchestral strings music" in queries
    assert "acoustic guitar music instrumental" not in queries[:2]
