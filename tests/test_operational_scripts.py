import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class OperationalScriptTests(unittest.TestCase):
    def test_overnight_hot_work_collection_covers_all_scheduled_lanes(self):
        script = (Path(__file__).parents[1] / "scripts" / "run_overnight_batch.sh").read_text(encoding="utf-8")
        for platform in (
            "wechat", "kuaishou", "douyin_ai", "douyin_pet", "bilibili", "zhihu",
            "juejin", "xiaohongshu", "youtube", "tiktok", "twitter", "shipinhao",
        ):
            self.assertIn(f"--platform {platform}", script)
        self.assertIn("platform-browser-states.json", script)

    def test_bgm_uniqueness_fails_closed_without_source_or_fingerprint(self):
        from scripts.check_bgm_uniqueness import check

        with tempfile.TemporaryDirectory() as tmp:
            result = check(Path(tmp), platform="kuaishou", registry_path=Path(tmp) / "registry.json")

        self.assertFalse(result["passed"])
        self.assertIn("bgm_source_json_missing", result["failed_dimensions"])
        self.assertIn("bgm_fingerprint_missing", result["failed_dimensions"])

    def test_bgm_uniqueness_rejects_duplicate_and_registers_new_track(self):
        from scripts.check_bgm_uniqueness import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bgm = root / "bgm.mp3"
            bgm.write_bytes(b"a" * 80_000)
            source = {"sha256": "fp1", "title": "Acoustic", "source_url": "https://example.test/a.mp3", "license": "cc-by"}
            (root / "bgm_source.json").write_text(json.dumps(source), encoding="utf-8")
            registry = root / "registry.json"
            with patch("scripts.check_bgm_uniqueness._mean_volume", return_value=-18.0):
                first = check(root, platform="kuaishou", registry_path=registry)
                second = check(root, platform="kuaishou", registry_path=registry)

        self.assertTrue(first["passed"])
        self.assertFalse(second["passed"])
        self.assertIn("bgm_fingerprint_duplicate", second["failed_dimensions"])

    def test_media_delivery_requires_configured_target(self):
        from scripts.deliver_media import deliver

        with patch.dict(os.environ, {"HERMES_DELIVERY_ENV_FILE": str(Path(tempfile.gettempdir()) / "missing-notifications.env")}, clear=True):
            result = deliver("video", ["missing.mp4"])

        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "HERMES_DELIVERY_TARGET_missing")

    def test_media_delivery_blocks_cover_without_quality_evidence(self):
        from scripts.deliver_media import deliver

        with tempfile.TemporaryDirectory() as tmp:
            cover = Path(tmp) / "cover.png"
            cover.write_bytes(b"not-a-real-cover")
            with patch("scripts.deliver_media.resolve_target", return_value="telegram:test"), patch(
                "scripts.deliver_media._send"
            ) as send:
                result = deliver("cover", [str(cover)])

        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "cover_quality_gate_failed")
        send.assert_not_called()

    def test_topic_independence_requires_source_matrix(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "platform_source_matrix_20260807.json").write_text(
                json.dumps(
                    {
                        "selected_topic": "独立选题",
                        "platform_source_matrix": {
                            "attempted_sources": ["a", "b", "c", "d", "e", "f", "g", "h"],
                            "successful_sources": ["a", "b", "c", "d", "e"],
                            "platform_internal_verified": True,
                            "shared_trend_only": False,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            ok = check("20260807", ["wechat"], root=root)
            bad = check("20260807", ["kuaishou"], root=root)

        self.assertTrue(ok["passed"])
        self.assertFalse(bad["passed"])
        self.assertEqual(bad["failures"][0]["failed_dimensions"][0], "analysis_file_missing")

    def test_topic_independence_accepts_markdown_source_matrix(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# WeChat analysis

选题方向：AI 自动化效率幻觉实测复盘

| 来源 | 状态 | 关键发现 |
| --- | --- | --- |
| 搜狗微信（平台内） | ✅ 成功 | 公众号同赛道活跃 |
| 微博 | ✅ 成功 | AI 降本讨论升温 |
| 抖音 | ✅ 成功 | AI 工具短视频高频 |
| 知乎 | ✅ 成功 | 工具实测和血泪教训 |
| B站 | ✅ 成功 | AI 自动化教程活跃 |
| GitHub | ✅ 成功 | automation 项目上升 |
| 小红书 | ❌ login_required | 记录失败原因 |

| harken | success | additional trend evidence |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        matrix = result["records"]["wechat"]["matrix"]
        self.assertGreaterEqual(matrix["attempted_count"], 8)
        self.assertGreaterEqual(matrix["successful_count"], 5)
        self.assertTrue(matrix["platform_internal_evidence"])
        self.assertEqual(result["records"]["wechat"]["selected_topic"], "AI 自动化效率幻觉实测复盘")

    def test_topic_independence_accepts_markdown_source_matrix_without_emoji_status(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# 公众号运营分析

内容主题：AI 自动化效率幻觉实测复盘

| 来源 | 状态 | 关键发现 |
| --- | --- | --- |
| wechat internal | success | 公众号同赛道活跃 |
| weibo | success | AI 降本讨论升温 |
| douyin | success | AI 工具短视频高频 |
| zhihu | success | 工具实测和血泪教训 |
| bilibili | success | AI 自动化教程活跃 |
| github | success | automation 项目上升 |
| xiaohongshu | login_required | 记录失败原因 |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        matrix = result["records"]["wechat"]["matrix"]
        self.assertEqual(matrix["attempted_count"], 7)
        self.assertEqual(matrix["successful_count"], 6)
        self.assertTrue(matrix["platform_internal_evidence"])

    def test_topic_independence_uses_wechat_directory_hint_for_markdown_internal_source(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# WeChat analysis

| source | status | finding |
| --- | --- | --- |
| source_a | success | platform signal captured |
| source_b | success | signal |
| source_c | success | signal |
| source_d | success | signal |
| source_e | success | signal |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        self.assertTrue(result["records"]["wechat"]["matrix"]["platform_internal_evidence"])
        self.assertEqual(result["records"]["wechat"]["selected_topic"], "WeChat analysis")

    def test_topic_independence_falls_back_to_markdown_heading_for_topic(self):
        from scripts.check_platform_topic_independence import check

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis_dir = root / "data" / "local_ops_gzh"
            analysis_dir.mkdir(parents=True)
            (analysis_dir / "analysis_20260809.md").write_text(
                """
# Daily source matrix

| source | status | finding |
| --- | --- | --- |
| source_a | success | signal |
| source_b | success | signal |
| source_c | success | signal |
| source_d | success | signal |
| source_e | success | signal |

shared_trend_only: false
""",
                encoding="utf-8",
            )
            result = check("20260809", ["wechat"], root=root)

        self.assertTrue(result["passed"], result)
        self.assertEqual(result["records"]["wechat"]["selected_topic"], "Daily source matrix")

    def test_public_scripts_do_not_embed_private_runtime_paths_or_targets(self):
        checked = [
            "scripts/build_kuaishou_packet.py",
            "scripts/check_bgm_uniqueness.py",
            "scripts/check_platform_topic_independence.py",
            "scripts/deliver_media.py",
            "scripts/normalize_kuaishou_render_dir.py",
            "scripts/render_landscape_video.py",
            "scripts/validate_wechat_image_post_packet.py",
            "scripts/wechat_image_post_cards.py",
        ]
        for rel in checked:
            text = Path(rel).read_text(encoding="utf-8")
            self.assertNotIn("/roo" + "t/", text, rel)
            self.assertNotIn("5975" + "133381", text, rel)
            self.assertNotIn("PEXELS_API_KEY =", text, rel)

    def test_growth_cycle_service_uses_default_platform_set_without_omissions(self):
        from content_platform.performance_cycle import DEFAULT_GROWTH_PLATFORMS

        service = Path("systemd/hermes-content-platform-growth-cycle.service").read_text(encoding="utf-8")
        text = Path("scripts/run_growth_cycle.sh").read_text(encoding="utf-8")

        self.assertIn("run_growth_cycle.sh", service)
        self.assertIn("performance-cycle", text)
        for platform in DEFAULT_GROWTH_PLATFORMS:
            self.assertIn(f"--platform {platform}", text)

    def test_growth_and_wechat_entrypoints_require_explicit_mutable_roots(self):
        for name in ("scripts/run_growth_cycle.sh", "scripts/run_wechat_metrics_refresh.sh"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertIn('CONTENT_PLATFORM_DATA_DIR:?CONTENT_PLATFORM_DATA_DIR is required', text)
            self.assertIn('CONTENT_PLATFORM_SECRETS_DIR:?CONTENT_PLATFORM_SECRETS_DIR is required', text)
            self.assertNotIn('$root/data', text)
            self.assertNotIn('$root/secrets', text)

    def test_cli_systemd_units_use_current_release_and_explicit_runtime_roots(self):
        for path in sorted(Path("systemd").glob("*.service")):
            text = path.read_text(encoding="utf-8")
            self.assertIn("Environment=CONTENT_PLATFORM_HOME=%h/.ai-self-media-tools-current", text, path)
            self.assertIn("Environment=CONTENT_PLATFORM_CODE_ROOT=%h/.ai-self-media-tools-current", text, path)
            self.assertIn("Environment=PYTHONPATH=%h/.ai-self-media-tools-current", text, path)
            self.assertIn("Environment=CONTENT_PLATFORM_DATA_DIR=%h/.ai-self-media-tools/data", text, path)
            self.assertIn("Environment=CONTENT_PLATFORM_SECRETS_DIR=%h/.ai-self-media-tools/secrets", text, path)
            self.assertIn("Environment=CONTENT_PLATFORM_CONFIG=%h/.ai-self-media-tools/config.json", text, path)
            self.assertIn("Environment=CONTENT_PLATFORM_RUNTIME_MODE=production", text, path)
            self.assertNotIn("%h/.local/bin/content-platform", text, path)

    def test_overnight_entrypoints_require_private_runtime_roots(self):
        for name in ("scripts/run_overnight_batch.sh", "scripts/run_overnight_supervisor.sh"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertIn('CONTENT_PLATFORM_DATA_DIR:?CONTENT_PLATFORM_DATA_DIR is required', text)
            self.assertIn('CONTENT_PLATFORM_SECRETS_DIR:?CONTENT_PLATFORM_SECRETS_DIR is required', text)
            self.assertIn('CONTENT_PLATFORM_CONFIG:?CONTENT_PLATFORM_CONFIG is required', text)
            self.assertNotIn('$release_root/config.json', text)

    def test_overnight_script_refreshes_growth_strategy_before_prepare(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertLess(text.index("performance-cycle"), text.index("overnight-prepare"))

    def test_overnight_script_refreshes_delivery_health_before_prepare_and_reports_partial_precisely(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertLess(text.index("health-refresh"), text.index("overnight-prepare"))
        self.assertIn("batch_partial_requires_follow_up", text)
        self.assertIn("trend_evidence_shadow_failures", text)

    def test_overnight_script_runs_the_checked_out_module_not_a_global_console_script(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn("python3 -m content_platform", text)
        self.assertNotIn('"$bin" --config', text)

    def test_overnight_script_requires_provider_smoke_before_creating_content_jobs(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertLess(text.index("smoke_provider.sh"), text.index("performance-cycle"))
        self.assertIn("provider_preflight_failed", text)

    def test_provider_smoke_can_use_the_active_hermes_model_without_pinning(self):
        text = Path("scripts/smoke_provider.sh").read_text(encoding="utf-8")
        self.assertIn('route=()', text)
        self.assertIn('"${route[@]}"', text)
        self.assertNotIn("hermes_provider and hermes_model must be configured", text)
        self.assertIn('text.startswith("```")', text)

    def test_overnight_script_writes_acceptance_summary_after_batch_execution(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn("overnight-sync-state", text)
        self.assertIn("acceptance_summary.json", text)
        self.assertIn("overnight-acceptance --result", text)
        self.assertIn("acceptance_report.json", text)

    def test_overnight_script_has_a_bounded_configurable_catchup_window(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn('OVERNIGHT_ADMISSION_WINDOW_MINUTES:-60', text)
        self.assertIn('missed_overnight_admission_window', text)

    def test_overnight_script_reports_non_admitted_capacity_without_claiming_completion(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn("capacity_blocked|blocked", text)
        self.assertIn("batch_not_admitted_", text)

    def test_overnight_systemd_service_sets_home_and_private_notification_environment(self):
        text = Path("systemd/hermes-content-platform-overnight.service").read_text(encoding="utf-8")

        self.assertIn("Environment=HOME=%h", text)
        self.assertIn("Environment=HERMES_PLATFORM_SCRAPER=%h/.hermes/scripts/platform_scraper.py", text)
        self.assertIn("secrets/notifications.env", text)

    def test_overnight_supervisor_is_independent_and_never_republishes(self):
        script = Path("scripts/run_overnight_supervisor.sh").read_text(encoding="utf-8")
        service = Path("systemd/hermes-content-platform-overnight-supervisor.service").read_text(encoding="utf-8")
        timer = Path("systemd/hermes-content-platform-overnight-supervisor.timer").read_text(encoding="utf-8")

        self.assertIn("overnight-supervise", script)
        self.assertIn("overnight-sync-state", script)
        self.assertLess(script.index("overnight-sync-state"), script.index('if [[ "$status" != "stale" ]]'))
        self.assertNotIn("overnight-run", script)
        self.assertIn("recovery_pending", script)
        self.assertIn("run_overnight_supervisor.sh", service)
        self.assertIn("*:0/3", timer)

    def test_stale_plan_keeps_recovery_pending_without_running_or_entering_delivery(self):
        script = Path("scripts/run_overnight_supervisor.sh").read_text(encoding="utf-8")

        self.assertIn("overnight-sync-state", script)
        self.assertIn("overnight-supervise", script)
        self.assertIn("recover", script)
        self.assertIn("recovery_pending", script)
        self.assertIn('notify "action_required"', script)
        self.assertNotIn("overnight-run", script)
        self.assertNotIn("automatic_recovery_started", script)
        self.assertNotIn("automatic_recovery_completed", script)

    def test_overnight_script_writes_a_failed_outcome_before_notifying_on_unhandled_error(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn("batch_failed_before_result", text)
        self.assertIn("overnight-sync-state", text)

    def test_overnight_script_verifies_release_metadata_before_any_task(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")

        resolve = text.index('release_root=$(readlink -f -- "$root")')
        verify = text.index("--verify-metadata")
        mkdir = text.index("mkdir -p")
        self.assertLess(resolve, verify)
        self.assertLess(verify, mkdir)
        self.assertIn('[[ -n "$release_root" && -d "$release_root" ]]', text)
        self.assertIn('metadata_path="${CONTENT_PLATFORM_RELEASE_METADATA:-$release_root/release-metadata.json}"', text)
        self.assertIn("runtime_release_audit.py", text)
        self.assertIn('CONTENT_PLATFORM_CODE_ROOT="$release_root"', text)
        self.assertIn('--release-root "$release_root"', text)
        self.assertNotIn('"$root/scripts/', text)
        self.assertIn('PYTHONPATH="$release_root', text)
        self.assertIn('smoke_provider.sh" "$config_path', text)

    def test_release_deploy_and_overnight_share_runtime_release_lock(self):
        overnight = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")
        deploy = Path("scripts/deploy_release.py").read_text(encoding="utf-8")

        self.assertIn("runtime-release.lock", overnight)
        self.assertIn("flock -s", overnight)
        self.assertIn("runtime-release.lock", deploy)
        self.assertIn("LOCK_EX", deploy)

    def test_overnight_batch_uses_an_exclusive_worker_lock(self):
        text = Path("scripts/run_overnight_batch.sh").read_text(encoding="utf-8")
        self.assertIn("overnight-batch.lock", text)
        self.assertIn("flock -n", text)
        self.assertNotIn("flock -s 9", text)

    def test_overnight_supervisor_gates_recovery_on_owner_proof(self):
        text = Path("scripts/run_overnight_supervisor.sh").read_text(encoding="utf-8")
        self.assertIn("recovery_authorized", text)
        self.assertIn('[[ "$recovery_authorized" != "true" ]]', text)
        self.assertLess(text.index('[[ "$recovery_authorized" != "true" ]]'), text.index(" recover >"))

    def test_overnight_scripts_invoke_the_independent_chinese_reporter_sidecar(self):
        for name in ("scripts/run_overnight_batch.sh", "scripts/run_overnight_supervisor.sh"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertIn("run_overnight_reporter.sh", text)
            self.assertIn("reporter.cursor.json", text)
        sidecar = Path("scripts/run_overnight_reporter.sh").read_text(encoding="utf-8")
        self.assertIn("overnight_reporter.py", sidecar)
        self.assertIn("flock -n 8", sidecar)
        self.assertIn("notify_hermes_progress.sh", sidecar)
        self.assertIn("ChineseReporter", Path("scripts/overnight_reporter.py").read_text(encoding="utf-8"))
        service = Path("systemd/hermes-content-platform-overnight-reporter.service").read_text(encoding="utf-8")
        timer = Path("systemd/hermes-content-platform-overnight-reporter.timer").read_text(encoding="utf-8")
        self.assertIn("run_overnight_reporter.sh", service)
        self.assertIn("notifications.env", service)
        self.assertIn("*:0/3", timer)

    def test_overnight_supervisor_resolves_canonical_release_and_verifies_before_state_writes(self):
        text = Path("scripts/run_overnight_supervisor.sh").read_text(encoding="utf-8")

        resolve = text.index('release_root=$(readlink -f -- "$root")')
        verify = text.index("--verify-metadata")
        state_check = text.index('[[ -f "$state" ]]')
        self.assertLess(resolve, verify)
        self.assertLess(verify, state_check)
        self.assertIn('CONTENT_PLATFORM_CODE_ROOT="$release_root"', text)
        self.assertIn("flock -s", text)
        self.assertIn("runtime-release.lock", text)
        self.assertNotIn('"$root/scripts/', text)
        self.assertIn('PYTHONPATH="$release_root', text)

    def test_batch_and_supervisor_verify_with_the_stable_signing_key(self):
        for name in ("scripts/run_overnight_batch.sh", "scripts/run_overnight_supervisor.sh"):
            text = Path(name).read_text(encoding="utf-8")
            self.assertIn('signing_key="${CONTENT_PLATFORM_RELEASE_SIGNING_KEY:-$secrets_root/release-signing.key}"', text)
            self.assertIn('--signing-key "$signing_key"', text)
            self.assertIn('trusted_secrets_root="$secrets_root"', text)
            self.assertIn('--trusted-secrets-root "$trusted_secrets_root"', text)

    def test_deploy_cli_requires_explicit_signing_key_or_secrets_root(self):
        text = Path("scripts/deploy_release.py").read_text(encoding="utf-8")

        self.assertIn("--signing-key", text)
        self.assertIn("--secrets-root", text)
        self.assertIn("release-signing.key", text)

    def test_overnight_units_use_current_code_and_stable_runtime_roots_consistently(self):
        batch = Path("systemd/hermes-content-platform-overnight.service").read_text(encoding="utf-8")
        supervisor = Path("systemd/hermes-content-platform-overnight-supervisor.service").read_text(encoding="utf-8")

        for text, script in ((batch, "run_overnight_batch.sh"), (supervisor, "run_overnight_supervisor.sh")):
            self.assertIn("Environment=CONTENT_PLATFORM_HOME=%h/.ai-self-media-tools-current", text)
            self.assertIn("Environment=CONTENT_PLATFORM_DATA_DIR=%h/.ai-self-media-tools/data", text)
            self.assertIn("Environment=CONTENT_PLATFORM_SECRETS_DIR=%h/.ai-self-media-tools/secrets", text)
            self.assertIn("Environment=CONTENT_PLATFORM_CONFIG=%h/.ai-self-media-tools/config.json", text)
            self.assertIn(f"ExecStart=/bin/bash %h/.ai-self-media-tools-current/scripts/{script}", text)
            self.assertNotIn("ExecStart=/bin/bash %h/.ai-self-media-tools/scripts/", text)

    def test_background_systemd_services_use_notification_wrappers(self):
        growth = Path("systemd/hermes-content-platform-growth-cycle.service").read_text(encoding="utf-8")
        wechat = Path("systemd/ai-self-media-wechat-metrics.service").read_text(encoding="utf-8")

        self.assertIn("run_growth_cycle.sh", growth)
        self.assertIn("secrets/notifications.env", growth)
        self.assertIn("run_wechat_metrics_refresh.sh", wechat)
        self.assertIn("secrets/notifications.env", wechat)

    def test_wechat_metrics_timer_retains_dedicated_schedule(self):
        path = Path("systemd/ai-self-media-wechat-metrics.timer")
        self.assertTrue(path.is_file(), "release must retain the installed WeChat metrics timer")
        text = path.read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 07:20:00 Asia/Shanghai", text)
        self.assertIn("Unit=ai-self-media-wechat-metrics.service", text)
        self.assertIn("Persistent=true", text)
        from scripts.deploy_release import _systemd_unit_paths
        _, timers = _systemd_unit_paths(Path.cwd())
        self.assertIn(path.name, [timer.name for timer in timers])

    def test_overnight_monitor_loads_the_private_notification_environment(self):
        text = Path("scripts/create_hermes_overnight_monitor.py").read_text(encoding="utf-8")

        self.assertIn("notifications.env", text)
        self.assertIn("AI_SELF_MEDIA_TELEGRAM_TARGET", text)

    def test_overnight_monitor_reports_a_stalled_batch_from_durable_state(self):
        text = Path("scripts/monitor_overnight_batch.sh").read_text(encoding="utf-8")

        self.assertIn("waiting_for_checkpoint", text)
        self.assertIn("over nine minutes", text)

    def test_overnight_monitor_does_not_register_a_duplicate_named_job(self):
        text = Path("scripts/create_hermes_overnight_monitor.py").read_text(encoding="utf-8")

        self.assertIn('"hermes", "cron", "list"', text)
        self.assertIn("AI自媒体夜间运行监控", text)

    def test_auto_service_refreshes_growth_strategy_before_auto_run(self):
        text = Path("systemd/hermes-content-platform.service").read_text(encoding="utf-8")

        self.assertLess(text.index("performance-cycle"), text.index(" auto "))

    def test_kuaishou_video_proxy_args_use_configured_cn_proxy(self):
        from scripts import validate_kuaishou_video as validator

        self.assertEqual(validator._curl_proxy_args("socks5://127.0.0.1:2080"), ["--socks5", "127.0.0.1:2080"])
        self.assertEqual(validator._curl_proxy_args("socks5h://127.0.0.1:2080"), ["--socks5-hostname", "127.0.0.1:2080"])


if __name__ == "__main__":
    unittest.main()
