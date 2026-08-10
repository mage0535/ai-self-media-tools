import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from content_platform.skills_adapter import get_status
from content_platform.tool_adapters import ScriptAnalyzerProvider, ScriptOCRProvider, ScriptTranscriberProvider, ScriptImageProvider
from content_platform.tool_registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_registry_reports_extended_content_tools(self):
        registry = ToolRegistry({"media": {}, "analysis": {}, "ocr": {}, "transcription": {}})
        with patch("content_platform.tool_registry.shutil.which", side_effect=lambda name: "C:/bin/tool" if name in {"python", "ffmpeg"} else ""):
            result = registry.probe()
        self.assertTrue(result["ffmpeg"]["available"])
        self.assertIn("ocr_script", result)
        self.assertIn("transcription_script", result)
        self.assertIn("analysis_script", result)

    def test_script_providers_return_structured_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root / "sample.png"
            sample.write_bytes(b"fake")
            script = root / "provider.py"
            script.write_text("# fixture", encoding="utf-8")
            payload = '{"summary":"ok","labels":["automation"]}'
            completed = type("Result", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
            with patch("content_platform.tool_adapters.subprocess.run", return_value=completed):
                analyzer = ScriptAnalyzerProvider(str(script))
                ocr = ScriptOCRProvider(str(script))
                transcriber = ScriptTranscriberProvider(str(script))
                self.assertEqual(analyzer.run(str(sample))["summary"], "ok")
                self.assertEqual(ocr.run(str(sample))["labels"][0], "automation")
                self.assertEqual(transcriber.run(str(sample))["summary"], "ok")

    def test_registry_can_build_provider_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "provider.py"
            script.write_text("# fixture", encoding="utf-8")
            registry = ToolRegistry({"media": {"image": {"script": str(script)}}})
            provider = registry.choose_provider("image")
            self.assertIsInstance(provider, ScriptImageProvider)

    def test_registry_reports_repo_relative_script_paths(self):
        registry = ToolRegistry({"media": {"image": {"script": "scripts/voice_engine.py"}}})
        result = registry.probe()
        self.assertTrue(result["image_script"]["available"])

    def test_skills_adapter_status_handles_missing_autocli_without_crashing(self):
        with patch("content_platform.skills_adapter.shutil.which", return_value=""):
            status = get_status()
        self.assertIn("autocli", status)
        self.assertFalse(status["autocli"]["available"])

    def test_registry_reports_zhihu_open_platform_skill_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            skill = home / ".hermes" / "skills" / "content" / "zhihu-open-platform"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# fixture", encoding="utf-8")

            with patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                with patch("content_platform.tool_registry.shutil.which", side_effect=lambda name: "/bin/zhihu-search" if name == "zhihu-search" else ""):
                    result = ToolRegistry().probe()

        self.assertTrue(result["zhihu_open_platform"]["available"])
        self.assertTrue(result["zhihu_open_cli"]["available"])

    def test_registry_reports_default_user_zhihu_search_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            binary = home / ".local" / "bin" / "zhihu-search"
            binary.parent.mkdir(parents=True)
            binary.write_text("# fixture", encoding="utf-8")

            with patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}, clear=True):
                with patch("content_platform.tool_registry.shutil.which", return_value=""):
                    result = ToolRegistry().probe()

        self.assertTrue(result["zhihu_open_cli"]["available"])


if __name__ == "__main__":
    unittest.main()
