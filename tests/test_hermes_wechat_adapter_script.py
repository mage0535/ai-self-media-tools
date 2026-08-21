import sys
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import json

from scripts import hermes_wechat_adapter
from scripts import gzh_publish_license


def _today_run_date() -> str:
    return datetime.now().strftime("%Y%m%d")


def test_generated_image_helpers_accept_image_gen_engine_output_key(tmp_path, monkeypatch):
    class FakeImageGen:
        @staticmethod
        def generate(prompt, platform=None, output_path=""):
            Path(output_path).write_bytes(b"image")
            return {"status": "ok", "output": output_path, "provider": "fake"}

    monkeypatch.setitem(sys.modules, "image_gen_engine", FakeImageGen)
    packet = {
        "title": "Adapter image generation",
        "cover_design": {"visual_subject": "workflow checklist"},
        "section_image_map": [{"section": "case", "purpose": "show the case"}],
    }

    cover = hermes_wechat_adapter._generate_image(packet, tmp_path, "cover")
    inline = hermes_wechat_adapter._generate_section_image(packet, tmp_path, packet["section_image_map"][0], 1)

    assert cover == tmp_path / "cover.jpg"
    assert inline == tmp_path / "inline_1.jpg"
    assert cover.is_file()
    assert inline.is_file()


def test_generated_image_path_keeps_legacy_path_key(tmp_path):
    image = tmp_path / "legacy.jpg"
    image.write_bytes(b"image")

    assert hermes_wechat_adapter._generated_image_path({"path": str(image)}, tmp_path / "fallback.jpg") == image


def test_markdown_replaces_section_placeholders_without_empty_image_links():
    packet = {
        "title": "Working title",
        "body": "Intro\n\n## One\n\n![weekly]()\n\n## Two\n\n![meeting]()\n\n## Three\n\n![email]()",
    }

    markdown = hermes_wechat_adapter._markdown_with_inline_images(
        packet,
        "https://cdn.example/cover.jpg",
        [
            "https://cdn.example/weekly.jpg",
            "https://cdn.example/meeting.jpg",
            "https://cdn.example/email.jpg",
        ],
    )

    assert "![](https://cdn.example/cover.jpg)" in markdown
    assert "![weekly](https://cdn.example/weekly.jpg)" in markdown
    assert "![meeting](https://cdn.example/meeting.jpg)" in markdown
    assert "![email](https://cdn.example/email.jpg)" in markdown
    assert "![]()" not in markdown


def test_markdown_rejects_unresolved_section_placeholders():
    packet = {"body": "## One\n\n![weekly]()\n\n## Two\n\n![meeting]()"}

    try:
        hermes_wechat_adapter._markdown_with_inline_images(packet, "", ["https://cdn.example/one.jpg"])
    except ValueError as exc:
        assert "unresolved inline image" in str(exc)
    else:
        raise AssertionError("unresolved placeholders must block the draft")


