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
