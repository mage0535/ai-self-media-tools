import hashlib

from PIL import Image, ImageStat


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_deterministic_editorial_visual_is_stable_distinct_and_render_ready(tmp_path):
    from content_platform.deterministic_visual import render_editorial_visual

    first = tmp_path / "first.png"
    repeated = tmp_path / "repeated.png"
    different = tmp_path / "different.png"
    kwargs = {
        "role": "cover",
        "size": (1200, 800),
        "title": "Agent Skills 操作手册",
        "subtitle": "把输入、技能和验证连成工作流",
        "concepts": ["connected workflow task nodes", "step-by-step operating playbook"],
        "accent": "#1E80FF",
    }

    evidence = render_editorial_visual(first, **kwargs)
    render_editorial_visual(repeated, **kwargs)
    render_editorial_visual(
        different,
        **{**kwargs, "concepts": ["side-by-side software module format comparison"]},
    )

    assert _sha(first) == _sha(repeated)
    assert _sha(first) != _sha(different)
    with Image.open(first) as image:
        assert image.size == (1200, 800)
        assert ImageStat.Stat(image.resize((64, 64)).convert("RGB")).stddev[0] >= 18
    assert evidence["provider"] == "cover_renderer"
    assert evidence["model"] == "deterministic_editorial_v1"
    assert evidence["license"] == "generated_for_project"
    assert evidence["semantic_concepts"] == kwargs["concepts"]
    assert evidence["output_sha256"] == _sha(first)


def test_deterministic_editorial_visual_routes_section_capability(tmp_path):
    from content_platform.deterministic_visual import render_editorial_visual

    output = tmp_path / "section.png"
    evidence = render_editorial_visual(
        output,
        role="section",
        size=(1200, 800),
        title="CommonJS 与 ESM",
        subtitle="模块格式并排对比",
        concepts=["side-by-side software module format comparison", "software development interface"],
        accent="#1E80FF",
    )

    assert evidence["provider"] == "knowledge_card_renderer"
    assert evidence["output_sha256"] == _sha(output)


def test_media_bridge_uses_deterministic_fallback_only_for_abstract_final_attempt():
    from content_platform.media import MediaBridge

    assert MediaBridge._use_deterministic_article_visual(
        {"intent": "cinematic_cover", "role": "cover"}, attempt=3, max_attempts=3
    ) is True
    assert MediaBridge._use_deterministic_article_visual(
        {"intent": "editorial_illustration", "role": "section"}, attempt=3, max_attempts=3
    ) is True
    assert MediaBridge._use_deterministic_article_visual(
        {"intent": "real_scene", "role": "section"}, attempt=3, max_attempts=3
    ) is False
    assert MediaBridge._use_deterministic_article_visual(
        {"intent": "cinematic_cover", "role": "cover"}, attempt=2, max_attempts=3
    ) is False
