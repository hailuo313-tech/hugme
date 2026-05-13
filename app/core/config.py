from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str = 'postgresql+asyncpg://eris:eris_secret_2026@postgres:5432/eris'
    REDIS_URL: str = 'redis://:redis_secret_2026@redis:6379/0'
    SECRET_KEY: str = 'change_this_secret_key_in_production'
    OPENROUTER_API_KEY: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
    # 默认 False（失败抛 LLMOrchestratorError，调用方决定如何兜底）；
    # 设为 True 用于演示 / 降级 / 离线开发。
    LLM_ECHO_FALLBACK: bool = False
    # D6-3: 静默重激活总开关。默认 False；设为 True 时 admin 的扫描端点才会真的查 DB / 写任务。
    SILENT_REACTIVATION_ENABLED: bool = False
    # D6-3 调度：crontab 形式（分 时 日 月 周，UTC）。默认每天 UTC 02:00（北京 10:00 / PT 18:00）。
    # 仅在 SILENT_REACTIVATION_ENABLED=True 时才注册定时任务。
    SILENT_REACTIVATION_CRON: str = '0 2 * * *'
    ENV: str = 'production'

    class Config:
        env_file = '.env'

settings = Settings()
