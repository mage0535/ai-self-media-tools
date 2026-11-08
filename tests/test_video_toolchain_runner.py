import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch


class VideoToolchainRunnerTests(unittest.TestCase):
    def test_rendered_html_gate_is_fail_closed_when_renderer_did_not_emit_html(self):
        from scripts.video_toolchain_runner import _run_rendered_html_gate

        with tempfile.TemporaryDirectory() as temp_dir:
            result = _run_rendered_html_gate(Path(temp_dir), [{"beat_id": "s01"}])

        self.assertFalse(result["passed"])
        self.assertIn("rendered_html_dir_missing", result["failures"])

    def test_rendered_html_gate_rejects_missing_contract(self):
        from scripts.video_toolchain_runner import _run_rendered_html_gate

        with tempfile.TemporaryDirectory() as temp_dir:
            result = _run_rendered_html_gate(Path(temp_dir), [])

        self.assertFalse(result["passed"])
        self.assertIn("rendered_html_contract_missing", result["failures"])

    def test_renderer_environment_forwards_plan_subtitle_position(self):
        from scripts.video_toolchain_runner import _renderer_environment

        with patch.dict(os.environ, {"FILM_SUB_Y_UP": "300"}, clear=False):
            env = _renderer_environment({"subtitle_y_up": 270})
        self.assertEqual(env["FILM_SUB_Y_UP"], "270")

    def test_load_visual_assets_uses_plan_path_without_extra_environment_variable(self):
        from scripts.video_toolchain_runner import _load_visual_assets

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "visual_assets.json"
            payload = {"assignments": [{"scene": 1, "background_image": "/tmp/scene.png"}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("VIDEO_VISUAL_ASSETS_PATH", None)
                loaded = _load_visual_assets({"visual_assets_path": str(path)})

        self.assertEqual(loaded, payload)

    def test_creative_structure_family_rewrites_scene_contract_into_executable_modes(self):
        from scripts.video_toolchain_runner import _apply_creative_structure_to_contract

        contract = [
            {
                "beat_id": f"s{index:02d}",
                "visual_mode": "generic_card",
                "group_motion": ["fade"],
            }
            for index in range(1, 9)
        ]
        plan = {
            "creative_structure": {
                "selected": {
                    "family": "document_workflow",
                    "capability_mapping": {
                        "source_visual_modes": ["generic_card"],
                        "target_visual_modes": [
                            "before_after_split",
                            "terminal_evidence",
                            "annotation_callout",
                            "flow_track",
                            "input_branch",
                            "checklist_lock",
                            "failure_rollback",
                            "result_audit",
                        ],
                        "semantic_compatible": True,
                    },
                },
            }
        }

        rewritten = _apply_creative_structure_to_contract(plan, contract)

        self.assertEqual(
            [scene["visual_mode"] for scene in rewritten],
            [
                "before_after_split",
                "terminal_evidence",
                "annotation_callout",
                "flow_track",
                "input_branch",
                "checklist_lock",
                "failure_rollback",
                "result_audit",
            ],
        )
        self.assertTrue(all(scene["structure_family"] == "document_workflow" for scene in rewritten))
        self.assertTrue(all(scene["template_id"].startswith("document_workflow_") for scene in rewritten))
        from scripts.visual_contract_gate import KNOWN_MOTION_ACTIONS
        self.assertTrue(
            all(
                set(scene["group_motion"]).issubset(KNOWN_MOTION_ACTIONS)
                for scene in rewritten
            )
        )

    def test_creative_structure_preserves_explicit_scene_specific_mode_and_hook(self):
        from scripts.video_toolchain_runner import (
            STRUCTURE_SCENE_MODES,
            _apply_creative_structure_to_contract,
        )

        contract = [
            {
                "beat_id": f"s{index:02d}",
                "visual_mode": "factory_inspection_closeup" if index == 1 else "generic_card",
                "visual_hook": "Show the actual defect under inspection" if index == 1 else "",
                "group_motion": ["focus_shift"],
            }
            for index in range(1, 9)
        ]
        plan = {
            "creative_structure": {
                "selected": {
                    "family": "timeline_process",
                    "capability_mapping": {
                        "source_visual_modes": ["generic_card"],
                        "target_visual_modes": list(STRUCTURE_SCENE_MODES["timeline_process"]),
                        "semantic_compatible": True,
                    },
                }
            }
        }

        rewritten = _apply_creative_structure_to_contract(plan, contract)

        self.assertEqual(rewritten[0]["visual_mode"], "factory_inspection_closeup")
        self.assertEqual(rewritten[0]["visual_hook"], "Show the actual defect under inspection")
        self.assertEqual(rewritten[1]["visual_mode"], "evidence_timeline")

    def test_creative_structure_does_not_map_without_semantically_compatible_capability_mapping(self):
        from scripts.video_toolchain_runner import (
            STRUCTURE_SCENE_MODES,
            _apply_creative_structure_to_contract,
        )

        contract = [
            {"beat_id": f"s{index:02d}", "visual_mode": "factory_scene", "group_motion": ["focus_shift"]}
            for index in range(1, 9)
        ]
        plan = {
            "creative_structure": {
                "selected": {
                    "family": "timeline_process",
                    "capability_mapping": {
                        "source_visual_modes": ["factory_scene"],
                        "target_visual_modes": list(STRUCTURE_SCENE_MODES["timeline_process"]),
                        "semantic_compatible": False,
                    },
                }
            }
        }

        rewritten = _apply_creative_structure_to_contract(plan, contract)

        self.assertEqual([scene["visual_mode"] for scene in rewritten], ["factory_scene"] * 8)

    def test_script_structure_gate_requires_distinct_story_beats(self):
        from scripts.video_toolchain_runner import validate_script_structure

        too_short = validate_script_structure("Only one useful observation.")
        complete = validate_script_structure("\n".join(f"Distinct practical beat {index}." for index in range(1, 9)))

        self.assertFalse(too_short["passed"])
        self.assertIn("story_beats_insufficient", too_short["failures"])
        self.assertTrue(complete["passed"])

    def test_build_cards_does_not_insert_placeholder_copy(self):
        from scripts.video_toolchain_runner import build_cards

        script = "\n".join(f"Specific narrative beat {index}." for index in range(1, 9))
        cards = build_cards(script, "Specific title", {"template_family": "knowledge_card_motion_case"})
        serialized = json.dumps(cards, ensure_ascii=False).casefold()

        self.assertNotIn("keep the visual rhythm", serialized)
        self.assertNotIn("match visual to narration", serialized)
        self.assertNotIn("step 1", serialized)

    def test_runner_blocks_non_dry_short_scripts_before_renderer(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps({"platforms": ["kuaishou"]}), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Only one useful observation.", "Useful title"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 5)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "script_structure_failed")

    def test_intl_short_video_pipeline_is_manual_handoff_with_tool_evidence(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "intl_short_video_pipeline.py"
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "CONTENT_PLATFORM_HOME": tmp,
                "PYTHONPATH": str(root),
                "PYTHONIOENCODING": "utf-8",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "--dry-run"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = Path(tmp) / "data" / "intl_video_drafts" / "manifest_"
            manifests = sorted(manifest.parent.glob("manifest_*.json"))
            self.assertTrue(manifests, proc.stdout)
            data = json.loads(manifests[-1].read_text(encoding="utf-8"))
            rows = data["self_gen"] + data["cross_post"]
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(row["status"], "handoff_pending")
                self.assertEqual(row["publish_boundary"], "manual_handoff_only_no_aitoearn")
                self.assertIn("tool_invocation_manifest", row)
                self.assertIn("tools_capability_analysis", row)
                self.assertIn("tool_selection_plan", row)
                self.assertTrue(row["handoff_policy"]["manual_only"])
                self.assertIn("aitoearn_publish", row["handoff_policy"]["forbidden"])

    def test_intl_short_video_pipeline_blocks_aitoearn_for_manual_platforms(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "intl_short_video_pipeline.py"
        spec = importlib.util.spec_from_file_location("intl_short_video_pipeline", script)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        with patch.dict(os.environ, {"AITOEARN_INTL_API_KEY": "fake-key"}):
            for platform in ["youtube", "youtube_shorts", "tiktok", "threads"]:
                self.assertFalse(module.publish_video("/tmp/fake.mp4", "title", platform))

    def test_runner_dry_run_materializes_plan_cards_and_output(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Cat workflow"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((out / "dry_run.mp4").is_file())
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cards), 8)
            self.assertEqual(cards[0]["hook"], "Cat workflow")
            self.assertEqual(manifest["template_family"], "pet_repost_real_behavior")
            self.assertTrue((out / "visual_recipe.json").is_file())
            self.assertTrue((out / "pre_render_gate.json").is_file())
            self.assertTrue(manifest["visual_recipe_gate"]["passed"])
            self.assertTrue(manifest["pre_render_gate"]["passed"])
            self.assertTrue(str(manifest["recipe_fingerprint"]).startswith("sha256:"))
            self.assertTrue(manifest["dedup_required"])
            self.assertTrue(manifest["dedup_gate"]["required"])
            self.assertFalse(
                manifest["dedup_gate"].get("status") == "not_run"
                and manifest["dedup_gate"].get("passed") is True
            )
            self.assertGreaterEqual(manifest["toolchain_contract"]["visual_recipe"]["module_count"], 3)
            self.assertIn("tools_capability_analysis", manifest)
            self.assertIn("tool_selection_plan", manifest)
            self.assertIn("tool_invocation_manifest", manifest)
            self.assertTrue(manifest["tools_capability_analysis"]["all_relevant_tool_types_analyzed"])
            self.assertGreaterEqual(len(manifest["tool_selection_plan"]["selected_tools"]), 6)
            self.assertTrue(manifest["shotcraft_motion_plan"]["available"])
            self.assertGreaterEqual(manifest["shotcraft_motion_plan"]["registry_count"], 100)
            self.assertTrue(cards[0]["shotcraft"]["available"])

    def test_runner_rejects_invalid_visual_recipe(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["kuaishou"],
                "visual_recipe": {
                    "template_family": "knowledge_card_motion_case",
                    "modules": ["template_theme"],
                    "selection_reason": "",
                },
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Invalid recipe"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "visual_recipe_failed")
            self.assertFalse(manifest["visual_recipe_gate"]["passed"])

    def test_runner_rejects_recent_duplicate_visual_recipe_core(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            first_out = Path(tmp) / "first"
            out = Path(tmp) / "out"
            registry = Path(tmp) / "visual_recipe_registry.json"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "content_form": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["kuaishou"],
                "color_mood": "clean_blueprint",
                "motion_density": "medium",
                "text_layout": "timeline_cards",
                "scene_change_interval_sec": 4,
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            first_env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(first_out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            first_proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Old topic"],
                capture_output=True,
                text=True,
                env=first_env,
                timeout=30,
                check=False,
            )
            self.assertEqual(first_proc.returncode, 0, first_proc.stderr)
            first_manifest = json.loads((first_out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            duplicate = first_manifest["visual_recipe"]
            registry.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": duplicate["core_fingerprint"],
                                "fingerprint": duplicate["fingerprint"],
                                "template_family": duplicate["template_family"],
                                "platforms": ["kuaishou"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "New topic"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "visual_recipe_reuse_failed")
            self.assertFalse(manifest["recipe_reuse_gate"]["passed"])
            self.assertEqual(manifest["recipe_reuse_gate"]["duplicate_count"], 1)

    def test_recipe_reuse_gate_allows_failed_same_work_rerender_only_with_material_structure_change(self):
        from scripts.video_toolchain_runner import _recipe_reuse_gate

        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "visual_recipe_registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "trusted": True,
                        "coverage_days": 7,
                        "recipes": [
                            {
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": "sha256:same",
                                "template_family": "industrial_inspection_workflow_v1",
                                "platforms": ["douyin"],
                                "work_id": "work-42",
                                "revision": 3,
                                "attempt": 1,
                                "terminal_status": "visual_gate_failed",
                                "dom_structure_signatures": ["old-title-card", "old-title-card"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            recipe = {
                "core_fingerprint": "sha256:same",
                "template_family": "industrial_inspection_workflow_v1",
                "modules": ["template_theme"],
                "style_variants": {"color_mood": "clean_blueprint"},
                "dom_structure_signatures": ["factory-scene", "annotated-defect"],
            }
            plan = {
                "platforms": ["douyin"],
                "work_id": "work-42",
                "revision": 3,
                "attempt": 2,
            }
            with patch.dict(os.environ, {"VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                result = _recipe_reuse_gate(recipe, plan)

        self.assertTrue(result["passed"])
        self.assertEqual(result["duplicate_count"], 0)
        self.assertEqual(result["same_work_rerender_count"], 1)

    def test_recipe_reuse_gate_rejects_same_work_rerender_after_success_or_without_material_change(self):
        from scripts.video_toolchain_runner import _recipe_reuse_gate

        recipe = {
            "core_fingerprint": "sha256:same",
            "template_family": "industrial_inspection_workflow_v1",
            "modules": ["template_theme"],
            "style_variants": {"motion_density": "medium"},
            "dom_structure_signatures": ["factory-scene", "annotated-defect"],
        }
        plan = {"platforms": ["douyin"], "work_id": "work-42", "revision": 3, "attempt": 2}
        for terminal_status, signatures in (
            ("handoff_ready", ["old-title-card", "old-title-card"]),
            ("visual_gate_failed", ["factory-scene", "annotated-defect"]),
        ):
            with self.subTest(terminal_status=terminal_status):
                with tempfile.TemporaryDirectory() as tmp:
                    registry = Path(tmp) / "visual_recipe_registry.json"
                    registry.write_text(
                        json.dumps({
                            "trusted": True,
                            "coverage_days": 7,
                            "recipes": [{
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": "sha256:same",
                                "template_family": "industrial_inspection_workflow_v1",
                                "platforms": ["douyin"],
                                "work_id": "work-42",
                                "revision": 3,
                                "attempt": 1,
                                "terminal_status": terminal_status,
                                "dom_structure_signatures": signatures,
                            }]
                        }),
                        encoding="utf-8",
                    )
                    with patch.dict(os.environ, {"VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                        result = _recipe_reuse_gate(recipe, plan)

                self.assertFalse(result["passed"])
                self.assertEqual(result["duplicate_count"], 1)

    def test_recipe_reuse_gate_fails_closed_without_trusted_seven_day_registry_in_production(self):
        from scripts.video_toolchain_runner import _recipe_reuse_gate

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-registry.json"
            with patch.dict(
                os.environ,
                {"VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(missing)},
                clear=False,
            ):
                os.environ.pop("VIDEO_TOOLCHAIN_DRY_RUN", None)
                result = _recipe_reuse_gate(
                    {"core_fingerprint": "sha256:new", "template_family": "family"},
                    {"platforms": ["douyin"]},
                )

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "not_run")
        self.assertTrue(result["required"])
        self.assertIn("trusted_seven_day_registry_missing", result["failures"])

    def test_registry_defaults_to_the_shared_registry_before_the_job_home(self):
        import scripts.video_toolchain_runner as runner

        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared.json"
            shared.write_text("{}", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "VISUAL_RECIPE_FINGERPRINT_REGISTRY"}
            with patch.dict(os.environ, {**env, "HERMES_HOME": str(Path(tmp) / "job-home")}, clear=True), \
                    patch.object(runner, "SHARED_VISUAL_RECIPE_REGISTRY", shared):
                self.assertEqual(runner._visual_recipe_registry_path(), shared)
            with patch.dict(os.environ, {**env, "HERMES_HOME": str(Path(tmp) / "job-home")}, clear=True), \
                    patch.object(runner, "SHARED_VISUAL_RECIPE_REGISTRY", Path(tmp) / "absent.json"):
                self.assertEqual(runner._visual_recipe_registry_path(), Path(tmp) / "job-home" / "data" / "visual_recipe_fingerprints.json")

    def test_runner_rejects_cross_platform_same_core_visual_recipe(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            first_out = Path(tmp) / "first"
            out = Path(tmp) / "out"
            registry = Path(tmp) / "visual_recipe_registry.json"
            base_plan = {
                "selected_pipeline": "knowledge_card_video",
                "content_form": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
            }
            first_plan_path = Path(tmp) / "first_plan.json"
            first_plan_path.write_text(json.dumps({**base_plan, "platforms": ["douyin"]}), encoding="utf-8")
            first_env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(first_out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(first_plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            first_proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "Old topic"],
                capture_output=True,
                text=True,
                env=first_env,
                timeout=30,
                check=False,
            )
            self.assertEqual(first_proc.returncode, 0, first_proc.stderr)
            duplicate = json.loads((first_out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))["visual_recipe"]
            registry.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "used_at": "2099-01-01T00:00:00+00:00",
                                "core_fingerprint": duplicate["core_fingerprint"],
                                "fingerprint": duplicate["fingerprint"],
                                "template_family": duplicate["template_family"],
                                "platforms": ["douyin"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps({**base_plan, "platforms": ["youtube"]}), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
                "VISUAL_RECIPE_FINGERPRINT_REGISTRY": str(registry),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Scene one.\nScene two.\nScene three.", "New platform topic"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "visual_recipe_reuse_failed")
            self.assertFalse(manifest["recipe_reuse_gate"]["passed"])
            self.assertEqual(manifest["recipe_reuse_gate"]["duplicates"][0]["duplicate_scope"], "cross_platform")

    def test_localized_repost_refuses_original_card_fallback_without_source(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Do not turn this into original cards.", "Repost only"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "source_required")
            self.assertIn("refusing original card fallback", manifest["error"])

    def test_localized_repost_blocks_when_dedup_evidence_is_incomplete(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"source-video")
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
                "source_video_path": str(source),
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }
            proc = subprocess.run(
                [sys.executable, str(script), "Repost source.", "Repost only"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse((out / "cards.json").exists())
            self.assertFalse((out / "final.mp4").exists())
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "BLOCKED_DEDUP")
            self.assertFalse(manifest["dedup_evidence"]["passed"])
            self.assertTrue((out / "dedup_evidence.json").is_file())

    def test_localized_repost_requires_passing_pre_and_post_render_dedup(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            source = Path(tmp) / "source.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=96x64:rate=8:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(source),
                ],
                check=True,
            )
            history = Path(tmp) / "history.jsonl"
            history.write_text("", encoding="utf-8")
            plan = {
                "selected_pipeline": "localized_repost_video",
                "template_family": "pet_repost_real_behavior",
                "platforms": ["douyin"],
                "source_video_path": str(source),
                "source_identity": {
                    "source_id": "provider:video-1",
                    "source_uri": "https://example.test/video-1",
                },
                "repost_history_index": str(history),
                "repost_transform": {
                    "kind": "localized_caption_edit",
                    "description": "Chinese captions and editorial cuts",
                },
                "source_rights": {"basis": "licensed", "reference": "license-42"},
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
            }

            proc = subprocess.run(
                [sys.executable, str(script), "Repost source.", "Repost only"],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stderr)
            evidence = json.loads((out / "dedup_evidence.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "candidate_gate_failed")
            self.assertIn("candidate_gate", manifest)
            self.assertFalse(manifest["candidate_gate"]["passed"])
            self.assertTrue(evidence["passed"])
            self.assertEqual(evidence["stage"], "post_render")
            self.assertTrue(evidence["pre_render_fingerprints"])
            self.assertTrue(evidence["post_render_verification"]["passed"])
            self.assertFalse((out / "final.mp4").exists())
            self.assertFalse((out / "cards.json").exists())

    def test_autoclip_repost_blocks_packaging_without_valid_dedup_evidence(self):
        from scripts.video_toolchain_runner import _run_autoclip_repost

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            generated = out / "autoclip" / "candidate.mp4"
            generated.parent.mkdir(parents=True)
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=96x64:rate=8:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000:duration=1",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(generated),
                ],
                check=True,
            )
            completed = subprocess.CompletedProcess([], 0, stdout="ok", stderr="")
            with patch("scripts.video_toolchain_runner.subprocess.run", return_value=completed):
                result = _run_autoclip_repost(
                    {"platforms": ["douyin"]},
                    out,
                    "title",
                    "https://example.test/source",
                    {"ok": False},
                )

            self.assertEqual(result, 7)
            self.assertFalse((out / "final.mp4").exists())
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "candidate_manifest_missing")

    def test_runner_dry_run_includes_cinema_storyboard_fields(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["bilibili"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "为了省时间我装了15个AI工具。步骤一：砍掉功能重叠。", "AI工具效率"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("cinema_storyboard", manifest)
            self.assertEqual(len(manifest["cinema_storyboard"]), 8)
            first = cards[0]
            for key in ["cinema", "traffic_pattern", "composition_advice", "layout_template", "color_scheme", "css"]:
                self.assertIn(key, first)
            self.assertIn("rgba(", first["css"]["card_bg"])
            self.assertIn("rgba(", first["css"]["card_border"])

    def test_runner_dry_run_records_full_toolchain_contract(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "AI 工具太多会拖慢工作流。步骤一：先砍重复工具。", "AI工具工作流"],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,  # workflow context + recipe generation can exceed 30s under full-suite load
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            contract = manifest["toolchain_contract"]
            for tool in [
                "cinema_composition.storyboard",
                "shotcraft_moves.shot_plan_for_text",
                "shotcraft_moves.shot_sequence",
                "video_toolchain_runner.build_cards",
                "kuaishou_render.render_cards",
                "kuaishou_render.gen_tts",
                "kuaishou_render.render_segments",
                "kuaishou_render.concat_video",
                "kuaishou_render.download_bgm",
                "mix_bgm_with_gate.mix_bgm",
                "kuaishou_render.gen_subtitles",
                "kuaishou_render.encode_final",
                "visual_gate.py --cinema",
            ]:
                self.assertIn(tool, contract["planned_tools"])
            self.assertIn("cinema_color_css", contract["effect_stack"])
            self.assertIn("shotcraft_motion_css", contract["effect_stack"])
            self.assertGreaterEqual(contract["template_registry"]["shotcraft_registry_count"], 100)
            self.assertEqual(contract["template_registry"]["theme"], "cyber-neon")
            self.assertIn("visual_gate.py --cinema", contract["post_render_gates"])
            self.assertIn("--bgm-style", manifest["renderer_command_preview"])
            self.assertIn("--width", manifest["renderer_command_preview"])
            self.assertIn("1080", manifest["renderer_command_preview"])
            self.assertIn("--height", manifest["renderer_command_preview"])
            self.assertIn("1920", manifest["renderer_command_preview"])
            self.assertEqual(manifest["bgm_style"], contract["bgm_style"])

    def test_cinema_visual_gate_skips_auxiliary_render_layers(self):
        from scripts import video_toolchain_runner as runner

        self.assertTrue(runner._is_full_card_visual_candidate(Path("card_01.png")))
        self.assertFalse(runner._is_full_card_visual_candidate(Path("card_01_bg.png")))
        self.assertFalse(runner._is_full_card_visual_candidate(Path("card_01_text.png")))

    def test_kuaishou_layered_text_filters_are_distinct_motion_paths(self):
        from scripts import kuaishou_render as renderer

        filters = [renderer._text_layer_filter(1080, 1920, 100, idx) for idx in range(4)]
        self.assertEqual(len(set(filters)), 4)
        self.assertTrue(any("iw*1.018" in item for item in filters))
        self.assertTrue(any("min(24" in item for item in filters))
        self.assertTrue(any("max(0, 24-n*24" in item or "max(0,24" in item for item in filters))
        layered = renderer._layered_segment_filter(1080, 1920, 100, 2)
        self.assertIn("[0:v]", layered)
        self.assertIn("[1:v]", layered)
        self.assertIn("overlay=x=", layered)
        self.assertIn("eval=frame", layered)

    def test_kuaishou_background_motion_meets_artifact_gate_threshold(self):
        from scripts import kuaishou_render as renderer

        filters = [renderer._background_layer_filter(1080, 1920, 100, idx) for idx in range(4)]

        self.assertIn("0.30*on/100", filters[0])
        self.assertIn("1.45", filters[0])
        self.assertIn("0.30*on/100", filters[1])
        self.assertIn("sin(on/30)*80", filters[2])
        self.assertIn("cos(on/30)*80", filters[3])

    def test_runner_passes_target_platform_to_shared_subtitle_renderer(self):
        from scripts.video_toolchain_runner import _renderer_command

        command = _renderer_command(
            Path("/tmp/renderer.py"),
            Path("/tmp/out"),
            "blueprint",
            "Video title",
            "A useful script.",
            {"platforms": ["shipinhao"]},
            "light piano",
        )

        self.assertIn("--platform", command)
        self.assertEqual(command[command.index("--platform") + 1], "shipinhao")

    def test_runner_honors_explicit_dimensions_tags_and_audio_route(self):
        from scripts.video_toolchain_runner import _renderer_command

        command = _renderer_command(
            Path("/tmp/film_renderer.py"),
            Path("/tmp/out"),
            "blueprint",
            "Video title",
            "A useful script.",
            {
                "platforms": ["douyin"],
                "width": 720,
                "height": 1280,
                "tags": ["AI质检", "智能制造", "工业AI"],
                "audio_plan": {
                    "route": "sfx_only",
                    "route_reason": "voice and effects only",
                    "source_audio_action": "replace_with_voiceover_and_sfx",
                    "fallback_route": None,
                },
            },
            "muted percussion",
        )

        self.assertEqual(command[command.index("--width") + 1], "720")
        self.assertEqual(command[command.index("--height") + 1], "1280")
        tag_start = command.index("--tags") + 1
        self.assertEqual(command[tag_start:tag_start + 3], ["AI质检", "智能制造", "工业AI"])
        self.assertEqual(command[command.index("--audio-route") + 1], "sfx_only")
        self.assertNotIn("猫咪", command)

    def test_workflow_platform_can_differ_from_delivery_platform(self):
        from scripts.video_toolchain_runner import _primary_platform, _workflow_platform

        plan = {"platforms": ["douyin"], "workflow_platform": "douyin_ai"}
        self.assertEqual(_primary_platform(plan), "douyin")
        self.assertEqual(_workflow_platform(plan), "douyin_ai")

    def test_landscape_renderer_uses_separate_background_and_text_layers(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "render_landscape_video.py").read_text(encoding="utf-8")

        self.assertIn("slide_{idx:02d}_bg.html", source)
        self.assertIn("slide_{idx:02d}_text.html", source)
        self.assertIn("card_{idx:02d}_bg.png", source)
        self.assertIn("card_{idx:02d}_text.png", source)
        self.assertIn("zoompan=", source)
        self.assertIn("overlay=0:0:format=auto", source)

    def test_runner_dry_run_records_shotcraft_motion_plan(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "AI tools can slow teams down.\n\nUse one tool per workflow stage.\n\nEnd with a clear rule.",
                    "AI tool workflow rules",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            cards = json.loads((out / "cards.json").read_text(encoding="utf-8"))
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            shotcraft = manifest["shotcraft_motion_plan"]
            self.assertTrue(shotcraft["available"])
            self.assertGreaterEqual(shotcraft["registry_count"], 100)
            self.assertGreaterEqual(len(shotcraft["selected_shots"]), 3)
            self.assertGreaterEqual(len(shotcraft["timeline"]), 3)
            self.assertEqual(cards[0]["shotcraft"]["name"], shotcraft["timeline"][0]["name"])

    def test_runner_accepts_bom_prefixed_plan_json(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "video_toolchain_runner.py"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            plan = {
                "selected_pipeline": "knowledge_card_video",
                "template_family": "knowledge_card_motion_case",
                "platforms": ["youtube"],
            }
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text("\ufeff" + json.dumps(plan), encoding="utf-8")
            env = {
                **os.environ,
                "VIDEO_OUTPUT_DIR": str(out),
                "VIDEO_TOOLCHAIN_PLAN_PATH": str(plan_path),
                "VIDEO_TOOLCHAIN_DRY_RUN": "1",
            }
            proc = subprocess.run(
                [sys.executable, str(script), "One useful script beat.\n\nAnother visual beat.", "BOM plan"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = json.loads((out / "video_toolchain_runner_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["shotcraft_motion_plan"]["available"])

    def test_intl_short_video_defaults_to_project_toolchain_before_legacy_fallback(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "intl_short_video_pipeline.py").read_text(encoding="utf-8")

        self.assertLess(source.index("_gen_with_project_toolchain"), source.index("screencast_engine.py"))
        self.assertIn("INTL_VIDEO_ALLOW_LEGACY_FALLBACK", source)
        self.assertIn("video_toolchain_runner.py", source)

    def test_renderer_html_consumes_cinema_css_when_background_image_is_absent(self):
        from scripts.kuaishou_render import THEMES, build_card_html

        html = build_card_html(
            {
                "layout": "cover",
                "hook": "AI工具工作流",
                "sub": "减少维护成本",
                "css": {
                    "bg_gradient": "linear-gradient(135deg, rgb(30, 35, 45) 0%, rgb(55, 65, 80) 100%)",
                    "accent_color": "rgb(62, 207, 135)",
                    "text_primary": "#ffffff",
                    "card_bg": "rgba(55,65,80,0.85)",
                },
            },
            1,
            None,
            None,
            THEMES["cyber-neon"],
        )

        self.assertIn("linear-gradient(135deg, rgb(30, 35, 45)", html)
        self.assertIn("repeating-linear-gradient", html)
        self.assertIn("rgb(62, 207, 135)", html)

    def test_renderer_video_assertion_uses_ffprobe_when_size_is_below_legacy_threshold(self):
        from scripts.kuaishou_render import assert_output

        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "short.mp4"
            video.write_bytes(b"0" * 80_000)

            fake = type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "streams": [{"codec_type": "video", "width": 720, "height": 1280}],
                            "format": {"duration": "12.5", "size": "80000"},
                        }
                    ),
                    "stderr": "",
                },
            )()
            with patch("scripts.kuaishou_render.subprocess.run", return_value=fake):
                assert_output(str(video), 2_000_000, "short.mp4")

    def test_bgm_download_uses_online_real_instrument_candidate(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            (root / "raw.mp4").write_bytes(b"0" * 900_000)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic-guitar.mp3",
                "source_url": "https://pixabay.com/music/acoustic-guitar",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "Pixabay Content License",
                "attribution_required": False,
                "duration": 90,
                "asset_id": "px1",
                "tags": "acoustic guitar instrumental folk",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(b"1" * 900_000)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        bgm = download_bgm(root, "acoustic guitar")

            self.assertEqual(Path(bgm), root / "bgm.mp3")
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "pixabay_music")
            self.assertEqual(source["license"], "Pixabay Content License")
            self.assertTrue(source["sha256"])
            registry_data = json.loads(registry.read_text(encoding="utf-8"))
            self.assertEqual(registry_data["tracks"][0]["fingerprint"], source["sha256"])

    def test_bgm_download_rejects_registry_duplicate_fingerprint(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            duplicate_bytes = b"1" * 900_000
            duplicate_hash = __import__("hashlib").sha256(duplicate_bytes).hexdigest()
            registry.write_text(json.dumps({"tracks": [{"fingerprint": duplicate_hash, "title": "used"}]}), encoding="utf-8")
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic-guitar.mp3",
                "source_url": "https://pixabay.com/music/acoustic-guitar",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "Pixabay Content License",
                "attribution_required": False,
                "duration": 90,
                "asset_id": "px1",
                "tags": "acoustic guitar instrumental folk",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(duplicate_bytes)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        with self.assertRaisesRegex(RuntimeError, "BGM fingerprint already used"):
                            download_bgm(root, "acoustic guitar")

            self.assertFalse((root / "bgm_source.json").exists())

    def test_bgm_download_replaces_stale_existing_bgm_every_render(self):
        from scripts.kuaishou_render import download_bgm, REAL_BGM_MIN_BYTES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "bgm_registry.json"
            (root / "bgm.mp3").write_bytes(b"old" * (REAL_BGM_MIN_BYTES // 3))
            (root / "bgm_source.json").write_text(
                json.dumps({"source": "local_instrument_bgm_library", "license": "operator_provided"}),
                encoding="utf-8",
            )
            candidate = {
                "provider": "openverse_audio",
                "download_url": "https://cdn.example/acoustic.mp3",
                "source_url": "https://freesound.example/sounds/1",
                "title": "Acoustic guitar instrumental",
                "artist": "artist",
                "license": "https://creativecommons.org/licenses/by/4.0/",
                "attribution_required": True,
                "duration": 90,
                "asset_id": "ov1",
                "tags": "acoustic guitar instrumental",
                "license_verified": True,
            }

            def fake_download(row, output):
                output.write_bytes(b"new" * 300_000)

            with patch.dict(os.environ, {"BGM_FINGERPRINT_REGISTRY": str(registry)}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render._download_candidate_bgm", side_effect=fake_download):
                        download_bgm(root, "acoustic guitar")

            self.assertEqual((root / "bgm.mp3").read_bytes(), b"new" * 300_000)
            source = json.loads((root / "bgm_source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["source"], "openverse_audio")

    def test_bgm_download_reuses_valid_existing_bgm(self):
        from scripts.kuaishou_render import download_bgm, REAL_BGM_MIN_BYTES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bgm.mp3").write_bytes(b"x" * (REAL_BGM_MIN_BYTES + 1000))
            (root / "bgm_source.json").write_text(
                json.dumps({"source": "openverse_audio", "license": "cc0", "title": "valid"}),
                encoding="utf-8",
            )
            with patch("scripts.kuaishou_render._online_bgm_candidates") as mock_online:
                result = download_bgm(root, "acoustic guitar")
            mock_online.assert_not_called()
            self.assertEqual(result, str(root / "bgm.mp3"))

    def test_bgm_download_refuses_synthetic_or_no_bgm_fallback(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw.mp4").write_bytes(b"0" * 80_000)

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "online real-instrument BGM unavailable"):
                    download_bgm(root, "lo-fi")

    def test_bgm_download_stops_when_the_global_resolution_budget_is_exhausted(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/acoustic.mp3",
                "source_url": "https://pixabay.example/acoustic",
                "title": "Acoustic guitar instrumental",
                "license": "Pixabay Content License",
                "tags": "acoustic guitar instrumental",
            }
            with patch.dict(os.environ, {"BGM_RESOLUTION_MAX_SECONDS": "1"}, clear=False):
                with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                    with patch("scripts.kuaishou_render.time.monotonic", side_effect=[0.0, 2.0]):
                        # 2026-08-16：在线预算耗尽会自动兜底 archive（改进）；测试 patch 掉兜底验证原预算逻辑
                        with patch("scripts.kuaishou_render._fetch_archive_bgm", return_value=None):
                            with self.assertRaisesRegex(RuntimeError, "resolution budget exhausted"):
                                download_bgm(root, "acoustic guitar")

    def test_bgm_download_rejects_electronic_synthetic_candidates(self):
        from scripts.kuaishou_render import download_bgm

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = {
                "provider": "pixabay_music",
                "download_url": "https://cdn.example/synth.mp3",
                "source_url": "https://pixabay.com/music/synth",
                "title": "Electronic synth lofi beat",
                "artist": "artist",
                "license": "Pixabay Content License",
                "tags": "electronic synth instrumental",
            }

            with patch("scripts.kuaishou_render._online_bgm_candidates", return_value=[candidate]):
                with self.assertRaisesRegex(RuntimeError, "no licensed real-instrument candidates"):
                    download_bgm(root, "electronic")

    def test_openverse_candidates_require_commercial_safe_license(self):
        from scripts.kuaishou_render import _openverse_candidates

        payload = {
            "results": [
                {
                    "id": "ok",
                    "title": "Acoustic guitar instrumental",
                    "creator": "artist",
                    "url": "https://cdn.example/ok.mp3",
                    "foreign_landing_url": "https://example.test/ok",
                    "license": "by",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "duration": 90000,
                    "audio_set": {"title": "Acoustic guitar"},
                    "tags": [{"name": "guitar"}],
                },
                {
                    "id": "blocked",
                    "title": "Acoustic guitar nc",
                    "creator": "artist",
                    "url": "https://cdn.example/nc.mp3",
                    "foreign_landing_url": "https://example.test/nc",
                    "license": "by-nc",
                    "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
                },
            ]
        }

        with patch("scripts.kuaishou_render._request_json", return_value=payload):
            rows = _openverse_candidates("acoustic guitar instrumental")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "openverse_audio")
        self.assertEqual(rows[0]["duration"], 90)
        self.assertTrue(rows[0]["license_verified"])

    def test_youtube_audio_library_candidates_are_youtube_scoped(self):
        from scripts.kuaishou_render import _bgm_candidate_allowed, _youtube_audio_library_candidates

        payload = {
            "all": [
                {"id": "drive-id", "name": "Acoustic_Guitar_Story.mp3", "mimeType": "audio/mpeg"},
                {"id": "blocked-id", "name": "Digital_Synth_Pulse.mp3", "mimeType": "audio/mpeg"},
            ],
            "map": {"drive-id": "https://docs.google.com/uc?export=open&id=drive-id"},
        }

        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "youtube"}, clear=False):
            with patch("scripts.kuaishou_render._request_json", return_value=payload):
                rows = _youtube_audio_library_candidates("acoustic guitar instrumental")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "youtube_audio_library")
        self.assertEqual(rows[0]["license_scope"], "youtube_only")
        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "youtube"}, clear=False):
            self.assertTrue(_bgm_candidate_allowed(rows[0]))
        with patch.dict(os.environ, {"BGM_TARGET_PLATFORM": "kuaishou"}, clear=False):
            self.assertFalse(_bgm_candidate_allowed(rows[0]))

    def test_subtitles_are_wrapped_and_kept_above_bottom_safe_area(self):
        from scripts.kuaishou_render import gen_subtitles

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tts = root / "tts"
            tts.mkdir()
            (tts / "tts_01.mp3").write_bytes(b"0")

            def fake_run(command, **kwargs):
                return type("Result", (), {"returncode": 0, "stdout": "5.0", "stderr": ""})()

            cards = [{"tts": "这是一条非常长的字幕内容必须自动换行不能超过视频宽度否则就会贴边"}]
            with patch("scripts.kuaishou_render.subprocess.run", side_effect=fake_run):
                gen_subtitles(root, cards)

            ass = (root / "subtitles.ass").read_text(encoding="utf-8")
            self.assertIn("20,20,200", ass)
            self.assertIn(r"\N", ass)

    def test_card_html_uses_sub_as_center_body_when_txt_missing(self):
        from scripts.kuaishou_render import build_card_html

        html = build_card_html(
            {"layout": "two_column", "t": "Title", "sub": "center body from sub"},
            1,
            "",
            "",
            {"accent": "#fff", "accent2": "#eee", "bg": "000", "text": "#ddd", "card_bg": "rgba(0,0,0,.2)", "badge_bg": "rgba(0,0,0,.2)", "glass": "rgba(0,0,0,.2)"},
        )
        self.assertIn("center body from sub", html)

    def test_packet_schedule_slot_tolerates_non_numeric_working_directory(self):
        from scripts.kuaishou_render import _safe_schedule_slot

        self.assertEqual(_safe_schedule_slot("video_toolchain_real_contract_verify"), 0)
        self.assertEqual(_safe_schedule_slot("job_7"), 7)

    def test_legacy_video_generation_demos_are_fail_closed_by_default(self):
        root = Path(__file__).resolve().parents[1]
        guarded = [
            "scripts/animated_card_pipeline.py",
            "scripts/knowledge_card_demo.py",
            "scripts/kuaishou_final_pipeline.py",
            "scripts/render_animation.py",
            "scripts/douyin_cat_cards.py",
        ]
        for rel in guarded:
            source = (root / rel).read_text(encoding="utf-8")
            self.assertIn("raise SystemExit", source, rel)
        kuaishou_legacy = (root / "scripts/kuaishou_final_pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("SoundHelix", kuaishou_legacy)
        self.assertNotIn("bgm_test", kuaishou_legacy)
        self.assertNotIn("HERMES_ALLOW_LEGACY_RENDER_DEMO", kuaishou_legacy)

    def test_review_required_cover_status_is_a_release_failure(self):
        from scripts.video_toolchain_runner import _cover_gate_failures

        result = {"status": "review_required", "passed": False, "failures": []}
        failures = _cover_gate_failures(result)
        self.assertIn("cover_status_review_required", failures)

    def test_planned_tool_is_not_runtime_success_without_execution_evidence(self):
        from scripts.video_toolchain_runner import _resolve_tool_invocation_status

        invocations = {
            "cinema_composition.storyboard": {"status": "planned_internal"},
            "shotcraft_moves.shot_sequence": {"status": "planned_internal"},
        }
        resolved = _resolve_tool_invocation_status(invocations, runtime_evidence={})
        self.assertEqual(resolved["cinema_composition.storyboard"]["status"], "not_invoked")
        self.assertEqual(resolved["shotcraft_moves.shot_sequence"]["status"], "not_invoked")


if __name__ == "__main__":
    unittest.main()


def test_generated_cover_carries_the_works_own_text_not_a_demo():
    """MED59 (11-08 CST window): the douyin_pet cover read '用AI做表？别直接算总数', a fixed 09-21 Kuaishou demo cover."""
    from scripts.video_toolchain_runner import _cover_text

    clip = lambda text, limit: text[:limit]
    script = "一只灰白猫把爪子搭在沙发上，你真以为养高智商猫不会让人崩溃吗？\n\n单只狸花猫趴在洗衣机台上休息。"
    title, subtitle, hook, layout, tag = _cover_text({"platform": "douyin_pet"}, "同时拥有两只高智商猫的弊端", script, clip)
    assert title == "同时拥有两只高\n智商猫的弊端" and subtitle == hook == tag == ""
    assert "做表" not in title and layout == "premium_fintech"
    assert _cover_text({}, "Untitled video", script, clip)[0].replace("\n", "") == script[:16]
    assert _cover_text({"template_family": "finance_reconciliation"}, "t", script, clip)[3] == "premium_fintech"
