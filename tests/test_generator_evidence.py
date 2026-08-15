from content_platform.generator import DraftGenerator


def test_growth_recipe_carries_real_kuaishou_trend_samples_into_the_publish_packet():
    draft_meta = {"strategy": {"primary_platforms": ["kuaishou"]}}
    brief = {
        "platform_source_matrix": {
            "platform": "kuaishou",
            "platform_internal_verified": True,
            "attempted_sources": [
                {"source": "kuaishou_hot", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/1"},
                {"source": "kuaishou_search", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/2"},
                {"source": "kuaishou_creator", "status": "ok", "topic_signal": "AI workflow", "url": "https://example.test/3"},
            ],
        }
    }

    DraftGenerator._attach_growth_recipe(brief, {}, draft_meta)

    evidence = draft_meta["trend_evidence"]
    assert evidence["source"] == "kuaishou_hot"
    assert evidence["collected_at"]
    assert len(evidence["samples"]) == 3
