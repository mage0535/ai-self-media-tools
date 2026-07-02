import copy
from pathlib import Path

from .aitoearn import AitoEarnClient
from .pipeline import Pipeline
from .publishers import read_setting
from .store import Store


PLATFORM_ALIASES = {
    "xhs": "xiaohongshu",
    "wxSph": "shipinhao",
    "KWAI": "kuaishou",
}


def _platform_name(platform):
    return PLATFORM_ALIASES.get(platform, platform)


class TaskMarketRunner:
    def __init__(self, db_path, config):
        self.db_path = db_path
        self.config = config or {}

    def _env_config(self, env):
        task_cfg = self.config.get("task_market", {})
        envs = task_cfg.get("environments", {})
        if env in envs:
            return envs[env]
        defaults = {
            "cn": {
                "base_url": "https://aitoearn.cn/api/unified/mcp",
                "api_key_env": "AITOEARN_API_KEY",
                "env_file": "",
            },
            "intl": {
                "base_url": "https://aitoearn.ai/api/unified/mcp",
                "api_key_env": "AITOEARN_INTL_API_KEY",
                "env_file": "",
            },
        }
        return defaults[env]

    def _client(self, env):
        cfg = self._env_config(env)
        key = read_setting(cfg.get("api_key_env", ""), cfg.get("env_file", ""), cfg.get("api_key", ""))
        if not key:
            raise ValueError(f"missing environment variable: {cfg.get('api_key_env', '')}")
        return AitoEarnClient(cfg["base_url"], key)

    def _policy(self):
        task_cfg = self.config.get("task_market", {})
        return {
            "allowed_types": set(task_cfg.get("allowed_types", ["promotion"])),
            "auto_platforms": set(task_cfg.get("auto_platforms", ["bilibili"])),
            "min_reward": float(task_cfg.get("min_reward", 0)),
        }

    def scan(self, env, page_size=20):
        client = self._client(env)
        policy = self._policy()
        payload = client.list_task_market(page_size=page_size)
        tasks = []
        summary = {"total": 0, "eligible": 0, "manual": 0, "blocked": 0}
        for item in payload["tasks"]:
            summary["total"] += 1
            platform = next(iter(item.get("platforms", [])), "")
            task_type = item.get("type", "")
            reward = float(item.get("reward", "0") or 0)
            reason = ""
            decision = "blocked"
            if item.get("status") != "active":
                reason = "inactive"
            elif item.get("current_recruits", 0) >= item.get("max_recruits", 1_000_000):
                reason = "full"
            elif task_type not in policy["allowed_types"]:
                decision = "manual"
                reason = "type_not_auto"
            elif platform not in policy["auto_platforms"]:
                decision = "manual"
                reason = "platform_not_auto"
            elif reward < policy["min_reward"]:
                decision = "manual"
                reason = "reward_below_floor"
            else:
                decision = "eligible"
                reason = "auto_promotion"
            summary[decision] += 1
            tasks.append({**item, "platform": platform, "decision": decision, "reason": reason})
        return {"env": env, "summary": summary, "tasks": tasks}

    def auto_run(self, env, page_size=20):
        try:
            client = self._client(env)
        except ValueError as exc:
            return {"accepted": 0, "completed": 0, "manual": 0, "failed": 0, "reason": str(exc)}
        scan = self.scan(env, page_size)
        result = {"accepted": 0, "completed": 0, "manual": 0, "failed": 0}
        publishers = self.config.get("publishers", {}).get("platforms", {})
        task_config = copy.deepcopy(self.config)
        task_config.setdefault("delivery", {})
        task_config["delivery"]["auto_stage_review_required"] = False
        task_publishers = self.config.get("task_market", {}).get("platform_publishers", {})
        for task in scan["tasks"]:
            if task["decision"] != "eligible":
                result["manual"] += 1
                continue
            platform = _platform_name(task["platform"])
            publisher_cfg = publishers.get(platform, {})
            account_id = publisher_cfg.get("account_id", "")
            accepted = client.accept_task(task["task_id"], account_id=account_id)
            user_task_id = accepted.get("user_task_id", "")
            if not user_task_id:
                result["failed"] += 1
                continue
            result["accepted"] += 1
            if platform in task_publishers:
                task_config.setdefault("publishers", {}).setdefault("platforms", {})[platform] = copy.deepcopy(task_publishers[platform])
            store = Store(Path(self.db_path))
            store.init()
            pipeline = Pipeline(store, task_config)
            job = pipeline.create(task.get("title", "AiToEarn promotion"), [platform], {"source": "aitoearn", "task_id": task["task_id"]})
            pipeline.run(job["id"])
            pipeline.approve(job["id"], "task-market-auto", f"userTaskId={user_task_id}")
            delivered = pipeline.publish(job["id"])
            delivery = next((row for row in delivered["deliveries"] if row["platform"] == platform), None)
            if not delivery or delivery["status"] == "handoff_pending":
                result["manual"] += 1
                continue
            work_link = delivery.get("error", "")
            publish_record_id = delivery.get("external_id", "")
            client.submit_task(user_task_id, work_link=work_link, publish_record_id=publish_record_id)
            result["completed"] += 1
        return result
