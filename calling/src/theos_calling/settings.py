"""Calling account and private gateway configuration."""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AccountSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CALLING_", env_file=".env", extra="ignore")

    api_id: int = Field(gt=0)
    api_hash: SecretStr = Field(min_length=32, max_length=32)
    data_dir: Path = Path("~/.local/share/theos-calling").expanduser()

    def prepare_directory(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        return self.data_dir

    @property
    def session_path(self):
        return self.data_dir / "account.session"


class LoginSettings(AccountSettings):
    phone: SecretStr = SecretStr("")
    recipient_username: str = ""
    recipients: set[int] = Field(default_factory=set)


class Settings(AccountSettings):
    key: SecretStr = Field(min_length=32)
    recipients: set[int] = Field(default_factory=set)
    host: str = "127.0.0.1"
    port: int = Field(default=8882, ge=1, le=65535)
    daily_limit: int = Field(default=20, ge=1, le=1000)
    spoken_approvals: bool = False

    @model_validator(mode="after")
    def private_recipients(self):
        if any(user_id <= 0 for user_id in self.recipients):
            raise ValueError("Use positive Telegram user IDs for call recipients.")
        return self
