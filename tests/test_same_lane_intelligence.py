import io
import json
from contextlib import redirect_stdout

from content_platform.cli import main
from content_platform.store import Store


def test_filter_samples_rejects_non_native_or_generic_homepage_for_platform():
    from content_platform.same_lane_intelligence import filter_rankable_samples

    accepted, rejected = filter_rankable_samples(
        "wechat",
        [
            {"title": "OpenAI 发布新模型", "url": "https://openai.com/index/gpt", "source": "searxng"},
            {"title": "AI 工作流提效教程：三步做会议纪要", "url": "https://mp.weixin.qq.com/s/abc", "source": "wechat_search"},
        ],
    )

    assert [row["title"] for row in accepted] == ["AI 工作流提效教程：三步做会议纪要"]
    assert rejected[0]["reject_reason"] == "non_native_domain"


def test_distill_youtube_samples_extracts_tool_workflow_patterns():
    from content_platform.same_lane_intelligence import distill_same_lane_samples

    report = distill_same_lane_samples(
        "youtube",
        [
            {
                "title": "Build a Website Chatbot with n8n, Postgres & Groq - No Code AI",
                "url": "https://www.youtube.com/watch?v=abc",
                "account": "The AI Workflow",
                "views": 640,
                "duration": "17:30",
            },
            {
                "title": "How to Automate Your Entire Social Media With One AI Agent",
                "url": "https://www.youtube.com/watch?v=def",
                "account": "Automate with Marc",
                "views": 1900,
                "duration": "14:17",
            },
        ],
        own_metrics_readiness={"strategy_eligible_count": 0},
    )

    assert report["platform"] == "youtube"
    assert report["own_data_status"] == "insufficient"
    assert "tool_workflow_tutorial" in report["topic_patterns"]
    assert "screen_or_tool_stack_demo" in report["proof_requirements"]
    assert report["top_accounts"][0]["account"] == "Automate with Marc"
    assert any("concrete tool stack" in move for move in report["recommended_content_moves"])


def test_distill_rejects_bad_sources_and_keeps_bilibili_native_samples():
    from content_platform.same_lane_intelligence import distill_same_lane_samples

    report = distill_same_lane_samples(
        "bilibili",
        [
            {"title": "AI 工具效率教程：自动做周报", "url": "https://www.bilibili.com/video/BV1xx", "account": "LeaderAI", "views": 22000},
            {"title": "ChatGPT 官网", "url": "https://openai.com/chatgpt", "account": "OpenAI", "views": 999999},
        ],
    )

    assert report["accepted_sample_count"] == 1
    assert report["rejected_sample_count"] == 1
    assert report["top_works"][0]["account"] == "LeaderAI"
    assert "platform_native_work" in report["evidence_quality"]


def test_cli_same_lane_intel_reads_sample_file_writes_report_and_snapshot(tmp_path):
    sample_file = tmp_path / "samples.json"
    sample_file.write_text(
        json.dumps(
            {
                "youtube": [
                    {
                        "title": "How to Use Claude Code With Kimi K3 and Ollama",
                        "url": "https://www.youtube.com/watch?v=yt1",
                        "account": "Automate with Marc",
                        "views": 1500,
                    }
                ],
                "bilibili": [
                    {
                        "title": "AI 工作流自动化教程",
                        "url": "https://www.bilibili.com/video/BV123",
                        "account": "AISolo大西瓜",
                        "views": 8888,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "same-lane-report.json"

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(
            [
                "--db",
                str(tmp_path / "state.db"),
                "--config",
                "",
                "same-lane-intel",
                "--sample-file",
                str(sample_file),
                "--platform",
                "youtube",
                "--platform",
                "bilibili",
                "--output",
                str(output_path),
            ]
        )

    assert code == 0
    result = json.loads(stdout.getvalue())
    assert result["ok"] is True
    assert output_path.is_file()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert sorted(report["platforms"]) == ["bilibili", "youtube"]
    latest = Store(tmp_path / "state.db").latest_tool_inventory("same_lane_intelligence:latest")
    assert latest["payload"]["report_path"] == str(output_path)
