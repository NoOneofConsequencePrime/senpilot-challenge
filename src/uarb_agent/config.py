"""Settings from the environment / .env. Missing required values fail at startup, not mid-request."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agentmail_api_key: str = Field(min_length=1)
    agentmail_inbox: str = Field(min_length=1)

    deepseek_api_key: str = Field(min_length=1)
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"

    oci_namespace: str = Field(min_length=1)
    oci_region: str = Field(min_length=1)
    oci_bucket: str = "uarb-agent-zips"
    oci_access_key: str = Field(min_length=1)
    oci_secret_key: str = Field(min_length=1)

    data_dir: Path = Path("data")

    # Empty = anyone may use the agent (so reviewers can try it); otherwise a comma-separated allowlist.
    allowed_senders: str = ""
    per_sender_per_hour: int = 5
    global_per_day: int = 60
    max_requests_per_email: int = 3

    # AgentMail rejects requests over 6 MB and base64 adds a third, so ~4.3 MB raw is the inline limit.
    inline_max_bytes: int = int(4.3 * MB)
    # Above this, recipient mail servers (Outlook/Exchange ~20-35 MB on the wire) may bounce the email.
    attach_max_bytes: int = 15 * MB
    link_days: int = 7
    recordings_budget_bytes: int = 1024 * MB
    recordings_link_days: int = 2

    @property
    def allowed(self) -> set[str]:
        return {s.strip().lower() for s in self.allowed_senders.split(",") if s.strip()}
