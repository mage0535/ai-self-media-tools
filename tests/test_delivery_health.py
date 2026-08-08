import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from content_platform.delivery_health import delivery_health_decision


class DeliveryHealthTests(unittest.TestCase):
    def test_state_file_blocks_douyin_account_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "health.json"
            state_file.write_text(
                json.dumps(
                    {
                        "channels": {
                            "douyin": {
                                "classification": {
                                    "state": "blocked_account_health",
                                    "can_publish_now": False,
                                    "reason": "health score is insufficient",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            decision = delivery_health_decision("douyin", {"delivery_health": {"enabled": True, "state_file": str(state_file)}})

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "blocked_account_health")
        self.assertIn("health score", decision.error())

    def test_env_health_file_overrides_configured_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "configured.json"
            override = Path(tmp) / "override.json"
            configured.write_text(json.dumps({"channels": {"douyin": {"classification": {"state": "usable", "can_publish_now": True}}}}), encoding="utf-8")
            override.write_text(
                json.dumps(
                    {
                        "channels": {
                            "douyin": {
                                "classification": {
                                    "state": "blocked_account_health",
                                    "can_publish_now": False,
                                    "reason": "env override block",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CONTENT_PLATFORM_DELIVERY_HEALTH_FILE": str(override)}):
                decision = delivery_health_decision("douyin", {"delivery_health": {"enabled": True, "state_file": str(configured)}})

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "blocked_account_health")

    def test_default_state_file_is_read_from_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "delivery_health_state.json").write_text(
                json.dumps(
                    {
                        "platforms": {
                            "wechat": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "require_postcheck": True,
                                "reason": "refreshed",
                                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            decision = delivery_health_decision("wechat", {"data_dir": str(data_dir), "delivery_health": {"enabled": True}})

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "usable_with_postcheck_required")
        self.assertTrue(decision.require_postcheck)

    def test_state_file_overrides_static_platform_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "delivery_health_state.json").write_text(
                json.dumps(
                    {
                        "platforms": {
                            "kuaishou": {
                                "state": "auth_required",
                                "can_publish_now": False,
                                "reason": "fresh probe failed",
                                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            decision = delivery_health_decision(
                "kuaishou",
                {
                    "data_dir": str(data_dir),
                    "delivery_health": {
                        "enabled": True,
                        "platforms": {
                            "kuaishou": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "reason": "stale config",
                            }
                        },
                    },
                },
            )

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "auth_required")

    def test_stale_state_file_blocks_instead_of_falling_back_to_static_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            data_dir.mkdir()
            stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
            (data_dir / "delivery_health_state.json").write_text(
                json.dumps(
                    {
                        "platforms": {
                            "kuaishou": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "require_postcheck": True,
                                "reason": "old success",
                                "checked_at": stale,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            decision = delivery_health_decision(
                "kuaishou",
                {
                    "data_dir": str(data_dir),
                    "delivery_health": {
                        "enabled": True,
                        "max_state_age_seconds": 60,
                        "platforms": {
                            "kuaishou": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "reason": "static fallback must not override stale probe",
                            }
                        },
                    },
                },
            )

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "insufficient_current_evidence")

    def test_usable_with_postcheck_allows_delivery_but_marks_postcheck(self):
        decision = delivery_health_decision(
            "kuaishou",
            {
                "delivery_health": {
                    "enabled": True,
                    "platforms": {
                        "kuaishou": {
                            "state": "usable_with_postcheck_required",
                            "can_publish_now": True,
                            "reason": "recent postcheck evidence exists",
                        }
                    },
                }
            },
        )

        self.assertTrue(decision.ok)
        self.assertTrue(decision.require_postcheck)

    def test_proxy_required_blocks_domestic_before_uploader(self):
        with patch.dict(os.environ, {}, clear=True):
            decision = delivery_health_decision(
                "kuaishou",
                {
                    "delivery_health": {
                        "enabled": True,
                        "require_proxy_by_region": True,
                        "platforms": {
                            "kuaishou": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "reason": "health evidence exists",
                            }
                        },
                    }
                },
            )

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "proxy_unavailable")

    def test_proxy_required_allows_domestic_when_cn_proxy_exists(self):
        with patch.dict(os.environ, {"CN_PROXY": "socks5://127.0.0.1:1080"}, clear=True):
            decision = delivery_health_decision(
                "kuaishou",
                {
                    "delivery_health": {
                        "enabled": True,
                        "require_proxy_by_region": True,
                        "platforms": {
                            "kuaishou": {
                                "state": "usable_with_postcheck_required",
                                "can_publish_now": True,
                                "reason": "health evidence exists",
                            }
                        },
                    }
                },
            )

        self.assertTrue(decision.ok)
        self.assertTrue(decision.require_postcheck)

    def test_unknown_domestic_route_blocks_when_policy_enabled(self):
        decision = delivery_health_decision(
            "zhihu",
            {
                "delivery_health": {"enabled": True, "block_unknown_domestic": True},
                "publishers": {"platforms": {}},
            },
        )

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "route_unverified")

    def test_unknown_domestic_route_blocks_by_default(self):
        decision = delivery_health_decision("wechat", {"delivery_health": {"enabled": True}})

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "route_unverified")

    def test_unknown_domestic_route_requires_explicit_exception_to_pass(self):
        decision = delivery_health_decision(
            "wechat",
            {"delivery_health": {"enabled": True, "allow_unknown_health": True}},
        )

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "unknown")

    def test_unknown_domestic_stage_is_allowed_without_live_health(self):
        decision = delivery_health_decision("wechat", {"delivery_health": {"enabled": True}}, action="stage")

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "unknown")

    def test_configured_domestic_route_still_requires_health_evidence(self):
        decision = delivery_health_decision(
            "douyin",
            {
                "delivery_health": {"enabled": True, "block_unknown_domestic": True},
                "publishers": {"platforms": {"douyin": {"type": "social-auto-upload"}}},
            },
        )

        self.assertFalse(decision.ok)
        self.assertEqual(decision.state, "route_unverified")

    def test_xiaohongshu_recovery_policy_requires_manual_handoff_for_publish(self):
        decision = delivery_health_decision(
            "xiaohongshu",
            {"delivery_health": {"enabled": True, "enforce_builtin_risk_policies": True}},
        )

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "manual_handoff_only")
        self.assertTrue(decision.require_postcheck)

    def test_xiaohongshu_recovery_policy_allows_stage_drafts(self):
        decision = delivery_health_decision(
            "xiaohongshu",
            {"delivery_health": {"enabled": True, "enforce_builtin_risk_policies": True}},
            action="stage",
        )

        self.assertTrue(decision.ok)
        self.assertEqual(decision.state, "manual_handoff_only")

    def test_douyin_and_shipinhao_are_manual_handoff_only(self):
        for platform in ["douyin", "douyin_pet", "douyin_ai", "shipinhao"]:
            with self.subTest(platform=platform):
                decision = delivery_health_decision(
                    platform,
                    {"delivery_health": {"enabled": True, "enforce_builtin_risk_policies": True}},
                )

                self.assertTrue(decision.ok)
                self.assertEqual(decision.state, "manual_handoff_only")
                self.assertTrue(decision.require_postcheck)

    def test_aitoearn_disabled_platform_health_blocks_draft_and_flow(self):
        for platform in ["youtube", "tiktok", "twitter", "x", "threads"]:
            for kind in ["aitoearn-draft", "aitoearn-intl", "aitoearn-flow"]:
                with self.subTest(platform=platform, kind=kind):
                    decision = delivery_health_decision(
                        platform,
                        {
                            "delivery_health": {"enabled": True, "enforce_builtin_risk_policies": True},
                            "publishers": {"platforms": {platform: {"type": kind, "account_id": "acct", "api_key": "secret"}}},
                        },
                    )

                    self.assertTrue(decision.ok)
                    self.assertEqual(decision.state, "manual_handoff_only")
                    self.assertIn("AiToEarn is disabled", decision.error())


if __name__ == "__main__":
    unittest.main()
