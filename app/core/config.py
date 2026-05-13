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
    # D3-3: 记忆写入开关 + LLM 评分模型 + importance 阈值。
    # MEMORY_WRITE_ENABLED=False 时 maybe_write_memory() 直接 noop（用于演示 / 降级）。
    MEMORY_WRITE_ENABLED: bool = True
    # 使用 fallback 模型（gpt-4o-mini）做结构化 JSON 评分，比主模型稳定；
    # 留空时 llm.chat 自走主备路由。
    LLM_MEMORY_MODEL: str = 'openai/gpt-4o-mini'
    # 评分 ≥ 此阈值才入 memories 表；默认 5（preference/goal 起步）。
    MEMORY_IMPORTANCE_THRESHOLD: int = 5
    # D6-1 / D6-2 Stripe（pydantic-settings 自动从环境变量读取，必须显式声明字段才生效）
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_SUCCESS_URL: str = 'https://hugme2.com/payment/success?session_id={CHECKOUT_SESSION_ID}'
    STRIPE_CANCEL_URL: str = 'https://hugme2.com/payment/cancel'
    ENV: str = 'production'

    class Config:
        env_file = '.env'

settings = Settings()
