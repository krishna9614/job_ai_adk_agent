from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(..., alias="DATABASE_URL")

    # Supabase Auth (public/anon key only; the service-role key is never used here).
    supabase_url: str | None = Field(None, alias="SUPABASE_URL")
    supabase_anon_key: str | None = Field(None, alias="SUPABASE_ANON_KEY")

    api_host: str = Field("127.0.0.1", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
