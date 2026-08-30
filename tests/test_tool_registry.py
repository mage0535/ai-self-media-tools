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

    def test_image_script_provider_preserves_source_and_license_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "provider.py"
            script.write_text("# fixture", encoding="utf-8")
            completed = type("Result", (), {
                "returncode": 0,
                "stdout": '{"provider":"pexels","source_url":"https://pexels.test/photo","license":"Pexels"}',
                "stderr": "",
            })()
            with patch("content_platform.tool_adapters.subprocess.run", return_value=completed):
                result = ScriptImageProvider(str(script)).run("AI workflow", Path(tmp) / "image.png")

        self.assertEqual(result["provider"], "pexels")
        self.assertEqual(result["source_url"], "https://pexels.test/photo")
        self.assertEqual(result["license"], "Pexels")

    def test_registry_reports_repo_relative_script_paths(self):
        registry = ToolRegistry({"media": {"image": {"script": "scripts/voice_engine.py"}}})
        result = registry.probe()
        self.assertTrue(result["image_script"]["available"])

    def test_relative_provider_paths_resolve_from_project_root_not_cwd(self):
        with tempfile.TemporaryDirectory() as project_tmp, tempfile.TemporaryDirectory() as cwd_tmp:
            project = Path(project_tmp)
            script = project / "scripts" / "analyze.py"
            script.parent.mkdir()
            script.write_text("print('{}')\n", encoding="utf-8")
            previous = __import__("os").getcwd()
            try:
                __import__("os").chdir(cwd_tmp)
                with patch.dict("os.environ", {"CONTENT_PLATFORM_CODE_ROOT": str(project)}):
                    registry = ToolRegistry({"analysis": {"script": "scripts/analyze.py"}})
                    provider = registry.choose_provider("analysis")
                    probe = registry.probe()
            finally:
                __import__("os").chdir(previous)

        self.assertTrue(probe["analysis_script"]["available"])
        self.assertEqual(provider.script, str(script))

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

    def test_registry_reports_qwen_tts_only_when_api_key_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"HOME": tmp, "USERPROFILE": tmp}, clear=True):
                result = ToolRegistry().probe()
            self.assertFalse(result["tts_engines"]["qwen3-tts"]["available"])

            with patch.dict("os.environ", {"HOME": tmp, "USERPROFILE": tmp, "DASHSCOPE_API_KEY": "test-key"}, clear=True):
                result = ToolRegistry().probe()
        self.assertTrue(result["tts_engines"]["qwen3-tts"]["available"])
        self.assertEqual(result["tts_engines"]["qwen3-tts"]["model"], "qwen3-tts-flash")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                "os.environ",
                {
                    "HOME": tmp,
                    "USERPROFILE": tmp,
                    "DASHSCOPE_API_KEY": "test-key",
                    "QWEN_TTS_MODEL": "qwen-audio-3.0-tts-flash",
                },
                clear=True,
            ):
                result = ToolRegistry().probe()
        self.assertEqual(result["tts_engines"]["qwen3-tts"]["model"], "qwen-audio-3.0-tts-flash")

    def test_registry_reports_image_provider_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOME": tmp,
                "USERPROFILE": tmp,
                "SN_API_KEY": "sense-key",
                "PIXAZO_API_KEY": "pixazo-key",
                "PEXELS_API_KEY": "pexels-key",
            }
            with patch.dict("os.environ", env, clear=True):
                result = ToolRegistry({"fast_probe": True}).probe()

        registry = result["image_providers"]
        self.assertTrue(registry["available"])
        self.assertEqual(registry["kind"], "image_provider_registry")
        self.assertTrue(registry["providers"]["sense_nova"]["supports_edit"])
        self.assertTrue(registry["providers"]["pixazo"]["supports_generate"])
        self.assertTrue(registry["providers"]["stock"]["available"])

    def test_registry_reports_agnes_image_and_video_capabilities(self):
        with patch.dict("os.environ", {"AGNES_API_KEY": "test-key"}, clear=False):
            result = ToolRegistry({"fast_probe": True}).probe()

        assert result["image_providers"]["providers"]["agnes"]["supports_edit"] is True
        assert result["agnes_multimodal"]["supports_text_to_video"] is True
        assert result["agnes_multimodal"]["video_model"] == "agnes-video-2.5-flash"
        assert result["agnes_multimodal"]["video_auto_enabled"] is False


if __name__ == "__main__":
    unittest.main()
