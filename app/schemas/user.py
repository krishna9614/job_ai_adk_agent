import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    account_status: str
    onboarding_status: str
    onboarding_step: int
    email_verified_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
