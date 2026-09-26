import hashlib
import hmac

from app.config import settings
from app.main import verify_signature

BODY = b'{"action": "opened"}'


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_correct_signature_is_accepted():
    assert verify_signature(BODY, sign(BODY, settings.github_webhook_secret))


def test_wrong_signature_is_rejected():
    assert not verify_signature(BODY, sign(BODY, "not-the-secret"))


def test_missing_signature_is_rejected():
    assert not verify_signature(BODY, None)
