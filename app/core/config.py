from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = 'postgresql+asyncpg://eris:eris_secret_2026@postgres:5432/eris'
    REDIS_URL: str = 'redis://:redis_secret_2026@redis:6379/0'
    SECRET_KEY: str = 'change_this_secret_key_in_production'
    OPENROUTER_API_KEY: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    ENV: str = 'production'

    class Config:
        env_file = '.env'

settings = Settings()
