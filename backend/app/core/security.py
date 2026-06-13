"""
JWT token generation + HMAC webhook verification.

Concepts you'll learn building this:
- JWT: a signed token that proves identity without hitting the DB each request
- HMAC: a hash-based message authentication code (GitHub uses it to sign webhooks)
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt  # type: ignore
from passlib.context import CryptContext  # type: ignore

from app.core.config import settings

# ── Password Hashing ──────────────────────────────────────────────────────────
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# ── JWT Settings ──────────────────────────────────────────────────────────────
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(user_id: str) -> str:
    """
    Creates a short-lived access token (30 min).
    The frontend sends this in every API request.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,   # subject = who this token belongs to
        "exp": expire,    # expiry time
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """
    Creates a long-lived refresh token (30 days).
    Used to get a new access token when the old one expires.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Verifies and decodes a JWT token.
    Raises JWTError if the token is invalid or expired.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def generate_webhook_secret() -> str:
    """
    Generates a cryptographically secure random string.
    Each repo gets its own secret — stored in the DB, used to verify webhooks.
    """
    return secrets.token_hex(32)  # 64-character hex string


def verify_webhook_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Verifies GitHub's webhook signature.

    GitHub signs every webhook payload with HMAC-SHA256 using your webhook secret.
    The signature comes in the header: X-Hub-Signature-256: sha256=<hash>

    Why this matters: Without this check, anyone on the internet could send
    fake webhook events to your endpoint and trigger AI reviews.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    # Compute expected signature using your stored secret
    expected = "sha256=" + hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # compare_digest prevents timing attacks
    # (timing attacks: measuring response time to guess the secret byte by byte)
    return hmac.compare_digest(expected, signature_header)