def test_draft_postcheck_rejects_missing_inline_images(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                "item": [{
                    "media_id": "draft-1",
                    "content": {"news_item": [{"title": "Working title", "content": "<p>text only</p>"}]},
                }],
            }).encode("utf-8")

    monkeypatch.setattr(hermes_wechat_adapter.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = hermes_wechat_adapter._batchget_confirm("token", "draft-1", "Working title", expected_inline_images=3)

    assert result["passed"] is False
    assert result["inline_image_count"] == 0


def test_draft_postcheck_counts_wechat_data_src_images(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = "".join(f'<img data-src="https://cdn.example/{index}.jpg">' for index in range(4))
            return json.dumps({
                "item": [{
                    "media_id": "draft-1",
                    "content": {"news_item": [{"title": "Working title", "content": content}]},
                }],
            }).encode("utf-8")

    monkeypatch.setattr(hermes_wechat_adapter.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = hermes_wechat_adapter._batchget_confirm("token", "draft-1", "Working title", expected_inline_images=3)

    assert result["passed"] is True
    assert result["inline_image_count"] == 4


def test_publish_license_gate_blocks_missing_title(tmp_path):
    result = hermes_wechat_adapter._run_publish_license_gate({}, tmp_path / "missing.py")

    assert result["passed"] is False
    assert "title_missing" in result["failures"]


def test_publish_license_gate_fails_closed_on_invalid_json(tmp_path):
    gate = tmp_path / "license.py"
    gate.write_text("print('not-json')\n", encoding="utf-8")

    result = hermes_wechat_adapter._run_publish_license_gate({"title": "Valid title"}, gate)

    assert result["passed"] is False
    assert "license_output_invalid" in result["failures"][0]


def test_publish_license_gate_fails_closed_when_script_missing(tmp_path):
    result = hermes_wechat_adapter._run_publish_license_gate({"title": "Valid title"}, tmp_path / "missing.py")

    assert result["passed"] is False
    assert "license_script_missing" in result["failures"]


def test_publish_packet_blocks_before_wechat_when_license_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("CN_PROXY", "socks5://127.0.0.1:1080")
    calls = [
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=1, stdout='{"passed": false, "failures": ["test_failure"]}', stderr=""),
    ]
    monkeypatch.setattr(hermes_wechat_adapter.subprocess, "run", lambda *args, **kwargs: calls.pop(0))
    packet = {"title": "AI自动化实测：10个平台工具测评"}

    result = hermes_wechat_adapter.publish_packet(packet, tmp_path)

    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert "WeChat publish license blocked" in result["error"]


def test_publish_license_does_not_count_bare_wechat_jobs_as_delivered(tmp_path):
    from content_platform.store import Store

    store = Store(tmp_path / "data" / "state.db")
    job = store.create_job("Generated but not delivered", ["wechat"], {})
    with store.connect() as conn:
        conn.execute("UPDATE jobs SET title=? WHERE id=?", ("Generated but not delivered", job["id"]))

    recent = gzh_publish_license.recent_wechat_titles(tmp_path)

    assert recent == []


def test_publish_license_counts_successful_wechat_receipts(tmp_path):
    from content_platform.store import Store

    store = Store(tmp_path / "data" / "state.db")
    job = store.create_job("Delivered article", ["wechat"], {})
    store.save_publish_receipt("cp1", "wechat", {"status": "created", "platform_content_id": "draft-1"}, job_id=job["id"])

    recent = gzh_publish_license.recent_wechat_titles(tmp_path)

    assert recent == [("Delivered article", recent[0][1])]


def test_publish_license_ignores_unstructured_markdown_recaps(tmp_path):
    recap_dir = tmp_path / "data" / "local_ops_gzh"
    recap_dir.mkdir(parents=True)
    (recap_dir / "recap_20260807.md").write_text(
        "# 公众号平台运营复盘 2026-08-07\n\n"
        "1. 每天重复4小时的工作，我用AI自动化后剩下了什么 → 草稿箱 ✅\n"
        "media_id=draft-1\n",
        encoding="utf-8",
    )

    recent = gzh_publish_license.recent_wechat_titles(tmp_path)

    assert recent == []


def test_publish_license_blocks_reused_direction_from_run_manifest(tmp_path):
    from content_platform.ops_run import create_run, record_topic

    run_date = _today_run_date()
    create_run(tmp_path, run_date, lookback_days=7)
    record_topic(
        tmp_path,
        run_date,
        "wechat",
        "How an AI agent runs eleven channels",
        direction="agent_workflow",
    )

    result = gzh_publish_license.check_license(
        "A different title about AI agent operations",
        root=tmp_path,
        skip_time=True,
        direction="agent_workflow",
    )

    assert result["passed"] is False
    assert any(item.startswith("duplicate_direction:") for item in result["failures"])


def test_adapter_passes_direction_to_publish_license_gate(tmp_path, monkeypatch):
    observed = {}

    def fake_run(args, **kwargs):
        observed["args"] = list(args)
        return SimpleNamespace(returncode=0, stdout='{"passed": true, "failures": []}', stderr="")

    monkeypatch.setattr(hermes_wechat_adapter.subprocess, "run", fake_run)

    result = hermes_wechat_adapter._run_publish_license_gate(
        {"title": "Distinct title", "strategy_brief": {"content_direction": "agent_workflow"}},
        tmp_path / "license.py",
    )

    assert result["passed"] is False
    assert "license_script_missing" in result["failures"]

    gate = tmp_path / "license.py"
    gate.write_text("placeholder", encoding="utf-8")
    result = hermes_wechat_adapter._run_publish_license_gate(
        {"title": "Distinct title", "strategy_brief": {"content_direction": "agent_workflow"}},
        gate,
    )

    assert result["passed"] is True
    assert "--direction" in observed["args"]
    assert observed["args"][observed["args"].index("--direction") + 1] == "agent_workflow"


def test_publish_license_direction_gate_works_from_arbitrary_cwd(tmp_path):
    from content_platform.ops_run import create_run, record_topic

    run_date = _today_run_date()
    create_run(tmp_path, run_date, lookback_days=7)
    record_topic(tmp_path, run_date, "wechat", "AI agent operations", direction="agent_workflow")
    script = Path(__file__).resolve().parents[1] / "scripts" / "gzh_publish_license.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--title",
            "Different title",
            "--direction",
            "agent_workflow",
            "--root",
            str(tmp_path),
            "--skip-time",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "duplicate_direction:agent_workflow" in result.stdout
