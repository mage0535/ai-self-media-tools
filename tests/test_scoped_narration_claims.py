import re
from types import SimpleNamespace

from content_platform.pipeline import Pipeline


class Runner:
    def __init__(self):
        self.blocked = []

    def block(self, step, code, message, gate, depends_on=None):
        self.blocked.append(step)


def _pipeline():
    ok = SimpleNamespace(evaluate=lambda *args: {"level": "pass", "findings": []})
    return SimpleNamespace(risk=ok, compliance=ok, store=SimpleNamespace(record_event=lambda *args: None))


BODY = "这是一个可以复用的工作流拆解，先整理输入，再交给模型生成结构化结果，最后由人工复核每一步输出。" * 2


def test_unsupported_sentence_is_removed_when_the_rest_passes():
    draft = {"title": "工作流拆解", "body": BODY + "\n若剩余有效期不足 6 个月，前置触发风险警报。"}
    runner = Runner()

    Pipeline._validate_scoped_narrations(_pipeline(), "job", draft, {"juejin": {"run_contract": {"id": 1}}}, runner)

    assert runner.blocked == []
    assert "6 个月" not in draft["body"]
    assert draft["draft_meta"]["claim_sanitization"]["removed_count"] == 1


def test_numeric_only_title_keeps_its_words_without_the_number():
    body = "这是一段足够长的正文，说明多 Agent 协同编辑的架构推演与人工复核边界，没有任何数字结论。" * 3
    draft = {"title": "实测避坑：10年前端带AI做在线协同文档的架构推演", "body": body}
    runner = Runner()

    Pipeline._validate_scoped_narrations(_pipeline(), "job", draft, {"zhihu": {"run_contract": {"id": 1}}}, runner)

    assert runner.blocked == []
    assert draft["title"] == "实测避坑：前端带AI做在线协同文档的架构推演"


def test_short_body_after_cleanup_still_blocks():
    draft = {"title": "工作流拆解", "body": "节省 3 小时。"}
    runner = Runner()

    Pipeline._validate_scoped_narrations(_pipeline(), "job", draft, {"juejin": {"run_contract": {"id": 1}}}, runner)

    assert runner.blocked == ["validate_factual_claims"]
    assert draft["body"] == "节省 3 小时。"


def test_humanizer_uses_generator_timeout(monkeypatch):
    seen = {}

    def fake_call(prompt, system="", timeout=60):
        seen["timeout"] = timeout
        return '{"title": "工作流拆解", "body": "' + BODY + '", "changes": [], "score": 40}'

    monkeypatch.setattr("content_platform.humanizer._hermes_llm_call", fake_call)
    pipeline = SimpleNamespace(config={"generator": {"timeout": 600}}, store=SimpleNamespace(record_event=lambda *a: None),
                               _validate_draft_structure=lambda item: None)
    draft = {"title": "工作流拆解", "body": BODY}

    Pipeline._humanize_draft(pipeline, "job", draft)

    assert seen["timeout"] == 600


def test_humanizer_keeps_short_video_script_when_rewrite_merges_paragraphs(monkeypatch):
    script = "猫为什么会拆家？\n\n第一步，换锁扣。\n\n第二步，加益智玩具。\n\n你家猫会合作吗？"
    merged = "猫为什么会拆家。原因很多。第一步换锁扣。第二步加益智玩具。第三步分开喂。你家猫会合作吗。"
    monkeypatch.setattr("content_platform.humanizer.humanize_text",
                        lambda title, body, **_: {"ok": True, "title": title, "body": merged, "score": 40, "patterns_detected": ["x"]})
    events = []
    pipeline = SimpleNamespace(config={}, store=SimpleNamespace(record_event=lambda *a: events.append(a[1])),
                               _validate_draft_structure=lambda item: None)
    draft = {"title": "t", "body": script, "draft_meta": {"strategy": {"primary_platforms": ["douyin_pet"]}}}

    Pipeline._humanize_draft(pipeline, "job", draft)

    assert draft["body"] == script and "humanize_rejected_structure" in events


def test_fit_article_length_never_ends_inside_code_and_keeps_language():
    from content_platform.generator import DraftGenerator

    para = "这是一段较长的中文说明，用于测试截断。" * 20
    code = "```python\n" + "\n\n".join(f"x{i} = {i}" for i in range(400)) + "\n```"
    body = "\n\n".join([para] * 6) + "\n\n" + code + "\n\n" + para

    fitted = DraftGenerator._fit_article_length(body, {"strategy": {"content_form": "technical_article"}})

    assert fitted.count("```") % 2 == 0
    assert "落地要点" not in fitted and "Practical takeaway" not in fitted


