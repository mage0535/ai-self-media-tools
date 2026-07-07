import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
