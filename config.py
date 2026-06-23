import os
from pathlib import Path
from dataclasses import dataclass, field


def _env_bool(key: str, default: str = "true") -> bool:
    return os.getenv(key, default).lower() == "true"


def _env_list(key: str) -> list[str]:
    raw = os.getenv(key, "")
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


@dataclass
class Config:
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "./data/nexus.db"))
    chroma_path: str = field(default_factory=lambda: os.getenv("CHROMA_PATH", "./data/chromadb"))
    cold_mode_enabled: bool = field(default_factory=lambda: _env_bool("COLD_MODE_ENABLED", "true"))
    require_approval_for_exec: bool = field(default_factory=lambda: _env_bool("REQUIRE_APPROVAL_FOR_EXEC", "true"))

    # API + Web OS
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8765")))
    enable_web_ui: bool = field(default_factory=lambda: _env_bool("ENABLE_WEB_UI", "true"))
    enable_cli: bool = field(default_factory=lambda: _env_bool("ENABLE_CLI", "true"))

    # Channels — Telegram is primary default
    enabled_channels: list[str] = field(default_factory=lambda: _env_list("ENABLED_CHANNELS") or ["telegram"])

    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    telegram_allowed_users: list[str] = field(default_factory=lambda: _env_list("TELEGRAM_ALLOWED_USERS"))

    whatsapp_token: str = field(default_factory=lambda: os.getenv("WHATSAPP_TOKEN", ""))
    whatsapp_phone_number_id: str = field(default_factory=lambda: os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""))
    whatsapp_verify_token: str = field(default_factory=lambda: os.getenv("WHATSAPP_VERIFY_TOKEN", "nexus-verify"))
    whatsapp_app_secret: str = field(default_factory=lambda: os.getenv("WHATSAPP_APP_SECRET", ""))
    whatsapp_allowed_numbers: list[str] = field(default_factory=lambda: _env_list("WHATSAPP_ALLOWED_NUMBERS"))

    instagram_token: str = field(default_factory=lambda: os.getenv("INSTAGRAM_TOKEN", ""))
    instagram_page_id: str = field(default_factory=lambda: os.getenv("INSTAGRAM_PAGE_ID", ""))
    instagram_app_secret: str = field(default_factory=lambda: os.getenv("INSTAGRAM_APP_SECRET", ""))
    instagram_allowed_users: list[str] = field(default_factory=lambda: _env_list("INSTAGRAM_ALLOWED_USERS"))

    discord_token: str = field(default_factory=lambda: os.getenv("DISCORD_TOKEN", ""))
    discord_allowed_users: list[str] = field(default_factory=lambda: _env_list("DISCORD_ALLOWED_USERS"))

    slack_bot_token: str = field(default_factory=lambda: os.getenv("SLACK_BOT_TOKEN", ""))
    slack_signing_secret: str = field(default_factory=lambda: os.getenv("SLACK_SIGNING_SECRET", ""))
    slack_allowed_users: list[str] = field(default_factory=lambda: _env_list("SLACK_ALLOWED_USERS"))

    signal_api_url: str = field(default_factory=lambda: os.getenv("SIGNAL_API_URL", "http://127.0.0.1:8090"))
    signal_account: str = field(default_factory=lambda: os.getenv("SIGNAL_ACCOUNT", ""))
    signal_allowed_numbers: list[str] = field(default_factory=lambda: _env_list("SIGNAL_ALLOWED_NUMBERS"))

    teams_app_id: str = field(default_factory=lambda: os.getenv("TEAMS_APP_ID", ""))
    teams_app_password: str = field(default_factory=lambda: os.getenv("TEAMS_APP_PASSWORD", ""))
    teams_allowed_users: list[str] = field(default_factory=lambda: _env_list("TEAMS_ALLOWED_USERS"))

    # LLM cloud keys (optional — router uses if set)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # Phase 3 — Deploy & Control
    executor_sandbox_enabled: bool = field(default_factory=lambda: _env_bool("EXECUTOR_SANDBOX_ENABLED", "true"))
    structured_log_json: bool = field(default_factory=lambda: _env_bool("STRUCTURED_LOG_JSON", "false"))
    allow_public_bots: bool = field(default_factory=lambda: _env_bool("ALLOW_PUBLIC_BOTS", "false"))

    # Social Media (official API only)
    twitter_api_key: str = field(default_factory=lambda: os.getenv("TWITTER_API_KEY", ""))
    twitter_api_secret: str = field(default_factory=lambda: os.getenv("TWITTER_API_SECRET", ""))
    twitter_access_token: str = field(default_factory=lambda: os.getenv("TWITTER_ACCESS_TOKEN", ""))
    twitter_access_token_secret: str = field(default_factory=lambda: os.getenv("TWITTER_ACCESS_TOKEN_SECRET", ""))
    twitter_bearer_token: str = field(default_factory=lambda: os.getenv("TWITTER_BEARER_TOKEN", ""))
    linkedin_access_token: str = field(default_factory=lambda: os.getenv("LINKEDIN_ACCESS_TOKEN", ""))
    linkedin_person_id: str = field(default_factory=lambda: os.getenv("LINKEDIN_PERSON_ID", ""))
    linkedin_org_id: str = field(default_factory=lambda: os.getenv("LINKEDIN_ORG_ID", ""))

    # Phase 2 — Cloud Brain
    bus_backend: str = field(default_factory=lambda: os.getenv("BUS_BACKEND", "local"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))
    use_react_loop: bool = field(default_factory=lambda: _env_bool("USE_REACT_LOOP", "true"))
    rag_enabled: bool = field(default_factory=lambda: _env_bool("RAG_ENABLED", "true"))
    docs_path: str = field(default_factory=lambda: os.getenv("DOCS_PATH", ".."))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))
    auto_ingest_docs: bool = field(default_factory=lambda: _env_bool("AUTO_INGEST_DOCS", "true"))

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        config = cls()
        config_file = Path(path)
        if config_file.exists():
            import yaml
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}
            for k, v in data.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        return config


config = Config.load()
