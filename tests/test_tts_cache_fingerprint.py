from content_platform.tts_cache import tts_fingerprint


def test_tts_fingerprint_changes_when_any_synthesis_parameter_changes():
    base = dict(display_text="AI工具", tts_text="A I 工具", provider="edge", model="edge-v1", voice="Yunjian", rate="-5%", pitch="+0Hz", pronunciation_dictionary_version="d1", postprocess_profile="none")
    original = tts_fingerprint(**base)
    for key in base:
        changed = dict(base)
        changed[key] = str(changed[key]) + "-changed"
        assert tts_fingerprint(**changed) != original
