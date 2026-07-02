import json
import re
import urllib.request


def _extract_text(payload):
    if not isinstance(payload, dict):
        return str(payload)
    result = payload.get("result", {})
    content = result.get("content", [{}])
    if content:
        return content[0].get("text", "")
    error = payload.get("error")
    if error:
        return str(error)
    return ""


def _first(pattern, text):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _all(pattern, text):
    return [match.strip() for match in re.findall(pattern, text, re.MULTILINE)]


def _to_int(value, default=0):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _publish_record_id(text):
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("- id:"):
            return stripped.split(":", 1)[1].strip()
        if stripped.startswith("id:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _task_market_item(lines):
    item = {}
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("_id:"):
            item["task_id"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("title:"):
            item["title"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("type:"):
            item["type"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("reward:"):
            item["reward"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("status:"):
            item["status"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("currentRecruits:"):
            item["current_recruits"] = _to_int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("maxRecruits:"):
            item["max_recruits"] = _to_int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("- ") and len(stripped) > 2:
            value = stripped[2:].strip()
            if value in {
                "douyin",
                "xhs",
                "wxSph",
                "KWAI",
                "youtube",
                "wxGzh",
                "bilibili",
                "twitter",
                "tiktok",
                "facebook",
                "instagram",
                "threads",
                "pinterest",
                "linkedin",
                "google_business",
            }:
                item.setdefault("platforms", []).append(value)
    return item


def parse_task_market_text(text):
    items, current = [], []
    for line in str(text).splitlines():
        if line.startswith("- _id:") or line.startswith("  - _id:"):
            if current:
                items.append(_task_market_item(current))
            current = [line.replace("  ", "", 1)]
            continue
        if current:
            current.append(line)
    if current:
        items.append(_task_market_item(current))
    return [item for item in items if item.get("task_id")]


def parse_platform_metadata(text, platform):
    section = re.search(
        rf"(^|\n)- platform: {re.escape(platform)}\n(?P<body>.*?)(?=\n- platform: |\Z)",
        str(text),
        re.DOTALL,
    )
    body = section.group("body") if section else ""
    return {
        "platform": platform,
        "status": _first(r"^\s*status:\s*([^\n]+)", body),
        "publishPolicy": {
            "completionStrategy": _first(r"^\s*completionStrategy:\s*([^\n]+)", body),
        },
        "raw_text": body,
    }


class AitoEarnClient:
    def __init__(self, base_url, api_key):
        self.base_url = str(base_url).rstrip("/")
        self.api_key = api_key
        self._platform_cache = {}

    def call(self, method, arguments=None, timeout=30):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": method, "arguments": arguments or {}},
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "x-api-key": self.api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
        return json.loads(raw)

    def create_image_text_draft(self, **kwargs):
        payload = self.call("createImageTextDraft", kwargs, timeout=20)
        text = _extract_text(payload)
        return {"task_ids": _all(r"Task IDs?:?\s*([A-Za-z0-9_-]+)", text) or _all(r"\b([A-Za-z0-9_-]{20,})\b", text), "raw_text": text}

    def create_video_draft(self, **kwargs):
        payload = self.call("createVideoDraft", kwargs, timeout=20)
        text = _extract_text(payload)
        return {"task_ids": _all(r"Task IDs?:?\s*([A-Za-z0-9_-]+)", text) or _all(r"\b([A-Za-z0-9_-]{20,})\b", text), "raw_text": text}

    def get_draft_task_status(self, task_id):
        payload = self.call("getDraftTaskStatus", {"taskId": task_id}, timeout=15)
        text = _extract_text(payload)
        lowered = text.lower()
        status = "success" if "success" in lowered else "failed" if "failed" in lowered else "generating"
        return {
            "status": status,
            "draft_id": _first(r"draftId:\s*([A-Za-z0-9_-]+)", text),
            "urls": _all(r"(https?://[^\s]+)", text),
            "raw_text": text,
        }

    def list_channel_platforms(self):
        payload = self.call("listChannelPlatforms", {}, timeout=60)
        return _extract_text(payload)

    def get_platform_metadata(self, platform):
        platform = str(platform)
        if platform not in self._platform_cache:
            self._platform_cache[platform] = parse_platform_metadata(self.list_channel_platforms(), platform)
        return self._platform_cache[platform]

    def create_channel_publish_flow(self, payload):
        response = self.call("createChannelPublishFlow", payload, timeout=60)
        text = _extract_text(response)
        return {"flow_id": _first(r"flowId:\s*([A-Za-z0-9_-]+)", text), "raw_text": text}

    def get_channel_publish_record_by_flow_id(self, flow_id):
        payload = self.call("getChannelPublishRecordByFlowId", {"flowId": flow_id}, timeout=60)
        text = _extract_text(payload)
        return {
            "publish_record_id": _publish_record_id(text),
            "work_link": _first(r"workLink:\s*([^\n]+)", text),
            "status": _to_int(_first(r"status:\s*([-\d]+)", text), 0),
            "error": _first(r"errorMsg:\s*([^\n]+)", text),
            "raw_text": text,
        }

    def list_task_market(self, page_no=1, page_size=20, platform="", task_type=""):
        arguments = {"pageNo": int(page_no), "pageSize": int(page_size)}
        if platform:
            arguments["platform"] = platform
        if task_type:
            arguments["type"] = task_type
        payload = self.call("listTaskMarket", arguments, timeout=60)
        text = _extract_text(payload)
        return {"tasks": parse_task_market_text(text), "raw_text": text}

    def accept_task(self, task_id, account_id=""):
        arguments = {"taskId": task_id}
        if account_id:
            arguments["accountId"] = account_id
        payload = self.call("acceptTask", arguments)
        text = _extract_text(payload)
        return {"user_task_id": _first(r"userTaskId=([A-Za-z0-9_-]+)", text) or _first(r"userTaskId:\s*([A-Za-z0-9_-]+)", text), "raw_text": text}

    def submit_task(self, user_task_id, work_link="", publish_record_id=""):
        arguments = {"userTaskId": user_task_id}
        if publish_record_id:
            arguments["publishRecordId"] = publish_record_id
        elif work_link:
            arguments["workLink"] = work_link
        payload = self.call("submitTask", arguments)
        return {"raw_text": _extract_text(payload)}
