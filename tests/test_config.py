import pytest
from pydantic import ValidationError

from app.config import Settings

SECRET_VARS = ["GITHUB_APP_ID", "GITHUB_PRIVATE_KEY_BASE64", "GITHUB_WEBHOOK_SECRET", "ANTHROPIC_API_KEY"]


def test_startup_errors_do_not_print_secret_values(tmp_path, monkeypatch):
    for name in SECRET_VARS:  # read only the file below, even where these are set (e.g. in CI)
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("GITHUB_APP_ID=1\nGITHUB_PRIVATE_KEY_BASE64=cHJpdmF0ZS1rZXk=\n"
                   "ANTHROPIC_API_KEY=sk-test-not-real\n", encoding="utf-8")  # webhook secret missing
    with pytest.raises(ValidationError) as err:
        Settings(_env_file=env)
    message = str(err.value)
    assert "github_webhook_secret" in message
    assert "cHJpdmF0ZS1rZXk=" not in message and "sk-test-not-real" not in message
