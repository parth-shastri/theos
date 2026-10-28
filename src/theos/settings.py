"""Explicit settings for the application and optional services."""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, SecretStr, StringConstraints, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from theos.config import DEFAULT_MODEL, DEFAULT_PROVIDER
from theos.services.mcp_accounts.config import MCPAccountSettings


class MemorySettings(BaseModel):
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:8001"
    api_key: SecretStr = SecretStr("")
    timeout: float = Field(default=15, gt=0, le=120)
    auth_header: Literal["X-API-Key", "Authorization"] = "X-API-Key"
    auth_prefix: str = ""
    auto_retrieve: bool = True
    retrieval_limit: int = Field(default=5, ge=1, le=20)
    retrieval_chars: int = Field(default=4000, ge=256, le=16000)
    retrieval_timeout: float = Field(default=3, gt=0, le=15)
    consolidation_turns: int = Field(default=5, ge=1, le=50)
    consolidation_interval: int = Field(default=600, ge=10, le=86400)


class OAuthSettings(BaseModel):
    client_id: str = ""
    client_secret: SecretStr = SecretStr("")
    redirect_uri: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.client_id)

    @model_validator(mode="after")
    def complete(self):
        if any((self.client_id, self.client_secret.get_secret_value(), self.redirect_uri)):
            if not all((self.client_id, self.client_secret.get_secret_value(), self.redirect_uri)):
                raise ValueError("Set the OAuth client ID, secret, and redirect URI together.")
            from urllib.parse import urlsplit

            uri = urlsplit(self.redirect_uri)
            if uri.scheme != "https" and not (
                uri.scheme == "http" and uri.hostname in {"localhost", "127.0.0.1"}
            ):
                raise ValueError("Use HTTPS for the OAuth callback, except on localhost.")
        return self


class SandboxSettings(BaseModel):
    enabled: bool = False
    domain: str = "localhost:8080"
    api_key: SecretStr = SecretStr("")
    use_server_proxy: bool = False
    image: str = "theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3"
    timeout_seconds: int = Field(default=3600, ge=60, le=3600)


class StorageSettings(BaseModel):
    checkpoint_keep: int = Field(default=3, ge=1, le=100)
    gc_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    gc_grace_seconds: int = Field(default=3600, ge=60, le=604800)
    endpoint: str = ""
    bucket: str = ""
    access_key: SecretStr = SecretStr("")
    secret_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def complete(self):
        values = (
            self.endpoint,
            self.bucket,
            self.access_key.get_secret_value(),
            self.secret_key.get_secret_value(),
        )
        if any(values) and not all(values):
            raise ValueError("Set all four R2 storage fields together.")
        return self


class ModelCosts(BaseModel):
    """Configured USD token rates for one model."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class OpenRouterSettings(BaseModel):
    """Prefer responsive endpoints while retaining ZDR and provider fallback."""

    sort: Literal["latency", "throughput", "price"] = "latency"
    latency_p90: float | None = Field(default=15, gt=0, le=600)
    throughput_p90: float | None = Field(default=10, gt=0, le=10000)

    def preferences(self):
        result = {"sort": self.sort}
        if self.latency_p90 is not None:
            result["preferred_max_latency"] = {"p90": self.latency_p90}
        if self.throughput_p90 is not None:
            result["preferred_min_throughput"] = {"p90": self.throughput_p90}
        return result


class TracingSettings(BaseModel):
    """Optional OTLP/HTTP export with explicit, bounded content capture."""

    enabled: bool = False
    endpoint: str = "http://127.0.0.1:4318/v1/traces"
    headers: dict[str, SecretStr] = Field(default_factory=dict)
    service_name: str = "theos"
    sample_ratio: float = Field(default=1, ge=0, le=1)
    timeout: float = Field(default=5, gt=0, le=30)
    capture_content: bool = False
    content_max_bytes: int = Field(default=8192, ge=256, le=65536)
    span_content_max_bytes: int = Field(default=32768, ge=1024, le=131072)

    @model_validator(mode="after")
    def valid_endpoint(self):
        uri = urlsplit(self.endpoint)
        if uri.scheme not in {"http", "https"} or not uri.hostname or uri.username or uri.password:
            raise ValueError(
                "Use an HTTP or HTTPS trace endpoint. Put credentials in tracing headers."
            )
        if not self.service_name.strip():
            raise ValueError("Set a nonempty tracing service name.")
        return self


class ClientSettings(BaseSettings):
    """Read remote credentials without validating deployment service configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )
    server_url: str = ""
    server_token: SecretStr = SecretStr("")


