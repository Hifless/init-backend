from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    BOT_TOKEN: str
    WEBAPP_URL: str = ""
    DATABASE_URL: str
    SECRET_KEY: str = "change-me-in-production"
    ADMIN_TG_ID: int = 0
    DEBUG: bool = False
    OWNER_TG_ID: int = 0

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
