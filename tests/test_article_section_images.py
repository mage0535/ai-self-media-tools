from content_platform.generator import DraftGenerator
from content_platform.media import MediaBridge

BODY = "开场段落。\n\n## 记忆分层\n\n会话记忆和长期画像分开存。\n\n## 知识库\n\n领域知识走检索。\n\n## 失效与复核\n\n过期记忆要能被纠正。\n"


def test_juejin_contract_article_binds_images_to_real_headings():
    job = {"title": "t", "topic": "AI Agent 记忆", "body": BODY, "platforms": ["juejin"], "brief": {"run_contract": {"id": "x"}}}
    prompts = MediaBridge._image_prompts(job, 4)
    assert [p["section"] for p in prompts[1:]] == ["记忆分层", "知识库", "失效与复核"]
    assert "会话记忆和长期画像分开存" in prompts[1]["prompt"]


def test_legacy_sections_use_titles_not_dict_repr():
    job = {"body": BODY, "draft_meta": {"sections": [{"id": "section_1", "title": "记忆分层", "role": "hook"}]}}
    assert MediaBridge._article_sections(job) == ["记忆分层"]


def test_article_requirements_ask_for_section_headings():
    text, _ = DraftGenerator._generation_requirements({"strategy": {"content_form": "article", "primary_platforms": ["juejin"]}})
    assert "## " in text


def test_auto_image_chain_reports_why_earlier_providers_were_skipped(tmp_path, monkeypatch):
    from content_platform import image_provider as ip

    def fail(*a, **k):
        raise ip.ImageProviderError("no usable image payload")

    def ok(prompt, output, **k):
        output.write_bytes(b"x" * 4096)
        return {"provider": "cloudflare"}

    monkeypatch.setenv("IMAGE_PROVIDER_DISABLE_CACHE", "1")
    monkeypatch.setenv("IMAGE_PROVIDER_CHAIN", "go_gemini,cloudflare")
    monkeypatch.setattr(ip, "_go_gemini_image", fail)
    monkeypatch.setattr(ip, "_cloudflare_image", ok)
    monkeypatch.setattr(ip, "_write_cache", lambda *a, **k: None)
    result = ip.generate_image("p", tmp_path / "o.png")
    assert result["provider"] == "cloudflare"
    assert result["fallback_errors"] == ["go_gemini: ImageProviderError: no usable image payload"]


def test_text_image_article_does_not_require_global_optional_audio():
    from content_platform.pipeline import Pipeline

    draft = {"title": "t", "body": "b", "draft_meta": {"content_form": "technical_article", "media_plan": ["cover", "article", "caption"]}}
    assert Pipeline._execution_media_kinds({"audio", "image", "article"}, draft, {"media": {"audio": {"enabled": True}}}) == {"image"}
    draft["draft_meta"]["voice_plan"] = [{"text": "x"}]
    assert "audio" in Pipeline._execution_media_kinds({"audio", "image"}, draft, {})
