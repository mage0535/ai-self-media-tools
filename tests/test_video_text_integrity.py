import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.film_renderer import _pick_actives, _wrap  # noqa: E402
from scripts.video_toolchain_runner import _card_title  # noqa: E402
from content_platform.tts_text_compiler import TTSTextCompiler  # noqa: E402


def test_english_wrap_preserves_words_and_content():
    text = "AI is fast, but you pick the story. Copyright matters."
    first, second = _wrap(text, max_chars=30)
    assert "story" in first or "story" in second
    assert "Copyright matters" in first + " " + second
    assert "s" != first[-1:]
    assert "..." not in first + second


def test_card_modules_are_not_fixed_length_truncated():
    items = ["AI is fast, but you pick the story", "Copyright matters"]
    result = _pick_actives(items, 3)
    assert result[0] == items[0]
    assert result[1] == items[1]


def test_english_card_title_keeps_first_sentence():
    text = "The rest fell apart on real scripts. So frustrating."
    assert _card_title(text, 1) == "The rest fell apart on real scripts"


def test_english_platform_does_not_apply_chinese_pronunciation_alias():
    compiler = TTSTextCompiler([{"source": "AI", "alias": "人工智能", "contexts": ["tech"]}])
    result = compiler.compile("AI is fast.", context="tech", platform="tiktok")
    assert result.tts_text == "AI is fast."
    assert result.applied_rules == []
