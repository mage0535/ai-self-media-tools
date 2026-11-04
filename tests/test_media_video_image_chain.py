from unittest.mock import patch

from content_platform.media import MediaBridge
from content_platform.tool_adapters import ScriptImageProvider


def test_video_image_cfg_uses_its_own_provider_chain(tmp_path):
    bridge = MediaBridge({"image": {"provider": "auto"}, "video": {"image_provider_chain": "sense_nova,go_gemini,cloudflare"}}, tmp_path)
    assert bridge._video_image_cfg() == {"provider": "auto", "provider_chain": "sense_nova,go_gemini,cloudflare"}
    assert "provider_chain" not in MediaBridge({"image": {"provider": "auto"}}, tmp_path)._video_image_cfg()


def test_script_image_provider_passes_env_only_when_given():
    provider = ScriptImageProvider("image_gen.py", 30)
    with patch.object(provider, "_run", return_value={}) as run:
        provider.run("p", "out.png", ["--provider", "auto"])
        provider.run("p", "out.png", ["--provider", "auto"], env={"IMAGE_PROVIDER_CHAIN": "sense_nova"})
    assert run.call_args_list[0].kwargs == {"env": None}
    assert run.call_args_list[1].kwargs == {"env": {"IMAGE_PROVIDER_CHAIN": "sense_nova"}}


def test_generate_image_hands_the_role_chain_to_the_image_script(tmp_path):
    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j1", "title": "AI Agent 之 用户记忆和知识库", "body": "正文", "platforms": ["kuaishou"]}
    seen = {}

    class Stop(Exception):
        pass

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen["env"] = env
            raise Stop

    with patch.object(bridge.registry, "choose_provider", return_value=Provider()):
        try:
            bridge._generate_image(job, tmp_path / "out", {"provider": "auto", "provider_chain": "sense_nova,go_gemini"})
        except Stop:
            pass
    assert seen["env"]["IMAGE_PROVIDER_CHAIN"] == "sense_nova,go_gemini"


def test_low_semantic_article_image_is_regenerated_once_and_the_kept_review_recorded(tmp_path):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j2", "title": "AI 客服工单分类", "body": "正文", "platforms": ["juejin"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            rng = random.Random(len(calls))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "fake"}

    scores = iter([0.9, 0.6, 0.8])
    recorded = {}
    prompts = [{"role": "cover", "prompt": "cover"}, {"role": "section", "section": "s1", "prompt": "s1", "purpose": "工单分类流程"}]
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=prompts), \
            patch.object(MediaBridge, "_required_image_count", return_value=2), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})

    assert len(calls) == 3 and "工单分类流程" in calls[2]
    assert [image["semantic_review"]["score"] for image in recorded["images"]] == [0.9, 0.8]


def test_rejected_semantic_beat_is_regenerated_once_with_its_claim_first(tmp_path):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j3", "title": "两只猫", "body": "正文", "platforms": ["douyin_pet"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            rng = random.Random(len(calls))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "fake"}

    requirements = [{"intent": {"beat_id": f"s0{i}", "claim": claim, "content_match_reason": "illustrate"}, "sha256": str(i)}
                    for i, claim in enumerate(["两只猫并排睡觉", "一只猫望风另一只开柜门"], 1)]
    reviews = iter([{"score": 0.8, "requirement_match": True}, {"score": 0.8, "requirement_match": False},
                    {"score": 0.8, "requirement_match": True}])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"}, semantic_requirements=requirements)

    assert len(calls) == 3
    assert calls[0].startswith("Video topic: 两只猫\nScene to show: 两只猫并排睡觉") and "一只猫望风另一只开柜门" in calls[2]
    assert [image["semantic_review"]["requirement_match"] for image in recorded["images"]] == [True, True]
    # A fragment beat is drawn with its neighbouring narration as context.
    assert "Neighbouring narration, for what this line refers to (do not illustrate it separately): 一只猫望风另一只开柜门" in calls[0]
    assert "refers to (do not illustrate it separately): 两只猫并排睡觉" in calls[1]


def test_rejected_semantic_beat_gets_a_second_retry_told_what_the_reviewer_saw(tmp_path):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j4", "title": "两只聪明猫", "body": "正文", "platforms": ["douyin_pet"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            rng = random.Random(len(calls))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "fake"}

    requirements = [{"intent": {"beat_id": "s01", "claim": "第一步，全面排查开锁隐患。", "content_match_reason": "illustrate"},
                     "sha256": "1"}]
    reviews = iter([{"score": 0.65, "requirement_match": True, "observed_subject": "Two cats on an office desk"},
                    {"score": 0.68, "requirement_match": False, "observed_subject": "A man at a desk with a cat",
                     "reason": "omits the cabinet lock the beat names"},
                    {"score": 0.74, "requirement_match": True, "observed_subject": "Cat pawing a cabinet latch"}])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"}, semantic_requirements=requirements)

    assert len(calls) == 3
    assert "The previous image showed: Two cats on an office desk" in calls[1]
    assert "The previous image showed: A man at a desk with a cat" in calls[2]
    assert recorded["images"][0]["semantic_review"]["score"] == 0.74


def test_review_timeout_reviews_the_same_pixels_again(tmp_path):
    reviews = iter([{"status": "failed", "score": 0.0, "error": "hermes_pixel_review_timeout"},
                    {"status": "evaluated", "score": 0.81}])
    with patch("content_platform.asset_semantic_review.review_asset", side_effect=lambda *a, **k: next(reviews)) as review:
        result = MediaBridge._semantic_review(tmp_path / "a.png", {"topic": "t"}, {"section": "s1"}, {})
    assert result["score"] == 0.81
    assert review.call_count == 2


def test_beat_retry_prompt_carries_the_reviewer_reason(tmp_path):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j5", "title": "两只聪明猫", "body": "正文", "platforms": ["douyin_pet"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            rng = random.Random(len(calls))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "fake"}

    requirements = [{"intent": {"beat_id": "s07", "claim": "若误食异物必须由兽医确诊。", "content_match_reason": "illustrate"},
                     "sha256": "7"}]
    reviews = iter([{"score": 0.65, "requirement_match": False, "observed_subject": "A cat biting plastic",
                     "reason": "omits the required veterinary consultation"},
                    {"score": 0.80, "requirement_match": True, "observed_subject": "A vet examining a cat"}])
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda *a: None):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"}, semantic_requirements=requirements)
    assert "The reviewer rejected it because: omits the required veterinary consultation" in calls[1]


def test_article_images_try_a_real_photo_first_except_original_knowledge():
    chain = MediaBridge._article_image_chain({"platforms": ["zhihu"]}, {"role": "section"})
    original = MediaBridge._article_image_chain({"platforms": ["juejin"], "brief": {"content_mode": "original_knowledge"}}, {"role": "cover"})

    assert chain.split(",")[:2] == ["stock", "go_gemini"]
    assert "stock" not in original.split(",")
