import json
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
    chain = MediaBridge._article_image_chain({"platforms": ["zhihu"]}, {"role": "cover"})
    original = MediaBridge._article_image_chain({"platforms": ["juejin"], "brief": {"content_mode": "original_knowledge"}}, {"role": "cover"})

    assert chain.split(",")[:2] == ["stock", "go_gemini"]
    assert "stock" not in original.split(",")


def test_article_section_images_skip_stock_unless_backgrounds_must_be_real():
    # MED45: Juejin/Zhihu section photos matched 0 of 12; each miss cost a search and a review.
    assert MediaBridge._article_image_chain({"platforms": ["zhihu"]}, {"role": "section"}).split(",")[0] == "go_gemini"
    assert MediaBridge._article_image_chain({"platforms": ["juejin"]}, {"role": "section"}).split(",")[0] == "go_gemini"
    assert MediaBridge._article_image_chain({"platforms": ["xiaohongshu"]}, {"role": "section"}).startswith("stock,")


def test_a_repeated_image_does_not_pin_later_images_to_another_provider(tmp_path):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j4", "title": "AI 客服工单分类", "body": "正文", "platforms": ["xiaohongshu"]}
    seen = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen.append((extra_args[extra_args.index("--provider") + 1], (env or {}).get("IMAGE_PROVIDER_CHAIN", "")))
            seed = 1 if len(seen) <= 2 else len(seen)  # the second image first repeats the first one
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(seed).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "pexels" if len(seen) == 2 else "go_gemini"}

    prompts = [{"role": "cover", "prompt": "cover"}, {"role": "section", "section": "s1", "prompt": "s1"},
               {"role": "section", "section": "s2", "prompt": "s2"}]
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=prompts), \
            patch.object(MediaBridge, "_required_image_count", return_value=3), \
            patch.object(MediaBridge, "_semantic_review", return_value={"score": 0.9}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})

    assert all(provider == "auto" for provider, _ in seen)
    assert seen[2][1].split(",")[0] == "go_gemini" and seen[3][1].startswith("stock")


def test_cover_title_overflow_falls_back_to_the_main_clause(tmp_path):
    calls = []

    def render(background, output, *, draft_title, cover_design, **kwargs):
        calls.append(draft_title)
        if len(draft_title) > 22:
            raise ValueError("wechat_cover_title_overflow")
        return {"path": str(background), "provider_result": {}, "cover_design": cover_design}

    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    job = {"title": "从零搭建 LangGraph 旅行规划师：生成的行程哪些还得自己查", "platforms": ["juejin"]}
    with patch("content_platform.wechat_cover_render.render_wechat_cover", side_effect=render):
        design = MediaBridge._compose_wechat_cover(tmp_path, [{"role": "cover", "path": str(cover)}], job)

    assert calls[-1] == "从零搭建 LangGraph 旅行规划师" and design["title_text"] == calls[-1]


def _weak_stock_retry_chains(tmp_path, platform):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j5", "title": "猫粮换粮 AI 记录", "body": "正文", "platforms": [platform]}
    seen = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen.append((env or {}).get("IMAGE_PROVIDER_CHAIN", ""))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(seen)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "pexels"}

    scores = iter([0.6, 0.9])
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=[{"role": "cover", "prompt": "cover"}]), \
            patch.object(MediaBridge, "_required_image_count", return_value=1), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})
    return seen


def test_weak_stock_photo_retries_stock_only_where_backgrounds_must_be_real(tmp_path):
    # MED37: Xiaohongshu card backgrounds must be real photos, so its semantic retry searches stock again.
    assert _weak_stock_retry_chains(tmp_path / "x", "xiaohongshu")[1].startswith("stock,")
    # Articles accept declared generated illustrations (MED35): a weak photo gives way to a generated scene.
    assert not _weak_stock_retry_chains(tmp_path / "j", "juejin")[1].startswith("stock")


def _beat_chains(tmp_path, platform, provider_name, content_mode=""):
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j9", "title": "两只猫", "body": "正文", "platforms": [platform], "brief": {"content_mode": content_mode}}
    seen = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen.append((env or {}).get("IMAGE_PROVIDER_CHAIN", ""))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(seen)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": provider_name}

    requirements = [{"intent": {"beat_id": "s01", "claim": "两只猫并排睡觉", "content_match_reason": "illustrate"}, "sha256": "1"}]
    reviews = iter([{"score": 0.6, "requirement_match": False}, {"score": 0.9, "requirement_match": True}])
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto", "provider_chain": "go_gemini,cloudflare"},
                               semantic_requirements=requirements)
    return seen