def test_fit_article_length_also_bounds_zhihu_evidence_answers():
    from content_platform.generator import DraftGenerator

    body = "\n\n".join(["## 判断\n\n" + "条件化判断与案例说明。" * 40] * 10)

    fitted = DraftGenerator._fit_article_length(body, {"strategy": {"content_form": "evidence_answer"}})

    assert 1200 <= len("".join(fitted.split())) <= 3000


def test_fit_article_length_drops_middle_sections_and_keeps_own_conclusion():
    from content_platform.generator import DraftGenerator

    mids = [f"## 步骤{i}\n\n" + f"第{i}步的具体做法与检查。" * 30 for i in range(8)]
    body = "开头说明问题。\n\n" + "\n\n".join(mids) + "\n\n## 结论\n\n本文自己的结论。"

    fitted = DraftGenerator._fit_article_length(body, {"strategy": {"content_form": "technical_article"}})

    assert len("".join(fitted.split())) <= 3000
    assert fitted.startswith("开头说明问题") and fitted.endswith("本文自己的结论。")
    assert "## 步骤0" in fitted and "落地要点" not in fitted


def test_fit_article_length_renumbers_sections_after_dropping_one():
    from content_platform.generator import DraftGenerator

    cn = "一二三四五"
    mids = [f"## {cn[i]}、第{i}部分\n\n" + f"第{i}部分的做法。" * (250 if i == 2 else 80) for i in range(5)]
    body = "开头。\n\n" + "\n\n".join(mids) + "\n\n## 结语\n\n结论。"

    fitted = DraftGenerator._fit_article_length(body, {"strategy": {"content_form": "long_article"}})

    heads = re.findall(r"(?m)^## (.)、", fitted)
    assert "第2部分" not in fitted and heads == list(cn[:len(heads)]) and len(heads) == 4


def test_fit_article_length_strips_image_placement_notes():
    from content_platform.generator import DraftGenerator

    body = "## 背景\n\n正文一。\n\n配图位置：此处放架构图\n\n（插图位置：流程截图）\n\n正文二。"

    fitted = DraftGenerator._fit_article_length(body, {"strategy": {"content_form": "technical_article"}})

    assert "配图位置" not in fitted and "插图位置" not in fitted
    assert "正文一。" in fitted and "正文二。" in fitted


def test_deferred_tool_needs_a_named_step_under_required_execution():
    from content_platform.content_recipe import build_tool_invocation_manifest, validate_tool_invocation_manifest

    planned = {"a": "x", "b": "x", "c": "x"}
    ok = {"a": {"status": "ok"}, "b": {"status": "ok"}}
    named = build_tool_invocation_manifest(planned_tools=planned, invocations=dict(ok, c={"status": "deferred", "step": "render"}))
    unnamed = build_tool_invocation_manifest(planned_tools=planned, invocations=dict(ok, c={"status": "deferred"}))

    assert validate_tool_invocation_manifest(named, require_execution=True)["passed"]
    assert not validate_tool_invocation_manifest(unnamed, require_execution=True)["passed"]


def test_humanizer_output_is_refit_to_article_length(monkeypatch):
    long_body = ("这是一段较长的中文说明，用于测试润色后的长度。" * 30 + "\n\n") * 8
    monkeypatch.setattr("content_platform.humanizer._hermes_llm_call",
                        lambda prompt, system="", timeout=60: __import__("json").dumps(
                            {"title": "工作流拆解", "body": long_body, "changes": [], "score": 40}, ensure_ascii=False))
    events = []
    pipeline = SimpleNamespace(config={"generator": {"timeout": 600}},
                               store=SimpleNamespace(record_event=lambda *a: events.append(a)),
                               _validate_draft_structure=lambda item: None)
    draft = {"title": "工作流拆解", "body": BODY, "draft_meta": {"strategy": {"content_form": "technical_article"}}}

    Pipeline._humanize_draft(pipeline, "job", draft)

    assert len("".join(draft["body"].split())) <= 3000


