"""Attach a same-lane breakdown (viral_breakdown) to ready overnight tasks.

Generation requires a breakdown observed within 24 h on the task's own
platform.  Only platforms with a typed public full-text collector get one;
other ready rows are blocked with the reason instead of failing later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _juejin(items: list[dict[str, Any]], out_dir: Path) -> list[dict[str, Any]]:
    from .juejin_native_article import collect_samples

    hot = [item for item in items if item.get("source") == "juejin"]
    return collect_samples(hot, out_dir / "juejin")


COLLECTORS = {"juejin": _juejin}


def attach_breakdowns(prepared: dict[str, Any], items: list[dict[str, Any]], out_dir: str | Path) -> dict[str, Any]:
    from .task_source_inputs import _observed_strategy_inputs

    cache: dict[str, Any] = {}
    for task in prepared.get("tasks") or []:
        platform = str(task.get("platform") or "")
        if task.get("state") != "ready_for_plan":
            continue
        if platform not in cache:
            collector = COLLECTORS.get(platform)
            try:
                if collector is None:
                    raise ValueError("no typed public same-lane collector for this platform")
                rows = collector(items, Path(out_dir))
                cache[platform] = _observed_strategy_inputs(platform, {"items": rows})
            except Exception as exc:  # One platform's benchmark must not abort the batch.
                cache[platform] = {"error": f"same-lane breakdown unavailable: {str(exc)[:200]}"}
        strategy = cache[platform]
        if "error" in strategy:
            task.update(state="blocked", reason=strategy["error"])
        else:
            task.setdefault("brief", {}).update(strategy)
    return prepared
