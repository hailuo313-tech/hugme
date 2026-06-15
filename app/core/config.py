from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    DATABASE_URL: str = 'postgresql+asyncpg://eris:eris_secret_2026@postgres:5432/eris'
    DATABASE_MIGRATION_URL: Optional[str] = None
    DATABASE_READER_URL: Optional[str] = None
    REDIS_URL: str = 'redis://:redis_secret_2026@redis:6379/0'
    SECRET_KEY: str = 'change_this_secret_key_in_production'
    OPENROUTER_API_KEY: Optional[str] = None
    NOVITA_API_KEY: Optional[str] = None
    LLM_PROVIDER: str = "openrouter"
    LLM_API_BASE_URL: str = "https://api.novita.ai/openai/v1"
    LLM_PRIMARY_MODEL: str = "deepseek/deepseek-v3-0324"
    LLM_FALLBACK_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # 按用途分流：chat=用户回复+坐席 AI 草稿；aux=翻译/记忆评分/年龄抽取等
    LLM_CHAT_PROVIDER: str = "novita"
    LLM_CHAT_MODEL: str = "deepseek/deepseek-v3-0324"
    LLM_AUX_PROVIDER: str = "openrouter"
    LLM_AUX_MODEL: str = "openai/gpt-4o-mini"
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    # C-03 / W2 MTProto（Telethon Userbot）；W2 前可不启用运行时，但须在 .env 配齐占位
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_SESSION_FERNET_KEY: Optional[str] = None
    TELEGRAM_SESSION_STRINGS: Optional[str] = None
    TELEGRAM_SESSION_DIR: str = "./data/telegram_sessions"
    MTProto_ENABLED: bool = False
    TELEGRAM_DEVICE_MODEL: str = "ERIS"
    TELEGRAM_SYSTEM_VERSION: str = "1.0"
    PUBLIC_BASE_URL: str = "https://hugme2.com"
    APP_DOWNLOAD_URL: Optional[str] = None
    APP_DOWNLOAD_FUNNEL_MODE: str = "click_only"
    # 同一会话硬性限制：距上一条含链接的助手消息不足 N 分钟则不得再发链接
    APP_DOWNLOAD_LINK_COOLDOWN_MINUTES: int = 15
    APP_DOWNLOAD_CONVERSION_ENABLED: bool = True
    APP_DOWNLOAD_NURTURE_ENABLED: bool = True
    # 培育 v3：沉默三轮视频邀请（秒）
    APP_DOWNLOAD_NURTURE_ROUND1_SECONDS: int = 300
    APP_DOWNLOAD_NURTURE_ROUND2_SECONDS: int = 1800
    APP_DOWNLOAD_NURTURE_ROUND3_SECONDS: int = 86400
    NURTURE_ACCEPT_AUTO_CALL_ENABLED: bool = False
    # Legacy aliases (still read if NURTURE_IDLE not overridden)
    APP_DOWNLOAD_FIRST_IDLE_SECONDS: int = 180
    APP_DOWNLOAD_WARM_NO_CLICK_SECONDS: int = 60
    APP_DOWNLOAD_CLICK_NO_DOWNLOAD_SECONDS: int = 600
    APP_DOWNLOAD_SILENT_30M_SECONDS: int = 1800
    APP_DOWNLOAD_SILENT_24H_SECONDS: int = 86400
    MEDIA_UPLOAD_DIR: str = "/srv/eris-uploads"
    MEDIA_PUBLIC_PATH: str = "/uploads"

    @field_validator("TELEGRAM_API_ID", mode="before")
    @classmethod
    def _empty_api_id_to_none(cls, v: object) -> object:
        if v is None or v == "":
            return None
        return v
    # D2-2: 上游 LLM 失败时是否回退为 "echo: <user_text>"。
    # 默认 False（失败抛 LLMOrchestratorError，调用方决定如何兜底）；
    # 设为 True 用于演示 / 降级 / 离线开发。
    LLM_ECHO_FALLBACK: bool = False
    # 出站回复硬性字数上限（sanitize）；LLM 生成 token 上限（orchestrator chat）
    OUTBOUND_REPLY_MAX_CHARS: int = 120
    ORCHESTRATOR_CHAT_MAX_TOKENS: int = 160
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
    # 人工接管后坐席 N 秒未回复则 AI 自动接管（默认 10 分钟）。
    HUMAN_TAKEOVER_IDLE_SECONDS: int = 600
    HUMAN_TAKEOVER_RELEASE_WORKER_ENABLED: bool = True
    HUMAN_TAKEOVER_RELEASE_POLL_SECONDS: int = 60
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
    # Legacy env vars ignored: inbound content safety gate removed.
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
    # 关闭时 worker scheduler 不启动；embedding key 没配也会自动跳过。
    EMBEDDING_WORKER_ENABLED: bool = True
    # 专给 embeddings 用的 key/base_url；未设置 key 时兼容旧的 OPENAI_API_KEY。
    # OpenRouter embeddings 可设置：
    # EMBEDDING_API_BASE_URL=https://openrouter.ai/api/v1
    # EMBEDDING_MODEL=openai/text-embedding-3-small
    EMBEDDING_API_KEY: Optional[str] = None
    EMBEDDING_API_BASE_URL: str = "https://api.openai.com/v1"
    # 旧配置：OpenAI API key；也被 content safety moderation 复用。
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
    # POL-01：Policy Service（七条件自动建 handoff_task）；默认关，与 CONTENT_SAFETY 一致生产显式打开。
    POLICY_SERVICE_ENABLED: bool = False
    POLICY_RISK_SCORE_THRESHOLD: int = 75
    POLICY_LONELINESS_THRESHOLD: float = 82.0
    POLICY_VIP_LEVEL_THRESHOLD: int = 1
    POLICY_HANDOFF_COUNT_THRESHOLD: int = 3
    # REL-01：S0–S4 自动升降级（S5 仅危机 / return-ai）；默认关。
    REL_STAGE_AUTO_ENABLED: bool = False
    REL_STAGE_ALLOW_DOWNGRADE: bool = True
    REL_STAGE_INITIATION_S1: float = 10.0
    REL_STAGE_INITIATION_S2: float = 30.0
    REL_STAGE_INITIATION_S3: float = 55.0
    REL_STAGE_INITIATION_S4: float = 78.0
    REL_STAGE_VIP_MIN_FOR_S1: int = 1
    # HO-LOCK / D5-3：handoff 会话级 Redis 锁（默认 5min TTL）；关则仅 DB 更新（旧行为）。
    HANDOFF_CONV_REDIS_LOCK_ENABLED: bool = True
    HANDOFF_CONV_REDIS_LOCK_TTL_SECONDS: int = 300
    # P2-02：GeoIP 服务配置（MaxMind/ip-api）
    MAXMIND_ENABLED: bool = False  # 是否启用 MaxMind GeoIP2
    MAXMIND_DB_PATH: Optional[str] = None  # MaxMind 数据库文件路径
    IPAPI_ENABLED: bool = True  # 是否启用 ip-api.com（备用方案）
    IPAPI_API_KEY: Optional[str] = None  # ip-api.com API 密钥（免费版不需要）
    GEOIP_CACHE_TTL: int = 3600  # GeoIP 结果缓存时间（秒）
    # P4-10：移动端推送服务配置（FCM/APNs）
    FCM_ENABLED: bool = False  # 是否启用 FCM（Android）
    FCM_CREDENTIALS_PATH: Optional[str] = None  # Firebase 服务账号密钥文件路径
    APNS_ENABLED: bool = False  # 是否启用 APNs（iOS）
    APNS_TEAM_ID: Optional[str] = None  # Apple Team ID
    APNS_KEY_ID: Optional[str] = None  # APNs Key ID
    APNS_KEY_PATH: Optional[str] = None  # APNs 私钥文件路径（.p8）
    APNS_BUNDLE_ID: str = 'com.hugme.app'  # App Bundle ID
    APNS_PRODUCTION: bool = False  # 是否使用生产环境 APNs（False = 开发环境）
    # P1-18：Session 管理器配置（自动重连 + 健康检查）
    SESSION_MANAGER_ENABLED: bool = False  # 是否启用 Session 管理器
    SESSION_RECONNECT_INTERVAL: int = 30  # 重连间隔（秒）
    SESSION_MAX_RECONNECT_ATTEMPTS: int = 5  # 最大重连尝试次数
    SESSION_HEALTH_CHECK_INTERVAL: int = 60  # 健康检查间隔（秒）
    # P1-20：账号监控配置
    ACCOUNT_MONITOR_ENABLED: bool = False  # 是否启用账号监控
    ACCOUNT_MONITOR_METRICS_PORT: int = 9091  # Prometheus metrics 端口
    ACCOUNT_MONITOR_COLLECTION_INTERVAL: int = 60  # 数据收集间隔（秒）
    ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS: int = 24  # 历史数据保留时长（小时）
    # P1-20：告警调度器配置
    ALERT_SCHEDULER_ENABLED: bool = False  # 是否启用告警调度器
    ALERT_SCHEDULER_CHECK_INTERVAL: int = 60  # 告警检查间隔（秒）
    ALERT_RULES_PATH: str = "config/alert_rules.json"  # 告警规则配置文件路径
    # P3-13：消息待发队列配置（Redis pending queue + send_at）
    MESSAGE_SCHEDULE_ENABLED: bool = False  # 是否启用消息待发队列
    MESSAGE_SCHEDULE_POLL_SECONDS: int = 20  # 轮询间隔（秒）
    MESSAGE_SCHEDULE_SCHEDULER_MAX_INSTANCES: int = 1  # 调度器最大并发实例数
    # P3-15：B/C/D 自动投递 Worker 配置
    AUTO_DELIVERY_ENABLED: bool = False  # 是否启用 B/C/D 自动投递 Worker
    AUTO_DELIVERY_POLL_SECONDS: int = 20  # 轮询间隔（秒）
    AUTO_DELIVERY_SCHEDULER_MAX_INSTANCES: int = 1  # 调度器最大并发实例数
    # P3-18：异步精聊归档 Worker 配置
    ARCHIVE_WORKER_ENABLED: bool = False  # 是否启用异步精聊归档 Worker
    ARCHIVE_WORKER_POLL_SECONDS: int = 30  # 轮询间隔（秒）
    ARCHIVE_WORKER_SCHEDULER_MAX_INSTANCES: int = 1  # 调度器最大并发实例数
    # Call broadcast: Telethon + PyTgCalls 视频通话（默认关，生产在 compose 显式打开）
    CALL_BROADCAST_ENABLED: bool = False
    CALL_BROADCAST_POLL_SECONDS: int = 15
    CALL_BROADCAST_SCHEDULER_MAX_INSTANCES: int = 1
    CALL_BROADCAST_MAX_CONCURRENT_PER_ACCOUNT: int = 1
    CALL_BROADCAST_DEFAULT_DURATION_SECONDS: int = 30
    CALL_BROADCAST_DEFAULT_VIDEO_PATH: Optional[str] = None
    CALL_BROADCAST_DEFAULT_VIDEO_ASSET_ID: Optional[str] = None
    CALL_BROADCAST_INCOMING_AUTO_ANSWER: bool = False
    CALL_BROADCAST_INBOUND_MANUAL_AFTER: int = 1
    CALL_BROADCAST_INBOUND_REVIEW_TTL_SECONDS: int = 90
    CALL_BROADCAST_KEYWORD_REVIEW_TTL_SECONDS: int = 600
    CALL_BROADCAST_TRANSCODE_ENABLED: bool = False
    CALL_BROADCAST_POST_CALL_NURTURE_ENABLED: bool = True
    CALL_BROADCAST_VIDEO_ROOT: str = "/data/videos"
    CALL_BROADCAST_WORK_DIR: str = "/tmp/call_broadcast"
    # 用户索要视频（文件或实时通话）时转人工，不自动拨打/发视频文件。
    VIDEO_REQUEST_OPERATOR_HANDOFF_ENABLED: bool = True

settings = Settings()