def test_humanizer_rewrite_that_drops_most_of_an_article_is_rejected(monkeypatch):
    article = ("值得注意的是，这一节说明分层记忆如何赋能写入、检索和过期，总而言之给出复核清单与具体步骤。" * 12 + "\n\n") * 6
    monkeypatch.setattr("content_platform.humanizer._hermes_llm_call",
                        lambda prompt, system="", timeout=60: __import__("json").dumps(
                            {"title": "改写标题", "body": "只剩一小段概括。" * 20, "changes": [], "score": 40}, ensure_ascii=False))
    events = []
    pipeline = SimpleNamespace(config={"generator": {"timeout": 600}},
                               store=SimpleNamespace(record_event=lambda *a: events.append(a)),
                               _validate_draft_structure=lambda item: None)
    draft = {"title": "原标题", "body": article, "draft_meta": {"strategy": {"content_form": "technical_article"}}}

    Pipeline._humanize_draft(pipeline, "job", draft)

    assert draft["body"] == article and draft["title"] == "原标题"
    assert [e[1] for e in events] == ["humanize_rejected_short"]


def test_failed_humanizer_call_keeps_the_original_draft(monkeypatch):
    monkeypatch.setattr("content_platform.humanizer._hermes_llm_call", lambda prompt, system="", timeout=60: "not json")
    events = []
    pipeline = SimpleNamespace(config={"generator": {"timeout": 600}},
                               store=SimpleNamespace(record_event=lambda *a: events.append(a)),
                               _validate_draft_structure=lambda item: None)
    draft = {"title": "原标题", "body": BODY, "draft_meta": {"strategy": {"content_form": "technical_article"}}}

    Pipeline._humanize_draft(pipeline, "job", draft)

    assert draft["body"] == BODY and draft["title"] == "原标题"
    assert events[0][1] == "humanize_failed" and events[0][2]["kept_original"] is True


def test_same_lane_analysis_uses_collected_samples_not_placeholders():
    from content_platform.generator import DraftGenerator

    brief = {"viral_collection": {"tool": "native.platform_hot_adapters"},
             "viral_breakdown": {"samples": [{"title": "样本", "canonical_url": "https://example.com/a", "metrics": {"like": 3},
                                              "body": "开头一句。后文。\n## 第一节\n正文"}]}}

    observed = DraftGenerator._observed_same_lane(brief)
    empty = DraftGenerator._observed_same_lane({})

    assert observed["source"] == "native.platform_hot_adapters" and observed["samples"][0]["canonical_url"] == "https://example.com/a"
    assert observed["borrowable_patterns"][0] == {"sample": "https://example.com/a", "observed_opening": "开头一句。", "observed_headings": ["第一节"]}
    assert empty["source"] == "" and empty["samples"] == []


def test_rendered_asset_mix_declares_the_actual_provenance():
    from content_platform.pipeline import Pipeline

    assets = [{"scene_id": "cover", "origin": "real_photo", "source_url": "https://www.pexels.com/photo/1/", "cover_render_evidence": {"v": 1}},
              {"scene_id": "s1", "origin": "ai_generated", "source_url": "generated:go_gemini"}]

    mix = Pipeline._rendered_asset_mix(assets, {"draft_meta": {}})
    original = Pipeline._rendered_asset_mix(assets, {"draft_meta": {"brief": {"content_mode": "original_knowledge"}}})

    assert mix["ai_generated"] == "s1: generated:go_gemini"
    assert "cover: https://www.pexels.com/photo/1/" in mix["real_material_retrieval"]
    assert mix["ai_edit_real_material"] == "cover title rendered over the real_photo background"
    assert original["real_material_retrieval"] == ""


def test_rendered_background_is_real_only_for_a_licensed_stock_photo():
    from content_platform.media_quality import _valid_real_scene_background
    from content_platform.pipeline import Pipeline

    photo = Pipeline._rendered_background({"path": "/a/cover.png", "scene_id": "cover", "origin": "real_photo", "license": "Pexels",
                                           "source_url": "https://www.pexels.com/photo/1/", "match_reason": "topic"})
    generated = Pipeline._rendered_background({"path": "/a/s1.png", "scene_id": "s1", "origin": "ai_generated",
                                               "license": "provider_terms_recorded", "source_url": "generated:go_gemini", "match_reason": "topic"})

    assert _valid_real_scene_background(photo) is True
    assert _valid_real_scene_background(generated) is False


def test_slot_quantity_states_the_channel_daily_target():
    from content_platform.generator import DraftGenerator

    plan = DraftGenerator._slot_quantity({"run_contract": {"channel_rules": {"daily_target": "1篇文章 + 2个回答"}}}, "evidence_answer")

    assert plan["final_count"] == 1 and plan["channel_daily_target"] == "1篇文章 + 2个回答"
    assert "one evidence_answer per scheduled overnight slot" in plan["decision_reason"]
