import base64

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": tolerate extra entries in .env (e.g. SMEE_URL).
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_app_id: str
    github_private_key_base64: str
    github_webhook_secret: str
    anthropic_api_key: SecretStr  # SecretStr hides the value in logs and errors
    anthropic_model: str = "claude-sonnet-5"
    # USD per million tokens for anthropic_model (Sonnet 5 list price); update if the model or pricing changes.
    input_price_per_mtok: float = 2.0
    output_price_per_mtok: float = 10.0
    min_confidence: float = 0.7
    max_comments: int = 15
    verify_findings: bool = True

    @property
    def private_key_pem(self) -> str:
        return base64.b64decode(self.github_private_key_base64).decode()


settings = Settings()
