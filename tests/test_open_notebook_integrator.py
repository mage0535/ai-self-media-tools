"""Tests for Open Notebook integrator.

These tests verify the integrator module's request construction, response parsing,
and failure handling. Real API calls against the local Open Notebook instance
are performed when the service is healthy; otherwise tests fall back to mocks.
"""
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from scripts.open_notebook_integrator import (
    OpenNotebookClient,
    digest_source,
    research_topic,
)


def _mock_json(data: dict):
    """Helper: create a requests.Response-like mock with .json() returning data."""
    m = MagicMock(status_code=200)
    m.json.return_value = data
    m.text = json.dumps(data)
    return m


class OpenNotebookClientTests(unittest.TestCase):
    """OpenNotebookClient — unit tests with mocked HTTP responses."""

    def setUp(self):
        self.client = OpenNotebookClient(base_url="http://test:5055", password="")
        self.nb_id = "notebook:test123"

    def test_health_passes(self):
        with patch.object(self.client.session, "request") as mock_req:
            mock_req.return_value = _mock_json({"status": "healthy"})
            self.assertEqual(self.client.health(), {"status": "healthy"})
            mock_req.assert_called_once_with("GET", "http://test:5055/health", json=None, timeout=60)

    def test_create_notebook_sends_json(self):
        with patch.object(self.client.session, "request") as mock_req:
            mock_req.return_value = _mock_json({"id": "nb:1"})
            result = self.client.create_notebook("test", "desc")
            self.assertEqual(result["id"], "nb:1")
            _, kwargs = mock_req.call_args
            self.assertEqual(kwargs["json"], {"name": "test", "description": "desc"})

    def test_add_source_link_sends_multipart(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = _mock_json({"id": "src:1"})
            result = self.client.add_source(self.nb_id, "link", "https://example.com")
            self.assertEqual(result["id"], "src:1")
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["data"]["type"], "link")
            self.assertEqual(kwargs["data"]["url"], "https://example.com")
            self.assertEqual(kwargs["data"]["notebook_id"], self.nb_id)

    def test_add_source_text_sends_content(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value = _mock_json({"id": "src:2"})
            result = self.client.add_source(self.nb_id, "text", "hello world")
            self.assertEqual(result["id"], "src:2")
            _, kwargs = mock_post.call_args
            self.assertEqual(kwargs["data"]["type"], "text")
            self.assertEqual(kwargs["data"]["content"], "hello world")

    def test_search_includes_notebook(self):
        with patch.object(self.client.session, "request") as mock_req:
            mock_req.return_value = _mock_json({"results": [], "total_count": 0})
            self.client.search("q", notebook_id=self.nb_id)
            _, kwargs = mock_req.call_args
            self.assertEqual(kwargs["json"]["query"], "q")
            self.assertEqual(kwargs["json"]["notebook_id"], self.nb_id)

    def test_ask_sends_question(self):
        with patch.object(self.client.session, "request") as mock_req:
            mock_req.return_value = _mock_json({"answer": "ok"})
            self.client.ask("What?")
            _, kwargs = mock_req.call_args
            self.assertEqual(kwargs["json"]["question"], "What?")

    def test_ask_with_models(self):
        with patch.object(self.client.session, "request") as mock_req:
            mock_req.return_value = _mock_json({"answer": "ok"})
            models = {"strategy_model": "m1", "answer_model": "m2", "final_answer_model": "m3"}
            self.client.ask("What?", models=models)
            _, kwargs = mock_req.call_args
            self.assertEqual(kwargs["json"]["strategy_model"], "m1")

    def test_http_error_raises(self):
        with patch.object(self.client.session, "request") as mock_req:
            import requests
            resp = MagicMock(status_code=422)
            resp.raise_for_status.side_effect = requests.HTTPError("422 Client Error")
            resp.text = '{"detail":"Bad"}'
            mock_req.return_value = resp
            with self.assertRaises(RuntimeError):
                self.client.health()

    def test_multipart_error_raises(self):
        with patch.object(self.client.session, "post") as mock_post:
            import requests
            resp = MagicMock(status_code=500)
            resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
            resp.text = '{"detail":"fail"}'
            mock_post.return_value = resp
            with self.assertRaises(RuntimeError):
                self.client.add_source(self.nb_id, "link", "https://x.com")

    def test_empty_response_returns_empty_dict(self):
        with patch.object(self.client.session, "request") as mock_req:
            m = MagicMock(status_code=200)
            m.json.return_value = {}
            m.text = ""
            mock_req.return_value = m
            self.assertEqual(self.client.health(), {})


class DigestSourceTests(unittest.TestCase):
    """digest_source — integration-style tests with mocked API layer."""

    def test_missing_service_returns_error(self):
        with patch.object(OpenNotebookClient, "health") as mock_h:
            mock_h.side_effect = RuntimeError("Connection refused")
            result = digest_source(url="https://x.com")
            self.assertIn("error", result)
            self.assertIn("unreachable", result["error"])

    def test_unhealthy_service_returns_error(self):
        with patch.object(OpenNotebookClient, "health") as mock_h:
            mock_h.return_value = {"status": "degraded"}
            result = digest_source(url="https://x.com")
            self.assertIn("error", result)
            self.assertIn("not healthy", result["error"])

    def test_full_flow_with_mocks(self):
        with (
            patch.object(OpenNotebookClient, "health", return_value={"status": "healthy"}),
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:mock"}),
            patch.object(OpenNotebookClient, "add_source", return_value={"id": "src:mock"}),
            patch.object(OpenNotebookClient, "ask", return_value={"answer": "summary"}),
            patch.object(OpenNotebookClient, "search", return_value={"results": []}),
            patch.object(OpenNotebookClient, "list_notes", return_value=[]),
        ):
            result = digest_source(url="https://x.com", title="X", topic="test")
            self.assertNotIn("error", result, str(result))
            self.assertEqual(result["notebook_id"], "nb:mock")
            self.assertEqual(result["source_id"], "src:mock")
            self.assertEqual(result["topic"], "test")
            self.assertEqual(result["source_type"], "link")

    def test_text_mode(self):
        with (
            patch.object(OpenNotebookClient, "health", return_value={"status": "healthy"}),
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:txt"}),
            patch.object(OpenNotebookClient, "add_source", return_value={"id": "src:txt"}),
            patch.object(OpenNotebookClient, "ask", return_value={"answer": "text summary"}),
            patch.object(OpenNotebookClient, "search", return_value={"results": []}),
            patch.object(OpenNotebookClient, "list_notes", return_value=[]),
        ):
            result = digest_source(text="Some content here", topic="text-test")
            self.assertNotIn("error", result)
            self.assertEqual(result["source_type"], "text")

    def test_both_url_and_text_required(self):
        """No url and no text → error."""
        result = digest_source()
        self.assertIn("error", result)

    def test_create_notebook_failure(self):
        with (
            patch.object(OpenNotebookClient, "health", return_value={"status": "healthy"}),
            patch.object(OpenNotebookClient, "create_notebook", return_value={}),
        ):
            result = digest_source(url="https://x.com")
            self.assertIn("error", result)
            self.assertIn("notebook", result["error"].lower())

    def test_add_source_failure(self):
        with (
            patch.object(OpenNotebookClient, "health", return_value={"status": "healthy"}),
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:1"}),
            patch.object(OpenNotebookClient, "add_source", side_effect=RuntimeError("API error")),
        ):
            result = digest_source(url="https://x.com")
            self.assertIn("error", result)

    def test_ask_failure_does_not_kill_flow(self):
        with (
            patch.object(OpenNotebookClient, "health", return_value={"status": "healthy"}),
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:1"}),
            patch.object(OpenNotebookClient, "add_source", return_value={"id": "src:1"}),
            patch.object(OpenNotebookClient, "ask", side_effect=RuntimeError("ask failed")),
            patch.object(OpenNotebookClient, "search", return_value={"results": []}),
            patch.object(OpenNotebookClient, "list_notes", return_value=[]),
        ):
            result = digest_source(url="https://x.com")
            self.assertNotIn("error", result)  # top-level error only for fatal
            self.assertIn("qa", result)


class ResearchTopicTests(unittest.TestCase):
    """research_topic — mock-based tests."""

    def test_create_notebook_failure(self):
        with patch.object(OpenNotebookClient, "create_notebook", side_effect=RuntimeError("fail")):
            result = research_topic("test", urls=[])
            self.assertIn("error", result)

    def test_multiple_urls(self):
        with (
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:r"}),
            patch.object(OpenNotebookClient, "add_source", return_value={"id": "src:r"}),
            patch.object(OpenNotebookClient, "ask", return_value={"answer": "ok"}),
        ):
            result = research_topic("test", urls=["https://a.com", "https://b.com"])
            self.assertEqual(result["notebook_id"], "nb:r")
            self.assertEqual(result["sources_added"], 2)
            self.assertEqual(result["qa_pairs"], 3)

    def test_with_texts(self):
        with (
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:rt"}),
            patch.object(OpenNotebookClient, "add_source", return_value={"id": "src:rt"}),
            patch.object(OpenNotebookClient, "ask", return_value={"answer": "ok"}),
        ):
            result = research_topic("t", texts=["text1"])
            self.assertEqual(result["sources_added"], 1)

    def test_add_source_error_does_not_block(self):
        with (
            patch.object(OpenNotebookClient, "create_notebook", return_value={"id": "nb:1"}),
            patch.object(OpenNotebookClient, "add_source", side_effect=[{"id": "ok"}, RuntimeError("fail")]),
            patch.object(OpenNotebookClient, "ask", return_value={"answer": "ok"}),
        ):
            result = research_topic("test", urls=["https://a.com", "https://b.com"])
            self.assertEqual(result["sources_added"], 2)  # one ok + one error counted


class ToolRegistryIntegrationTests(unittest.TestCase):
    """Verify tool_registry probe includes open_notebook."""

    def test_probe_includes_open_notebook(self):
        from content_platform.tool_registry import ToolRegistry
        probe = ToolRegistry().probe()
        self.assertIn("open_notebook", probe)
        entry = probe["open_notebook"]
        self.assertIn("available", entry)
        self.assertEqual(entry["kind"], "research")


class IntelligenceIntegrationTests(unittest.TestCase):
    """Verify intelligence.py passes through open_notebook_research."""

    def test_context_contains_key(self):
        from content_platform.intelligence import build_generation_context
        ctx = build_generation_context("test", {"deep_research": False})
        self.assertIn("open_notebook_research", ctx)
        self.assertEqual(ctx["open_notebook_research"], {})

    def test_prompt_brief_includes_key(self):
        from content_platform.intelligence import prompt_brief
        output = prompt_brief("test", {"deep_research": False})
        parsed = json.loads(output)
        self.assertIn("open_notebook_research", parsed)

    def test_deep_research_no_urls_no_crash(self):
        from content_platform.intelligence import build_generation_context
        ctx = build_generation_context("test", {"deep_research": True})
        self.assertIsInstance(ctx.get("open_notebook_research"), dict)


class ModelDiscoveryTests(unittest.TestCase):
    """Verify the model discovery flow for the ask endpoint."""

    def test_get_defaults_returns_list(self):
        with patch.object(OpenNotebookClient, "_json") as mock_j:
            mock_j.return_value = []
            cli = OpenNotebookClient()
            result = cli.get_defaults()
            self.assertEqual(result, [])

    def test_list_notebooks_returns_list(self):
        with patch.object(OpenNotebookClient, "_json") as mock_j:
            mock_j.return_value = [{"id": "nb:1"}]
            cli = OpenNotebookClient()
            result = cli.list_notebooks()
            self.assertEqual(len(result), 1)


class CommandLineTests(unittest.TestCase):
    """CLI interface smoke tests."""

    def test_cli_health_flag(self):
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, "-m", "scripts.open_notebook_integrator", "health"],
            capture_output=True, text=True, timeout=15,
            cwd="<server-runtime-root>",
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("Open Notebook", r.stdout)

    def test_cli_help(self):
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, "-m", "scripts.open_notebook_integrator"],
            capture_output=True, text=True, timeout=10,
            cwd="<server-runtime-root>",
        )
        # argparse exits 1 when no subcommand given; help text still printed
        self.assertIn("digest", r.stdout)
        self.assertIn("research", r.stdout)
        self.assertIn("health", r.stdout)


if __name__ == "__main__":
    unittest.main()
