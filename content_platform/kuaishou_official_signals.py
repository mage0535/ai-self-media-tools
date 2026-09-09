"""Read verified Kuaishou creator inspiration signals without publishing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _metric_number(value: str) -> int:
    raw = str(value or "").replace(",", "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(万)?", raw)
    if not match:
        return 0
    amount = float(match.group(1)) * (10000 if match.group(2) else 1)
    return int(amount)


def parse_kuaishou_creator_text(
    text: str,
    *,
    captured_at: str,
    source_url: str,
    snapshot_sha256: str,
) -> dict[str, Any]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    failures = []
    if urlparse(source_url).hostname != "cp.kuaishou.com":
        failures.append("kuaishou_creator_domain_required")
    if len(snapshot_sha256) != 64:
        failures.append("snapshot_sha256_missing")
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except ValueError:
        captured = datetime.now(timezone.utc)
        failures.append("captured_at_invalid")
    try:
        inspiration_start = lines.index("创作灵感") + 1
        activity_start = lines.index("激励活动")
    except ValueError:
        return {"passed": False, "failures": [*failures, "creator_sections_missing"], "matrix_row": {}}

    details = []
    index = inspiration_start
    while index < activity_start - 1:
        title, metadata = lines[index], lines[index + 1]
        match = re.search(r"(\d+(?:\.\d+)?万?)人参与", metadata)
        if title != "查看更多" and match:
            labels = [part.strip() for part in metadata.split("·")[1:] if part.strip()]
            details.append({"title": title, "participants": _metric_number(match.group(1)), "labels": labels, "rank": len(details) + 1})
            index += 2
        else:
            index += 1

    activities = []
    end = lines.index("精选", activity_start + 1) if "精选" in lines[activity_start + 1:] else len(lines)
    index = activity_start + 1
    while index < end - 1:
        title, metadata = lines[index], lines[index + 1]
        if title != "活动多多 奖励多多" and any(token in metadata for token in ("奖励", "热点创作", "发稿")):
            activities.append({"title": title, "labels": [part.strip() for part in metadata.split("·") if part.strip()]})
            index += 2
        else:
            index += 1
    if not details:
        failures.append("creator_inspiration_missing")
    row = {
        "platform": "kuaishou",
        "status": "backend_loaded",
        "signal_type": "official_creator_activity",
        "evidence_type": "official_keyword",
        "signals": [item["title"] for item in details],
        "signal_details": details,
        "activities": activities,
        "official_url": source_url,
        "final_url": source_url,
        "captured_at": captured.astimezone(timezone.utc).isoformat(),
        "expires_at": (captured.astimezone(timezone.utc) + timedelta(hours=24)).isoformat(),
        "evidence_sha256": snapshot_sha256,
        "raw_snapshot_sha256": snapshot_sha256,
        "collector": "kuaishou_creator_backend",
        "native_verified": False,
    }
    return {"passed": not failures, "failures": failures, "matrix_row": row if not failures else {}}


def creator_page_requires_login(text: str) -> bool:
    lowered = str(text or "").casefold()
    return any(token in lowered for token in ("扫码登录", "请登录", "立即登录", "验证码", "captcha"))


def parse_kuaishou_public_hot_rank(
    html: str,
    *,
    captured_at: str,
    source_url: str,
    snapshot_sha256: str,
) -> dict[str, Any]:
    failures = []
    parsed_url = urlparse(source_url)
    if parsed_url.hostname != "www.kuaishou.com" or parsed_url.path != "/brilliant":
        failures.append("kuaishou_public_rank_url_required")
    if len(snapshot_sha256) != 64:
        failures.append("snapshot_sha256_missing")
    try:
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
    except ValueError:
        captured = datetime.now(timezone.utc)
        failures.append("captured_at_invalid")
    details = []
    pattern = re.compile(r'"VisionHotRankItem:[^"]+":\{(.*?),"__typename":"VisionHotRankItem"\}', re.S)
    for match in pattern.finditer(str(html or "")):
        try:
            item = json.loads("{" + match.group(1) + "}")
        except json.JSONDecodeError:
            continue
        title = str(item.get("name") or item.get("id") or "").strip()
        if not title or not isinstance(item.get("rank"), int):
            continue
        photo_ids = (item.get("photoIds") or {}).get("json") if isinstance(item.get("photoIds"), dict) else []
        details.append({
            "title": title,
            "rank": int(item["rank"]),
            "hot_value": _metric_number(str(item.get("hotValue") or "")),
            "hot_value_text": str(item.get("hotValue") or ""),
            "tag_type": str(item.get("tagType") or ""),
            "photo_ids": [str(value) for value in (photo_ids or []) if str(value)],
        })
    deduped = {item["title"]: item for item in sorted(details, key=lambda value: value["rank"])}
    details = list(deduped.values())[:50]
    if not details:
        failures.append("public_hot_rank_missing")
    row = {
        "platform": "kuaishou",
        "status": "public_hot_rank_loaded",
        "signal_type": "official_public_hot_rank",
        "evidence_type": "official_public_hot_rank",
        "signals": [item["title"] for item in details],
        "signal_details": details,
        "activities": [],
        "official_url": source_url,
        "final_url": source_url,
        "captured_at": captured.astimezone(timezone.utc).isoformat(),
        "expires_at": (captured.astimezone(timezone.utc) + timedelta(hours=6)).isoformat(),
        "evidence_sha256": snapshot_sha256,
        "raw_snapshot_sha256": snapshot_sha256,
        "collector": "kuaishou_public_hot_rank",
        "official_reference_only": True,
        "native_verified": False,
        "associated_hotspot": {},
    }
    return {"passed": not failures, "failures": failures, "matrix_row": row if not failures else {}}


def collect_kuaishou_public_hot_rank(output_dir: str | Path, *, timeout: int = 30) -> tuple[dict[str, Any], dict[str, Any]]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    source_url = "https://www.kuaishou.com/brilliant"
    html_path = output / "brilliant.html"
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    request = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 ai-self-media-tools/1.0"})
    body = b""
    last_error = None
    attempts = 0
    for attempts in range(1, 3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            break
        except Exception as exc:
            last_error = exc
    if not body:
        return {}, {"source": "kuaishou:official_public_hot_rank", "status": "failed", "count": 0, "attempts": attempts, "error": f"{type(last_error).__name__}: {str(last_error)[:180]}"}
    html_path.write_bytes(body)
    snapshot_sha = hashlib.sha256(body).hexdigest()
    parsed = parse_kuaishou_public_hot_rank(body.decode("utf-8", errors="ignore"), captured_at=captured_at, source_url=source_url, snapshot_sha256=snapshot_sha)
    status = {
        "source": "kuaishou:official_public_hot_rank",
        "status": "ok" if parsed["passed"] else "contract_failed",
        "count": len((parsed.get("matrix_row") or {}).get("signals") or []),
        "attempts": attempts,
        "captured_at": captured_at,
        "final_url": source_url,
        "html_path": str(html_path),
        "snapshot_sha256": snapshot_sha,
        "failures": parsed["failures"],
    }
    return parsed.get("matrix_row") or {}, status


def collect_kuaishou_creator_signals(
    state_file: str | Path,
    output_dir: str | Path,
    *,
    timeout_ms: int = 45000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    state = Path(state_file)
    if not state.is_file():
        return {}, {"source": "kuaishou:official_creator", "status": "auth_state_missing", "count": 0}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    text_path, html_path, screenshot_path = output / "profile.txt", output / "profile.html", output / "profile.png"
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sync_playwright() as pw:
        executable = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
        options = {"headless": True}
        if executable:
            options["executable_path"] = executable
        browser = pw.chromium.launch(**options)
        context = browser.new_context(storage_state=str(state), viewport={"width": 1365, "height": 900}, locale="zh-CN")
        page = context.new_page()
        page.goto("https://cp.kuaishou.com/profile", wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(8000)
        body = page.locator("body").inner_text(timeout=8000)
        final_url = page.url
        text_path.write_text(body, encoding="utf-8")
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(screenshot_path), full_page=True)
        context.close()
        browser.close()
    lowered = body.casefold()
    if creator_page_requires_login(body):
        return {}, {"source": "kuaishou:official_creator", "status": "login_required_or_captcha", "count": 0, "final_url": final_url}
    snapshot_sha = hashlib.sha256(text_path.read_bytes()).hexdigest()
    parsed = parse_kuaishou_creator_text(body, captured_at=captured_at, source_url=final_url, snapshot_sha256=snapshot_sha)
    status = {
        "source": "kuaishou:official_creator",
        "status": "ok" if parsed["passed"] else "contract_failed",
        "count": len((parsed.get("matrix_row") or {}).get("signals") or []),
        "captured_at": captured_at,
        "final_url": final_url,
        "text_path": str(text_path),
        "html_path": str(html_path),
        "screenshot_path": str(screenshot_path),
        "snapshot_sha256": snapshot_sha,
        "failures": parsed["failures"],
    }
    return parsed.get("matrix_row") or {}, status


def upsert_official_signal_matrix(data_dir: str | Path, row: dict[str, Any], *, now: datetime | None = None) -> Path:
    current = now or datetime.now(timezone.utc)
    target = Path(data_dir) / "overnight" / current.astimezone(timezone.utc).date().isoformat() / "official-platform-signal-matrix-v3.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema": "official-platform-signal-matrix-v3", "platforms": []}
    if target.is_file() and not target.is_symlink():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            pass
    rows = [item for item in payload.get("platforms") or [] if isinstance(item, dict) and item.get("platform") != row.get("platform")]
    rows.append(dict(row))
    payload.update({"schema": "official-platform-signal-matrix-v3", "platforms": rows, "updated_at": current.isoformat()})
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