class Settings(ClientSettings):
    """Read AGENT_ settings. Nested fields use two underscores."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] = (
        "Theos"
    )
    data_dir: Path = Path(".theos")
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    # Each credential maps to one identity. Never accept an owner from request data.
    users: dict[str, SecretStr] = Field(default_factory=dict)
    admins: set[str] = Field(default_factory=set)
    web_url: str = ""
    frontend_secret: SecretStr = SecretStr("")
    provider: Literal["gemini", "openrouter", "openai", "anthropic", "llama", "fake"] = (
        DEFAULT_PROVIDER
    )
    model: str = DEFAULT_MODEL
    # Optional override. OpenAI and OpenRouter default to the previous Luna model.
    fallback_model: str | None = None
    api_key: SecretStr = SecretStr("")
    model_base_url: str = ""
    openrouter: OpenRouterSettings = Field(default_factory=OpenRouterSettings)
    allowed_models: list[str] = Field(default_factory=list)
    reasoning: Literal["default", "none", "low", "medium", "high", "xhigh", "max"] = "default"
    auto_titles: bool = True
    max_concurrent_turns: int = Field(default=4, ge=1, le=32)
    # Retained for bounded harness callers. Theos disables call and turn-time
    # budget enforcement in Runtime, while context and output limits still apply.
    max_model_calls: int = Field(default=30, ge=1, le=100)
    # Omitted counts derive from these ratios when a turn starts.
    max_compaction_calls: int | None = Field(default=None, ge=0, le=100)
    compaction_call_ratio: float = Field(default=1 / 6, ge=0, le=1)
    # Accept older environment files. Recovery now always reserves one response call.
    max_recovery_calls: int = Field(default=1, ge=0, le=100)
    delegate_max_model_calls: int | None = Field(default=None, ge=1, le=100)
    delegate_call_ratio: float = Field(default=1 / 3, gt=0, le=1)
    max_scheduled_tasks: int = Field(default=50, ge=1, le=200)
    turn_timeout: int = Field(default=300, ge=10, le=3600)
    context_tokens: int | None = Field(default=None, ge=4096)
    compaction_model: str | None = None
    compaction_trigger_ratio: float = Field(default=0.5, gt=0, le=1)
    compaction_tail_ratio: float = Field(default=0.025, gt=0, le=0.5)
    max_output_tokens: int = Field(default=8192, ge=1, le=1_000_000)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    timezone: str = "UTC"
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)
    model_costs: dict[str, ModelCosts] = Field(default_factory=dict)
    telegram_token: SecretStr = SecretStr("")
    telegram_access_code: SecretStr = SecretStr("")
    telegram_users: set[int] = Field(default_factory=set)
    telegram_max_users: int = Field(default=50, ge=1, le=50)
    telegram_chats: set[int] = Field(default_factory=set)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    exa_key: SecretStr = SecretStr("")
    brave_key: SecretStr = SecretStr("")
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    transcription_url: str = ""
    transcription_key: SecretStr = SecretStr("")
    transcription_model: str = "whisper-1"
    kokoro_url: str = ""
    kokoro_voice: str = "am_michael(0.7)+bm_george(0.3)"
    kokoro_speed: float = Field(default=0.9, ge=0.5, le=2)
    kokoro_key: SecretStr = SecretStr("")
    slack: MCPAccountSettings = Field(default_factory=MCPAccountSettings)
    gmail: OAuthSettings = Field(default_factory=OAuthSettings)
    health: OAuthSettings = Field(default_factory=OAuthSettings)
    token_encryption_key: SecretStr = SecretStr("")
    health_interval: int = Field(default=43200, ge=60)
    zepto_url: str = ""
    zepto_redirect_uri: str = "http://localhost/callback"
    skills_dir: Path | None = None

    @model_validator(mode="after")
    def validate_configuration(self):
        ZoneInfo(self.timezone)
        self.web_url = self.web_url.strip().rstrip("/")
        if self.frontend_secret and len(self.frontend_secret.get_secret_value()) < 32:
            raise ValueError("AGENT_FRONTEND_SECRET must contain at least 32 characters.")
        if self.web_url:
            web = urlsplit(self.web_url)
            if (
                not web.hostname
                or web.username
                or web.password
                or web.path
                or web.query
                or web.fragment
                or not (
                    web.scheme == "https"
                    or (web.scheme == "http" and web.hostname in {"localhost", "127.0.0.1"})
                )
            ):
                raise ValueError("Use an HTTPS origin for AGENT_WEB_URL, except on localhost.")
        from theos.storage.account_access import RESERVED_PREFIXES

        if any(not owner.strip() or owner.startswith(RESERVED_PREFIXES) for owner in self.users):
            raise ValueError("Use browser user IDs outside the Telegram and terminal namespaces.")
        if any(len(token.get_secret_value()) < 32 for token in self.users.values()):
            raise ValueError("Each browser token must contain at least 32 characters.")
        values = [token.get_secret_value() for token in self.users.values()]
        if len(values) != len(set(values)):
            raise ValueError("Use a different browser token for each user.")
        if not self.admins <= self.users.keys():
            raise ValueError("Each administrator must have a browser token.")
        self.slack.check_callback("slack")
        if self.gmail.enabled or self.health.enabled or self.zepto_url or self.slack.enabled:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.token_encryption_key.get_secret_value().encode())
            except (ValueError, TypeError) as error:
                raise ValueError(
                    "Set a valid Fernet token encryption key for connected accounts."
                ) from error
        if self.zepto_url:
            endpoint = urlsplit(self.zepto_url)
            if endpoint.scheme != "https" and not (
                endpoint.scheme == "http" and endpoint.hostname in {"localhost", "127.0.0.1"}
            ):
                raise ValueError("Use HTTPS for the Zepto MCP endpoint, except on localhost.")
            redirect = urlsplit(self.zepto_redirect_uri)
            local_redirect = (
                redirect.scheme == "http"
                and redirect.hostname in {"localhost", "127.0.0.1"}
                and redirect.path == "/callback"
                and not redirect.query
                and not redirect.fragment
                and not redirect.username
                and not redirect.password
            )
            public_redirect = (
                redirect.scheme == "https"
                and redirect.path == "/oauth/zepto/callback"
                and not redirect.query
                and not redirect.fragment
                and not redirect.username
                and not redirect.password
            )
            if not (local_redirect or public_redirect):
                raise ValueError(
                    "Use http://localhost/callback or an HTTPS /oauth/zepto/callback URI for Zepto."
                )
        return self
