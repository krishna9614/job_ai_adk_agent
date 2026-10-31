from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_access_token, get_current_user
from app.models import User

router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
) -> ChatResponse:
    # Imported lazily so the REST API does not require ADK/Gemini at import time.
    from app.services.agent_service import run_chat

    session_id, reply = await run_chat(
        user_id=str(user.id),
        access_token=access_token,
        message=body.message,
        session_id=body.session_id,
    )
    return ChatResponse(session_id=session_id, reply=reply)
