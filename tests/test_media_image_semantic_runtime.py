import json
from pathlib import Path

from PIL import Image

from content_platform.media import MediaBridge


def _image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (768, 1024), color).save(path)


def test_media_bridge_uses_top_level_analysis_configuration(tmp_path: Path) -> None:
    analyzer = tmp_path / "analyze.py"
    analyzer.write_text("print('{}')\n", encoding="utf-8")

    bridge = MediaBridge(
        {"image": {"enabled": True}},
        tmp_path,
        tool_config={"analysis": {"script": str(analyzer), "timeout": 12}},
    )

    provider = bridge.registry.choose_provider("analysis")
    assert provider is not None
    assert provider.script == str(analyzer)


def test_semantic_analysis_is_computed_from_analyzer_output(tmp_path: Path) -> None:
    analyzer = tmp_path / "analyze.py"
    analyzer.write_text(
        "import hashlib,json,sys\n"
        "sha=hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()\n"
        "print(json.dumps({'ok': True, 'analyzer': 'fixture', 'caption': 'a developer using an AI workflow dashboard', "
        "'labels': ['developer','workflow','dashboard'], 'expected_concepts': ['workflow','dashboard'], "
        "'matched_concepts': ['workflow','dashboard'], 'semantic_match_score': 1.0, 'threshold': 0.55, 'passed': True, 'image_sha256': sha}))\n",
        encoding="utf-8",
    )
    image = tmp_path / "candidate.png"
    _image(image, (30, 80, 130))
    bridge = MediaBridge({}, tmp_path, tool_config={"analysis": {"script": str(analyzer)}})

    evidence = bridge._analyze_image_semantics(
        image,
        {"expected_concepts": ["AI workflow", "dashboard"], "role": "section", "platform": "juejin"},
    )

    assert evidence["passed"] is True
    assert evidence["analyzer"] == "fixture"
    assert evidence["semantic_match_score"] == 1.0
    assert evidence["caption"].startswith("a developer")


def test_required_semantic_analysis_fails_closed_when_analyzer_unavailable(tmp_path: Path) -> None:
    image = tmp_path / "candidate.png"
    _image(image, (50, 90, 140))
    bridge = MediaBridge({}, tmp_path, tool_config={"analysis": {"script": str(tmp_path / 'missing.py')}})

    evidence = bridge._analyze_image_semantics(
        image,
        {"expected_concepts": ["AI workflow"], "role": "cover", "platform": "xiaohongshu"},
    )

    assert evidence["passed"] is False
    assert evidence["failure"] == "semantic_analyzer_unavailable"


def test_provenance_uses_real_semantic_evidence_not_constant_score(tmp_path: Path) -> None:
    image = tmp_path / "cover.png"
    _image(image, (20, 70, 120))
    semantic = {
        "passed": True,
        "analyzer": "fixture-vision",
        "caption": "AI workflow dashboard",
        "labels": ["AI", "workflow", "dashboard"],
        "expected_concepts": ["workflow"],
        "matched_concepts": ["workflow"],
        "semantic_match_score": 0.91,
        "threshold": 0.55,
        "output_sha256": "a" * 64,
    }

    MediaBridge._persist_asset_provenance(
        tmp_path,
        [{
            "role": "cover",
            "path": str(image),
            "checksum": "b" * 64,
            "semantic_evidence": semantic,
            "source_url": "generated:fixture",
            "license": "generated_for_project",
        }],
        [{"role": "cover", "section": "cover", "purpose": "topic cover", "prompt": "workflow", "expected_concepts": ["workflow"]}],
        "fixture",
        {"title": "AI workflow", "platforms": ["xiaohongshu"], "draft_meta": {}},
    )

    payload = json.loads((tmp_path / "asset_provenance.json").read_text(encoding="utf-8"))
    record = payload["assets"][0]
    assert record["semantic_match_score"] == 0.91
    assert record["semantic_evidence"]["analyzer"] == "fixture-vision"
    assert record["semantic_evidence"]["output_sha256"] == "a" * 64


