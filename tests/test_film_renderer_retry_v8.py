import asyncio

from scripts.film_renderer import execute_shot_sequence


def test_shot_sequence_retries_current_shot_and_stops_before_later_shots():
    calls = []

    async def render(name, duration, attempt):
        calls.append((name, attempt))
        if name == "shot_02A":
            return None
        return {"name": name, "renderer": "playwright-video", "reused": False}

    result = asyncio.run(
        execute_shot_sequence(
            [("shot_01A", 2.0), ("shot_02A", 2.0), ("shot_03A", 2.0)],
            render,
            max_attempts=2,
        )
    )

    assert result["passed"] is False
    assert result["failed_shot"] == "shot_02A"
    assert calls == [("shot_01A", 1), ("shot_02A", 1), ("shot_02A", 2)]
    assert all(name != "shot_03A" for name, _attempt in calls)


def test_shot_sequence_continues_only_after_local_retry_succeeds():
    calls = []

    async def render(name, duration, attempt):
        calls.append((name, attempt))
        if name == "shot_02A" and attempt == 1:
            return None
        return {"name": name, "renderer": "playwright-video", "reused": False}

    result = asyncio.run(
        execute_shot_sequence(
            [("shot_01A", 2.0), ("shot_02A", 2.0), ("shot_03A", 2.0)],
            render,
            max_attempts=2,
        )
    )

    assert result["passed"] is True
    assert result["failed_shot"] == ""
    assert calls == [("shot_01A", 1), ("shot_02A", 1), ("shot_02A", 2), ("shot_03A", 1)]
    second = next(row for row in result["records"] if row["name"] == "shot_02A")
    assert second["attempt_count"] == 2


def test_shot_sequence_rejects_invalid_retry_budget():
    async def render(name, duration, attempt):
        return {"name": name}

    try:
        asyncio.run(execute_shot_sequence([("shot_01A", 1.0)], render, max_attempts=0))
    except ValueError as exc:
        assert "max_attempts" in str(exc)
    else:
        raise AssertionError("expected invalid retry budget")
