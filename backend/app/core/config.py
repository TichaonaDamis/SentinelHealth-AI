from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    """Runtime configuration. Every value can be set with a ``SENTINEL_`` environment variable.

    In AWS these come from ECS task definitions backed by Secrets Manager / SSM.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENTINEL_", extra="ignore")

    app_name: str = "SentinelHealth AI"
    environment: str = "local"  # local | test | dev | staging | prod
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
    db_pool_size: int = 10
    db_echo: bool = False

    jwt_secret: str = INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "sentinelhealth-ai"
    access_token_ttl_minutes: int = 30
    # Base64 urlsafe 32-byte key for field-level encryption of PHI (Fernet). In AWS this is a
    # KMS-encrypted data key decrypted at start-up.
    field_encryption_key: str | None = None

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])

    model_dir: Path = Path(__file__).resolve().parents[3] / "ml" / "artifacts"

    # Copilot / LLM
    copilot_provider: str = "anthropic"  # anthropic | openai | offline
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    llm_max_tokens: int = 1500
    opensearch_url: str | None = None

    # Notifications
    notification_channels: list[str] = Field(default_factory=lambda: ["in_app", "log"])
    ses_sender: str | None = None
    sns_topic_arn: str | None = None
    partner_webhook_url: str | None = None
    alert_dedup_days: int = 7

    seed_password: str = "ChangeMe!2026"

    @property
    def is_production(self) -> bool:
        return self.environment in {"staging", "prod"}

    @model_validator(mode="after")
    def _guard_production(self):
        if self.is_production:
            if self.jwt_secret == INSECURE_DEFAULT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("SENTINEL_JWT_SECRET must be set to a strong secret outside local/test")
            if not self.field_encryption_key:
                raise ValueError("SENTINEL_FIELD_ENCRYPTION_KEY is required outside local/test")
            if "*" in self.cors_origins:
                raise ValueError("wildcard CORS origins are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
