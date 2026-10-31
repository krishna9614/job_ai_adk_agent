"""JobAI root agent.

A single Google ADK ``LlmAgent`` backed by Gemini, connected to the User Profile
MCP server over streamable HTTP. The caller's Supabase access token is forwarded
to the MCP server per invocation, so the agent never chooses which user's data it
reads. Only read access is exposed: profile writes stay explicit REST actions.
"""

import logging
import os

from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

load_dotenv()

logger = logging.getLogger("jobai.agent")

MODEL = os.getenv("JOBAI_MODEL", "gemini-2.5-flash")
PROFILE_MCP_URL = os.getenv("PROFILE_MCP_URL", "http://127.0.0.1:8001/mcp")

# Session-state key holding the caller's access token (temp: => never persisted).
ACCESS_TOKEN_STATE_KEY = "temp:jobai_access_token"

# Read-only by design: create/update require explicit user action via the REST API.
AGENT_PROFILE_TOOLS = ["get_user_profile"]


def profile_mcp_headers(context: ReadonlyContext | None) -> dict[str, str]:
    token = context.state.get(ACCESS_TOKEN_STATE_KEY) if context is not None else None
    return {"Authorization": f"Bearer {token}"} if token else {}


profile_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=PROFILE_MCP_URL),
    tool_filter=AGENT_PROFILE_TOOLS,
    header_provider=profile_mcp_headers,
)

root_agent = LlmAgent(
    name="jobai_agent",
    model=MODEL,
    instruction=(
        "You are JobAI, a career assistant.\n"
        "- Use the `get_user_profile` tool to look up the signed-in user's profile "
        "when they ask about their own details.\n"
        "- You cannot create or change profiles. If the user wants to, tell them to "
        "use the profile page/API.\n"
        "- Never ask for or reveal passwords, tokens, or internal IDs.\n"
        "- Job search, matching, and recommendations are not available yet.\n"
        "Keep answers concise and friendly."
    ),
    tools=[profile_toolset],
)