def test_video_beats_search_licensed_stock_first_and_retry_on_stock(tmp_path):
    """MED39 (r108): rendered video scenes must be licensed real photos, but beats only ever drew generated images."""
    for platform in ("douyin_pet", "kuaishou"):
        chains = _beat_chains(tmp_path / platform, platform, "pexels")
        assert chains == ["stock,go_gemini,cloudflare", "stock,go_gemini,cloudflare"]
    # Original-knowledge jobs only take new generated assets; other lanes keep their configured chain.
    assert _beat_chains(tmp_path / "o", "douyin_pet", "fake", "original_knowledge")[0] == "go_gemini,cloudflare"
    assert _beat_chains(tmp_path / "w", "wechat_channels", "fake")[0] == "go_gemini,cloudflare"


def test_provenance_declares_real_scene_only_for_a_licensed_stock_photo(tmp_path):
    from pathlib import Path
    from PIL import Image

    out = tmp_path / "p"; out.mkdir()
    images = []
    for index, result in enumerate([{"provider": "pexels", "mode": "search", "license": "Pexels",
                                     "source_url": "https://www.pexels.com/photo/1/", "photo_id": "1",
                                     "page_url": "https://www.pexels.com/photo/1/", "photographer": "p", "query": "cat",
                                     "download_url": "https://images.pexels.com/photos/1/a.jpeg",
                                     "license_url": "https://www.pexels.com/license/", "downloaded_at": "2026-11-05T20:00:00+00:00"},
                                    {"provider": "go_gemini", "model": "m"}]):
        path = out / f"section-{index:02d}.png"
        Image.new("RGB", (8, 8)).save(path)
        images.append({"path": str(path), "role": "section", "section": f"s0{index}", "provider_result": result,
                       "semantic_review": {"score": 0.9}})
    MediaBridge._persist_asset_provenance(out, images, [], "fake", {"title": "t"})
    rows = json.loads(Path(out / "asset_provenance.json").read_text(encoding="utf-8"))["assets"]
    assert [(row["real_scene"], row["rights_cleared"]) for row in rows] == [(True, True), (False, False)]
    # MED50: the stock photo's own record reaches the video background gate; a generated image gets none of it.
    assert rows[0]["photo_id"] == "1" and rows[0]["downloaded_at"] and "photo_id" not in rows[1]


def test_rejected_duplicate_retry_keeps_the_previous_image(tmp_path):
    """MED41 (r109): a stock retry repeated beat 1's photo; the rejected file overwrote the kept image and the job
    stopped with 'image retry left an unrecorded file'."""
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j10", "title": "客服", "body": "正文", "platforms": ["kuaishou"]}
    seeds = iter([1, 2, 1, 4])

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            rng = random.Random(next(seeds))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "pexels"}

    requirements = [{"intent": {"beat_id": f"s0{i}", "claim": claim, "content_match_reason": "illustrate"}, "sha256": str(i)}
                    for i, claim in enumerate(["客服坐席查看工单", "主管审批特批退款"], 1)]
    reviews = iter([{"score": 0.9, "requirement_match": True}, {"score": 0.6, "requirement_match": False},
                    {"score": 0.9, "requirement_match": True}])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: next(reviews)), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"}, semantic_requirements=requirements)
    images = recorded["images"]
    assert [image["semantic_review"]["requirement_match"] for image in images] == [True, True]
    assert images[0]["checksum"] != images[1]["checksum"]
    import hashlib
    assert hashlib.sha256(Path(images[1]["path"]).read_bytes()).hexdigest() == images[1]["checksum"]


