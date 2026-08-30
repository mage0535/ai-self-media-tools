import pytest

from content_platform.image_routing import SUPPORTED_PLATFORMS, route_image_request


PLATFORM_SPECS = {
    "wechat": ([1200, 800], "3:2"),
    "xiaohongshu": ([1080, 1440], "3:4"),
    "douyin_ai": ([1080, 1920], "9:16"),
    "douyin_pet": ([1080, 1920], "9:16"),
    "kuaishou": ([1080, 1920], "9:16"),
    "bilibili": ([1920, 1080], "16:9"),
    "shipinhao": ([1080, 1920], "9:16"),
    "zhihu": ([1200, 800], "3:2"),
    "juejin": ([1200, 800], "3:2"),
    "youtube": ([1920, 1080], "16:9"),
    "tiktok": ([1080, 1920], "9:16"),
    "twitter": ([1600, 900], "16:9"),
}


@pytest.mark.parametrize(("platform", "expected"), PLATFORM_SPECS.items())
def test_all_twelve_platforms_have_deterministic_dimensions(platform, expected):
    route = route_image_request(
        platform=platform,
        role="cover",
        topic="Reliable AI workflows",
        section="Deployment checklist",
    )

    assert tuple(SUPPORTED_PLATFORMS) == tuple(PLATFORM_SPECS)
    assert (route["dimensions"], route["aspect_ratio"]) == expected
    assert route["platform"] == platform


def test_cover_uses_cinematic_cover_generation():
    route = route_image_request(platform="wechat", role="cover", topic="AI workflow")

    assert route["intent"] == "cinematic_cover"
    assert route["semantic_required"] is True
    assert route["preferred_provider_kinds"] == ["generated_image", "real_scene_search"]


def test_knowledge_card_uses_background_intent_without_semantic_subject_requirement():
    route = route_image_request(
        platform="xiaohongshu",
        role="knowledge_card",
        topic="AI workflow",
        section="Three deployment checks",
    )

    assert route["intent"] == "knowledge_card_background"
    assert route["semantic_required"] is False
    assert route["preferred_provider_kinds"] == ["generated_image"]


@pytest.mark.parametrize("role", ["section", "video_scene"])
def test_section_and_video_scene_use_content_signals_instead_of_a_fixed_provider(role):
    real_route = route_image_request(
        platform="juejin",
        role=role,
        topic="Engineering team rollout",
        section="Developers collaborating in a real office",
    )
    editorial_route = route_image_request(
        platform="juejin",
        role=role,
        topic="API architecture",
        section="Abstract data workflow and metrics",
    )

    assert real_route["intent"] == "real_scene"
    assert real_route["preferred_provider_kinds"][0] == "real_scene_search"
    assert editorial_route["intent"] == "editorial_illustration"
    assert editorial_route["preferred_provider_kinds"][0] == "generated_image"
    assert real_route["semantic_required"] is True
    assert editorial_route["semantic_required"] is True


def test_platform_is_only_a_tiebreaker_for_section_intent():
    assert route_image_request(
        platform="douyin_pet", role="section", topic="A useful update"
    )["intent"] == "real_scene"
    assert route_image_request(
        platform="zhihu", role="section", topic="A useful update"
    )["intent"] == "editorial_illustration"


def test_short_ascii_signals_do_not_match_inside_unrelated_words():
    route = route_image_request(
        platform="xiaohongshu",
        role="section",
        topic="Daily planning update",
    )

    assert route["intent"] == "real_scene"


def test_edit_requires_input_and_routes_only_to_edit_capable_providers():
    with pytest.raises(ValueError, match="input_image"):
        route_image_request(platform="youtube", role="edit", topic="AI workflow")

    route = route_image_request(
        platform="youtube",
        role="edit",
        topic="AI workflow",
        section="Remove visual clutter",
        input_image="source.png",
    )

    assert route["intent"] == "image_edit"
    assert route["preferred_provider_kinds"] == ["generated_image_and_edit"]
    assert route["semantic_required"] is True


def test_expected_concepts_are_clean_deduplicated_topic_and_section_values():
    route = route_image_request(
        platform="twitter",
        role="video_scene",
        topic="  Agent reliability  ",
        section="Agent reliability",
    )

    assert route["expected_concepts"] == ["Agent reliability"]


@pytest.mark.parametrize(
    ("platform", "role", "message"),
    [("unknown", "cover", "platform"), ("wechat", "thumbnail", "role")],
)
def test_unknown_platforms_and_roles_fail_closed(platform, role, message):
    with pytest.raises(ValueError, match=message):
        route_image_request(platform=platform, role=role, topic="Topic")
