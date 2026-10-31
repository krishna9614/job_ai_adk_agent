"""Runs the single ADK agent for an authenticated user."""

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.core.errors import NotFoundError
from job_ai_agent.agent import ACCESS_TOKEN_STATE_KEY, root_agent

APP_NAME = "job_ai_agent"

_session_service = InMemorySessionService()
_runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)


async def run_chat(
    *, user_id: str, access_token: str, message: str, session_id: str | None
) -> tuple[str, str]:
    if session_id:
        # Sessions are scoped by user_id, so another user's session id is simply not found.
        session = await _session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if session is None:
            raise NotFoundError("Chat session not found")
    else:
        session = await _session_service.create_session(app_name=APP_NAME, user_id=user_id)

    reply: list[str] = []
    async for event in _runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        # temp: state lives only for this invocation and is never persisted.
        state_delta={ACCESS_TOKEN_STATE_KEY: access_token},
    ):
        if event.is_final_response() and event.content and event.content.parts:
            reply.extend(p.text for p in event.content.parts if p.text)
    return session.id, "".join(reply)
