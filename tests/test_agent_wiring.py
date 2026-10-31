from types import SimpleNamespace

from job_ai_agent.agent import (
    ACCESS_TOKEN_STATE_KEY,
    AGENT_PROFILE_TOOLS,
    profile_mcp_headers,
    profile_toolset,
)


def test_agent_only_gets_read_tool():
    assert AGENT_PROFILE_TOOLS == ["get_user_profile"]
    assert profile_toolset.tool_filter == ["get_user_profile"]


def test_headers_forward_callers_token():
    ctx = SimpleNamespace(state={ACCESS_TOKEN_STATE_KEY: "tok"})
    assert profile_mcp_headers(ctx) == {"Authorization": "Bearer tok"}
    assert profile_mcp_headers(SimpleNamespace(state={})) == {}
    assert profile_mcp_headers(None) == {}
