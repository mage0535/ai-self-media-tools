from content_platform.video_director import build_video_route


def test_video_route_varies_by_platform_content_and_assets():
    vertical = build_video_route(
        platform="kuaishou",
        title="Three steps for an AI workflow",
        body="A practical checklist: first step, second step, then verify the result.",
        content_form="knowledge_card_video",
    )
    horizontal = build_video_route(
        platform="bilibili",
        title="AI 工作流深度拆解",
        body="从原理、演示到结果验证。",
        content_form="article_explainer_video",
    )
    footage = build_video_route(
        platform="tiktok",
        title="AI tools in real life",
        body="Eight real clips show the workflow.",
        content_form="short_video",
        available_assets={"footage_count": 8},
    )

    assert vertical["renderer_id"] == "layered_card_renderer"
    assert horizontal["renderer_id"] == "landscape_explainer_renderer"
    assert footage["renderer_id"] == "real_footage_renderer"
    assert len(set(vertical["scene_presentations"])) >= 5


def test_video_route_avoids_same_platform_style_used_within_three_days():
    first = build_video_route(
        platform="kuaishou",
        title="AI API 实测",
        body="展示界面和 API 接入证据。",
        content_form="knowledge_card_video",
    )
    second = build_video_route(
        platform="kuaishou",
        title="AI API 实测",
        body="展示界面和 API 接入证据。",
        content_form="knowledge_card_video",
        recent_style_ids=[first["style_id"]],
    )

    assert second["style_id"] != first["style_id"]
    assert second["history_window_days"] == 3