def test_semantic_mismatch_reselects_candidate_before_acceptance(tmp_path: Path, monkeypatch) -> None:
    class Provider:
        calls = 0

        def run(self, _prompt, output, _args):
            self.calls += 1
            image = Image.new("RGB", (768, 1024))
            pixels = image.load()
            for y in range(1024):
                for x in range(768):
                    block = (x // 24 + y // 24 + self.calls) % 3
                    pixels[x, y] = [(220, 30, 50), (20, 190, 90), (30, 70, 220)][block]
            image.save(output)
            return {"provider": "fixture", "model": "fixture", "license": "generated_for_project"}

    bridge = MediaBridge(
        {"image": {"semantic_validation_required": True, "quality_recovery_attempts": 3}},
        tmp_path,
        tool_config={"strict_media_contract": True},
    )
    analyzer_calls = []

    def analyze(path, _request):
        analyzer_calls.append(Path(path).read_bytes())
        passed = len(analyzer_calls) == 2
        sha = __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()
        return {
            "version": "image_semantic_evidence_v1", "analyzer": "fixture", "caption": "workflow" if passed else "cat",
            "labels": ["workflow"] if passed else ["cat"], "expected_concepts": ["workflow"],
            "matched_concepts": ["workflow"] if passed else [], "semantic_match_score": 1.0 if passed else 0.0,
            "threshold": 0.55, "passed": passed, "image_sha256": sha,
            "score_source": "deterministic_caption_label_recall", "evidence_level": "artifact_verified",
        }

    monkeypatch.setattr(bridge, "_analyze_image_semantics", analyze)
    provider = Provider()
    output = tmp_path / "section.png"
    recovery = bridge._image_quality_recovery_plan(
        {"platforms": ["xiaohongshu"], "content_form": "carousel"},
        bridge.config["image"],
    )

    gate = bridge._run_image_provider_with_quality_recovery(
        provider,
        {"role": "section", "section": "workflow", "purpose": "explain", "prompt": "workflow", "intent": "real_scene"},
        {"platforms": ["xiaohongshu"], "topic": "workflow"},
        output,
        [],
        tmp_path,
        set(),
        set(),
        recovery,
    )

    assert provider.calls == 2
    assert len(analyzer_calls) == 2
    assert gate["passed"] is True
    assert gate["semantic_evidence"]["caption"] == "workflow"
    assert recovery["attempts"][0]["passed"] is False
    assert recovery["attempts"][1]["passed"] is True


def test_provider_retry_order_is_content_intent_specific(monkeypatch):
    monkeypatch.setenv("AGNES_IMAGE_AUTO_ENABLED", "1")
    first = MediaBridge._image_provider_args(
        ["--provider", "auto", "--size", "1024x1024"],
        {"intent": "real_scene", "size": "1080x1920"},
        attempt=1,
        rotate=True,
    )
    second = MediaBridge._image_provider_args(
        ["--provider", "auto", "--size", "1024x1024"],
        {"intent": "real_scene", "size": "1080x1920"},
        attempt=2,
        rotate=True,
    )
    cover = MediaBridge._image_provider_args(
        ["--provider", "auto"],
        {"intent": "cinematic_cover", "size": "1080x1440"},
        attempt=1,
        rotate=True,
    )

    assert first[first.index("--provider") + 1] == "stock"
    assert second[second.index("--provider") + 1] == "agnes"
    assert cover[cover.index("--provider") + 1] == "agnes"


def test_cover_semantic_request_excludes_non_visual_workflow_labels():
    request = MediaBridge._semantic_request(
        {"platforms": ["xiaohongshu"], "topic": "AI workflow dashboard", "title": "AI workflow dashboard"},
        {"role": "cover", "section": "cover", "purpose": "introduce the article promise with a topic-matched visual", "expected_concepts": ["AI workflow dashboard", "cover"]},
    )

    assert request["expected_concepts"] == ["AI workflow dashboard"]


def test_semantic_analysis_retries_nondeterministic_mismatch(tmp_path, monkeypatch):
    image = tmp_path / "cover.png"
    _image(image, (20, 40, 80))
    bridge = MediaBridge({}, tmp_path)
    sha = __import__("hashlib").sha256(image.read_bytes()).hexdigest()
    values = iter([
        {"analyzer":"fixture","caption":"office","labels":["office"],"expected_concepts":["workflow"],"matched_concepts":[],"semantic_match_score":0.0,"threshold":0.6,"passed":False,"image_sha256":sha},
        {"analyzer":"fixture","caption":"workflow dashboard","labels":["workflow","dashboard"],"expected_concepts":["workflow"],"matched_concepts":["workflow"],"semantic_match_score":1.0,"threshold":0.6,"passed":True,"image_sha256":sha},
    ])
    provider = type("Provider", (), {"run": lambda self, target, args: next(values)})()
    monkeypatch.setattr(bridge.registry, "choose_provider", lambda kind: provider)

    result = bridge._analyze_image_semantics(image, {"expected_concepts":["workflow"],"role":"cover","platform":"xiaohongshu"}, attempts=2)

    assert result["passed"] is True
    assert result["semantic_match_score"] == 1.0


def test_cover_derivative_rebinds_parent_semantics_to_final_artifact(tmp_path):
    output = tmp_path / "cover.png"
    _image(output, (30, 80, 140))
    parent = {"passed": True, "image_sha256": "a" * 64, "semantic_match_score": 0.9, "caption": "workflow dashboard"}

    result = MediaBridge._derive_cover_semantic_evidence(parent, output, {"passed": True, "renderer": "poster"})

    assert result["passed"] is True
    assert result["derivative_of_sha256"] == "a" * 64
    assert result["image_sha256"] == __import__("hashlib").sha256(output.read_bytes()).hexdigest()
    assert result["derivative_transform"] == "cover_title_and_layout_overlay"


def test_grounded_article_headings_compile_to_visible_section_concepts():
    job = {
        "platforms": ["juejin"],
        "topic": "Agent Skills 入门",
        "title": "Agent Skills 入门",
    }

    directory = MediaBridge._semantic_request(
        job,
        {"role": "section", "section": "Agent Skill 目录与 SKILL.md", "purpose": "explain the adjacent point"},
    )
    resources = MediaBridge._semantic_request(
        job,
        {"role": "section", "section": "scripts、references 与 assets 资源结构", "purpose": "explain the adjacent point"},
    )
    loading = MediaBridge._semantic_request(
        job,
        {"role": "section", "section": "按需加载正文与其他资源", "purpose": "explain the adjacent point"},
    )

    assert directory["expected_concepts"] == ["structured skill directory documents"]
    assert resources["expected_concepts"] == ["structured skill directory documents"]
    assert loading["expected_concepts"] == ["selective document loading sequence"]
    assert all("核心定义" not in value for value in directory["expected_concepts"])


def test_deterministic_section_visual_copy_does_not_reuse_cover_headline():
    job = {
        "title": "cover title",
        "topic": "cover topic",
        "draft_meta": {"cover_design": {"title_text": "COVER", "subtitle_text": "COVER SUBTITLE"}},
    }

    title, subtitle = MediaBridge._deterministic_visual_copy(
        job,
        {"role": "section", "section": "scripts、references 与 assets 资源结构", "purpose": "explain files"},
    )

    assert title == "scripts、references 与 assets 资源结构"
    assert subtitle == "explain files"
    assert "COVER" not in title + subtitle


def test_deterministic_visual_semantics_require_vision_structure_and_hash_bound_labels(tmp_path):
    import hashlib
    from content_platform.media import MediaBridge

    image = tmp_path / "card.png"
    image.write_bytes(b"deterministic-card")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    parent = {
        "ok": True,
        "passed": False,
        "caption": "Two panels show eight tool items and a task checklist.",
        "labels": ["two panels", "tool items", "task checklist"],
        "semantic_match_score": 0.12,
        "expected_concepts": ["multiple software tool tabs and unfinished task list"],
        "image_sha256": sha,
        "output_sha256": sha,
    }
    renderer = {
        "provider": "knowledge_card_renderer",
        "output_sha256": sha,
        "semantic_concepts": ["multiple software tool tabs and unfinished task list"],
        "visible_labels": ["8个工具标签页", "任务清单", "待处理", "未完成", "未开始"],
    }

    derived = MediaBridge._derive_deterministic_semantic_evidence(parent, image, renderer)

    assert derived["passed"] is True
    assert derived["evidence_sources"] == ["cloudflare_workers_ai", "knowledge_card_renderer"]
    assert derived["image_sha256"] == sha
    assert MediaBridge._derive_deterministic_semantic_evidence(parent, image, {**renderer, "output_sha256": "bad"})["passed"] is False
    assert MediaBridge._derive_deterministic_semantic_evidence(parent, image, {**renderer, "provider": "sense_nova"})["passed"] is False
    assert MediaBridge._derive_deterministic_semantic_evidence({**parent, "caption": "office portrait", "labels": ["office"]}, image, renderer)["passed"] is False
    mistranscribed = {
        **parent,
        "caption": "Two dark blue rectangles are shown. The left rectangle contains eight numbered options. The right rectangle is titled 任务清单 and contains three checkboxes.",
        "labels": ["two rectangles", "eight numbered options", "任务清单", "checkboxes"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(mistranscribed, image, renderer)["passed"] is True
    geometry_only = {
        **parent,
        "caption": "Two dark blue rectangles are shown. The left rectangle contains eight lines and outlined boxes. The right rectangle contains three lines and outlined boxes.",
        "labels": ["two rectangles", "eight lines", "three lines", "outlined boxes"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(geometry_only, image, renderer)["passed"] is True
    counted_sections = {
        **parent,
        "caption": "The graphic is divided into two sections. The left section has a list of eight items in rectangular boxes. The right section has a list of three items.",
        "labels": ["two sections", "eight items", "rectangular boxes", "three items"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(counted_sections, image, renderer)["passed"] is True

    goal_renderer = {
        **renderer,
        "semantic_concepts": ["goal input output checklist card"],
        "visible_labels": ["目标", "明确结果", "输入", "核对材料", "输出", "设定验收"],
    }
    vertical_cards = {
        **parent,
        "expected_concepts": ["goal input output checklist card"],
        "caption": "Four rectangular boxes with rounded corners are arranged in a vertical column as an infographic.",
        "labels": ["rectangular boxes", "vertical column", "infographic"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(vertical_cards, image, goal_renderer)["passed"] is True
    partial_ocr_cards = {
        **parent,
        "expected_concepts": ["goal input output checklist card"],
        "caption": "Four rectangular boxes contain Chinese text. One is labelled 入 for input, another 出 for output, and another 设定.",
        "labels": ["rectangular boxes", "input", "output", "settings"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(partial_ocr_cards, image, goal_renderer)["passed"] is True
    chinese_partial_ocr = {
        **parent,
        "expected_concepts": ["goal input output checklist card"],
        "caption": "四个矩形文本框排列成两行，可见中文标签目标、输入、输出和设定验收。",
        "labels": ["矩形文本框", "目标", "输入", "输出", "设定验收"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(chinese_partial_ocr, image, goal_renderer)["passed"] is True

    boundary_renderer = {
        **renderer,
        "semantic_concepts": ["four-panel task boundary checklist"],
        "visible_labels": ["目标", "明确吗？", "输入", "齐全吗？", "验收", "可检查吗？", "卡点", "明确吗？"],
    }
    four_grid = {
        **parent,
        "expected_concepts": ["four-panel task boundary checklist"],
        "caption": "Four rectangular panels are arranged in two rows of two, each with a checkbox and question.",
        "labels": ["four panels", "two rows of two", "checkboxes"],
    }
    assert MediaBridge._derive_deterministic_semantic_evidence(four_grid, image, boundary_renderer)["passed"] is True


def test_only_project_renderers_are_eligible_for_dual_semantic_evidence():
    from content_platform.media import MediaBridge

    assert MediaBridge._is_deterministic_renderer_result({"provider": "knowledge_card_renderer"}) is True
    assert MediaBridge._is_deterministic_renderer_result({"provider": "cover_renderer"}) is True
    assert MediaBridge._is_deterministic_renderer_result({"provider": "pixazo"}) is False
    assert MediaBridge._is_deterministic_renderer_result({"provider": "sense_nova"}) is False
