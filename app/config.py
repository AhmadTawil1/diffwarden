import base64

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env also holds ANTHROPIC_API_KEY, which the Anthropic SDK reads itself.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_app_id: str
    github_private_key_base64: str
    github_webhook_secret: str
    anthropic_model: str = "claude-sonnet-5"
    min_confidence: float = 0.7
    max_comments: int = 15
    verify_findings: bool = True

    @property
    def private_key_pem(self) -> str:
        return base64.b64decode(self.github_private_key_base64).decode()


settings = Settings()
