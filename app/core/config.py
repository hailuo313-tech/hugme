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
    # D6-4 / V001-P0-4：notification_tasks → Telegram 真发送 worker。
    # False 时不注册 scheduler；生产打开前须确认 TELEGRAM_BOT_TOKEN 与话术合规。
    NOTIFICATION_SENDER_ENABLED: bool = False
    NOTIFICATION_SENDER_POLL_SECONDS: int = 20
    NOTIFICATION_SENDER_SCHEDULER_MAX_INSTANCES: int = 1
    # D3-3: 记忆写入开关 + LLM 评分模型 + importance 阈值。
    # MEMORY_WRITE_ENABLED=False 时 maybe_write_memory() 直接 noop（用于演示 / 降级）。
    MEMORY_WRITE_ENABLED: bool = True
    # 使用 fallback 模型（gpt-4o-mini）做结构化 JSON 评分，比主模型稳定；
    # 留空时 llm.chat 自走主备路由。
    LLM_MEMORY_MODEL: str = 'openai/gpt-4o-mini'
    # 评分 ≥ 此阈值才入 memories 表；默认 5（preference/goal 起步）。
    MEMORY_IMPORTANCE_THRESHOLD: int = 5
    # D4-2：是否在 generate_reply 主路径调用 memory_retriever 填充 L6_MEMORY。
    # 关闭时与旧行为一致（不占 embed / SQL）；生产需 OPENAI_API_KEY 才能语义检索。
    MEMORY_RETRIEVE_IN_PROMPT: bool = False
    # D4-2：注入条数与候选池，与 app/api/memories.py MemoryRetrieveRequest 默认对齐。
    MEMORY_RETRIEVE_TOP_K: int = 10
    MEMORY_RETRIEVE_K_CANDIDATES: int = 30
    # D4-2 任务卡 9：注入 L6 前过滤与当前用户句互斥的记忆（默认仅规则，不调 LLM）。
    MEMORY_CONSISTENCY_ENABLED: bool = True
    # >0 时预留「轻量 LLM 二次校验」上限（当前未实现，保持 0 即零额外 completion）。
    MEMORY_CONSISTENCY_LLM_MAX_OUTPUT_TOKENS: int = 0
    # D4-3 / D4-4：loneliness_updater（须显式声明，单测 monkeypatch 与 RUNBOOK 对齐）
    LONELINESS_REFRESH_ENABLED: bool = True
    LONELINESS_LOOKBACK_DAYS: int = 30
    LONELINESS_MEMORY_CAP: int = 40
    LONELINESS_PER_MEMORY_CLAMP: float = 12.0
    LONELINESS_GLOBAL_DELTA_CLAMP: float = 20.0
    LONELINESS_DECAY_FACTOR: float = 0.08
    LONELINESS_BASELINE: float = 35.0
    LONELINESS_MIN_UPDATE_DELTA: float = 0.05
    LONELINESS_UTTERANCE_ENABLED: bool = True
    LONELINESS_UTTERANCE_MAX_DELTA: float = 10.0
    # D4-4 剩余：画像分 Worker（initiation_score + min-only trigger_threshold）。
    # False 时不启动 scheduler；与 embedding / silent_reactivation 模式一致。
    SCORE_WORKER_ENABLED: bool = False
    SCORE_WORKER_POLL_SECONDS: int = 120
    SCORE_INITIATION_LOOKBACK_DAYS: int = 7
    SCORE_INITIATION_CAP_MESSAGES: int = 40
    SCORE_PROFILE_MIN_UPDATE_DELTA: float = 0.05
    # trigger_threshold：与 scripts/init.sql 默认 65 对齐；pivot 与 LONELINESS_BASELINE 一致。
    TRIGGER_THRESHOLD_BASE: float = 65.0
    TRIGGER_THRESHOLD_PIVOT: float = 35.0
    TRIGGER_THRESHOLD_K: float = 0.15
    TRIGGER_THRESHOLD_FLOOR: float = 50.0
    TRIGGER_THRESHOLD_CEIL: float = 82.0
    # D3-4: 异步 embedding worker，把 memories.embedding 从 NULL 填满。
    # 关闭时 worker scheduler 不启动；OPENAI_API_KEY 没配也会自动跳过。
    EMBEDDING_WORKER_ENABLED: bool = True
    # 直连 OpenAI（而不是 OpenRouter）的 API key；专给 embeddings 用。
    OPENAI_API_KEY: Optional[str] = None
    # OpenAI embedding 模型；1536 维需与 memories.embedding vector(1536) 对齐。
    EMBEDDING_MODEL: str = 'text-embedding-3-small'
    # 一次 tick 拉多少条 NULL embedding 行（OpenAI 单次最多 ~2048，但越大越容易超时）。
    EMBEDDING_BATCH_SIZE: int = 32
    # 多久跑一次 tick；最低 5 秒。
    EMBEDDING_POLL_SECONDS: int = 30
    # D8-2b：OpenAI embeddings HTTP 超时（秒）；过大拉长单次 tick 占用 advisory lock 时间。
    EMBEDDING_HTTP_TIMEOUT_SECONDS: float = 20.0
    # D8-2b：APScheduler 单进程内 embedding tick 最大并发实例；>1 会叠多个 tick，仍受 DB advisory lock 串行，通常无收益且徒增日志噪声。默认 1。
    EMBEDDING_SCHEDULER_MAX_INSTANCES: int = 1
    # D8-2b：画像分 worker 调度 max_instances（与 embedding 同理，默认 1）。
    SCORE_WORKER_SCHEDULER_MAX_INSTANCES: int = 1
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
