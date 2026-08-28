import json
from pathlib import Path


def test_compiler_keeps_display_text_and_applies_contextual_aliases(tmp_path: Path):
    from content_platform.tts_text_compiler import TTSTextCompiler

    dictionary = tmp_path / "pronunciation_dictionary.json"
    dictionary.write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {"source": "AI", "alias": "人工智能", "priority": 10, "contexts": ["tech"]},
                    {"source": "API", "alias": "A P I", "priority": 10, "contexts": ["tech"]},
                    {"source": "API", "alias": "接口", "priority": 10, "contexts": ["general"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = TTSTextCompiler.from_file(dictionary).compile(
        "AI 工具调用 API", context="tech", platform="douyin"
    )

    assert result.display_text == "AI 工具调用 API"
    assert result.tts_text == "人工智能 工具调用 A P I"
    assert [row["source"] for row in result.applied_rules] == ["AI", "API"]


def test_compiler_uses_priority_and_reports_unhandled_latin_tokens(tmp_path: Path):
    from content_platform.tts_text_compiler import TTSTextCompiler

    dictionary = tmp_path / "pronunciation_dictionary.json"
    dictionary.write_text(
        json.dumps(
            {
                "rules": [
                    {"source": "AI", "alias": "人工智能", "priority": 1},
                    {"source": "AI", "alias": "A I", "priority": 20},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = TTSTextCompiler.from_file(dictionary).compile("AI 与 GPU", context="tech")

    assert result.tts_text == "A I 与 GPU"
    assert result.applied_rules[0]["alias"] == "A I"
    assert result.unhandled_latin_tokens == ["GPU"]


def test_compiler_prefers_full_domain_rule_and_does_not_replace_ai_inside_words():
    from content_platform.tts_text_compiler import TTSTextCompiler

    compiler = TTSTextCompiler([
        {"source": "ai.kuaishou.com", "alias": "快手人工智能开放平台官网", "priority": 50, "contexts": ["tech"]},
        {"source": "AI", "alias": "人工智能", "priority": 20, "contexts": ["tech"]},
    ])
    result = compiler.compile("打开 ai.kuaishou.com 使用 AI", context="tech", platform="kuaishou")

    assert result.tts_text == "打开 快手人工智能开放平台官网 使用 人工智能"
    assert result.unhandled_latin_tokens == []

    spaced = compiler.compile("打开 ai. kuaishou. com", context="tech", platform="kuaishou")
    assert spaced.display_text == "打开 ai.kuaishou.com"
    assert spaced.tts_text == "打开 快手人工智能开放平台官网"


def test_compiler_applies_the_same_pronunciation_rule_to_every_occurrence():
    from content_platform.tts_text_compiler import TTSTextCompiler

    compiler = TTSTextCompiler([
        {"source": "AI", "alias": "人工智能", "priority": 20, "contexts": ["tech"]},
    ])

    result = compiler.compile("AI开放平台整合多个AI能力", context="tech", platform="kuaishou")

    assert result.tts_text == "人工智能开放平台整合多个人工智能能力"
    assert result.unhandled_latin_tokens == []
