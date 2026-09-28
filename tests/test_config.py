import pytest
from pydantic import ValidationError

from app.config import Settings


def test_startup_errors_do_not_print_secret_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GITHUB_APP_ID=1\nGITHUB_PRIVATE_KEY_BASE64=cHJpdmF0ZS1rZXk=\n"
                   "ANTHROPIC_API_KEY=sk-test-not-real\n", encoding="utf-8")  # webhook secret missing
    with pytest.raises(ValidationError) as err:
        Settings(_env_file=env)
    message = str(err.value)
    assert "github_webhook_secret" in message
    assert "cHJpdmF0ZS1rZXk=" not in message and "sk-test-not-real" not in message
