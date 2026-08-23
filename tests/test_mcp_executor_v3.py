from content_platform.mcp_executor import invoke_mcp_tool


def test_mcp_executor_requires_allowlisted_server_and_returns_evidence():
    result = invoke_mcp_tool(
        "content-platform",
        "build_tool_selection_plan",
        {"platform": "douyin_ai"},
        allowlist={"content-platform": {"build_tool_selection_plan"}},
        client=lambda server, tool, arguments, timeout: {"server": server, "tool": tool, "args": arguments, "timeout": timeout},
    )
    assert result["status"] == "executed"
    assert result["output_contract"] == "mcp_result_v1"
    assert result["output_hash"].startswith("sha256:")


def test_mcp_executor_fails_closed_for_unallowlisted_tool():
    result = invoke_mcp_tool("tavily-mcp", "search", {}, allowlist={"content-platform": {"search"}}, client=lambda *_: {})
    assert result["status"] == "failed"
    assert result["reason"] == "mcp_tool_not_allowlisted"