def test_beat_uses_its_preselected_photo_first(tmp_path):
    """MED42: the narration was written from these photos, so each beat's first candidate is its own photo."""
    import hashlib
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    photos = []
    for i in range(2):
        path = tmp_path / f"photo-{i}.png"
        Image.frombytes("L", (64, 64), bytes(random.Random(10 + i).randrange(256) for _ in range(64 * 64))).save(path)
        photos.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "provider_result": {"provider": "pexels", "source_url": "https://www.pexels.com/photo/%d/" % i, "license": "Pexels"}})
    job = {"id": "j11", "title": "两只猫", "body": "正文", "platforms": ["douyin_pet"],
           "draft_meta": {"beat_photo_plan": {"photos": photos}}}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            return {"provider": "fake"}

    requirements = [{"intent": {"beat_id": f"s0{i}", "claim": claim, "content_match_reason": "illustrate"}, "sha256": str(i)}
                    for i, claim in enumerate(["两只猫并排睡觉", "一只猫望风"], 1)]
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch("content_platform.video_asset_semantics.validate_requirement", side_effect=lambda r: r), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": 0.9, "requirement_match": True}), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"}, semantic_requirements=requirements)
    assert calls == []
    assert [image["provider_result"]["source_url"] for image in recorded["images"]] == [row["provider_result"]["source_url"] for row in photos]
    assert [image["checksum"] for image in recorded["images"]] == [row["sha256"] for row in photos]
    # A photo changed since it was picked is not used.
    Path(photos[1]["path"]).write_bytes(b"changed")
    assert MediaBridge._planned_beat_photos(job, [{"semantic_requirement": 1}, {"semantic_requirement": 1}]) == []


def test_article_image_gets_a_second_regeneration_before_blocking(tmp_path):
    # MED47 (r115): a Juejin section stayed 0.65 after one regeneration and blocked the article.
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j6", "title": "AI 排产", "body": "正文", "platforms": ["juejin"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(calls)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "go_gemini"}

    scores = iter([0.6, 0.65, 0.8])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=[{"role": "cover", "prompt": "cover"}]), \
            patch.object(MediaBridge, "_required_image_count", return_value=1), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})
    assert len(calls) == 3 and recorded["images"][0]["semantic_review"]["score"] == 0.8


def test_a_regeneration_the_provider_rejects_keeps_the_previous_image(tmp_path):
    # MED49 (r117): the provider's flat-image check raised during a retry and failed the whole job.
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j7", "title": "AI 排产", "body": "正文", "platforms": ["juejin"]}
    calls = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            calls.append(prompt)
            if len(calls) == 2:
                Path(output).write_bytes(b"partial")
                raise RuntimeError("标准差 13.8 < 15，画面过于单一")
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(calls)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "go_gemini"}

    scores = iter([0.6, 0.8])
    recorded = {}
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=[{"role": "cover", "prompt": "cover"}]), \
            patch.object(MediaBridge, "_required_image_count", return_value=1), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", side_effect=lambda d, images, *a: recorded.setdefault("images", images)):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})
    assert len(calls) == 3 and recorded["images"][0]["semantic_review"]["score"] == 0.8


def test_real_background_stock_retries_take_the_next_search_result(tmp_path, monkeypatch):
    # MED51 (r121): Xiaohongshu stock retries kept getting the top photo of a similar query (0.36-0.48).
    import random
    from pathlib import Path
    from PIL import Image

    bridge = MediaBridge({}, tmp_path)
    job = {"id": "j8", "title": "AI 工作流", "body": "正文", "platforms": ["xiaohongshu"]}
    seen = []

    class Provider:
        def run(self, prompt, output, extra_args=None, env=None):
            seen.append((env or {}).get("IMAGE_STOCK_RESULT_INDEX", "0"))
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Image.frombytes("L", (64, 64), bytes(random.Random(len(seen)).randrange(256) for _ in range(64 * 64))).save(output)
            return {"provider": "pexels"}

    scores = iter([0.4, 0.5, 0.8])
    with patch.object(bridge.registry, "choose_provider", return_value=Provider()), \
            patch.object(MediaBridge, "_image_prompts", return_value=[{"role": "cover", "prompt": "cover"}]), \
            patch.object(MediaBridge, "_required_image_count", return_value=1), \
            patch.object(MediaBridge, "_semantic_review", side_effect=lambda *a: {"score": next(scores)}), \
            patch.object(MediaBridge, "_compose_wechat_cover", return_value={}), \
            patch.object(MediaBridge, "_bound_section_image_map", return_value=[]), \
            patch.object(MediaBridge, "_persist_asset_provenance", return_value=None):
        bridge._generate_image(job, tmp_path / "out", {"provider": "auto"})
    assert seen == ["0", "1", "2"]


def test_pexels_result_index_comes_from_the_environment(monkeypatch):
    from content_platform import image_provider
    monkeypatch.setenv("IMAGE_STOCK_RESULT_INDEX", "2")
    assert image_provider._stock_result_index() == 2
    monkeypatch.setenv("IMAGE_STOCK_RESULT_INDEX", "x")
    assert image_provider._stock_result_index() == 0
