import os
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status

ACCESS_TOKEN_TTL_SECONDS = 15 * 60
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


def _secret_key() -> str:
    secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key or len(secret_key) < 32:
        raise RuntimeError("JWT_SECRET_KEY must contain at least 32 characters.")
    return secret_key


def _create_token(user_id: int, token_type: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": token_type,
            "iat": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        },
        _secret_key(),
        algorithm="HS256",
    )


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access", ACCESS_TOKEN_TTL_SECONDS)


def create_refresh_token(user_id: int) -> str:
    return _create_token(user_id, "refresh", REFRESH_TOKEN_TTL_SECONDS)


def create_token_pair(user_id: int) -> tuple[str, str]:
    return create_access_token(user_id), create_refresh_token(user_id)


def decode_token(token: str, expected_type: str) -> int:
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=["HS256"])
        if payload.get("type") != expected_type:
            raise jwt.InvalidTokenError("Unexpected token type")
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from error
