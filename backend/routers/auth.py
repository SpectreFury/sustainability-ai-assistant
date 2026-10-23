import os
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.auth import get_current_user
from db import get_db
from models import User
from schemas.auth import LoginRequest, SignupRequest, UserResponse
from services.auth_service import login_user, signup_user
from services.token_service import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    create_access_token,
    create_token_pair,
    decode_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_token_cookie(
    response: Response,
    name: str,
    token: str,
    max_age: int,
    path: str,
) -> None:
    secure = os.getenv("JWT_COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        path=path,
    )


def _set_auth_cookies(response: Response, user_id: int) -> None:
    access_token, refresh_token = create_token_pair(user_id)
    _set_token_cookie(
        response, "access_token", access_token, ACCESS_TOKEN_TTL_SECONDS, "/"
    )
    _set_token_cookie(
        response, "refresh_token", refresh_token, REFRESH_TOKEN_TTL_SECONDS, "/"
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await signup_user(
        session,
        username=payload.username,
        email=str(payload.email),
        password=payload.password,
    )
    _set_auth_cookies(response, user.id)
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    user = await login_user(
        session,
        email=str(payload.email),
        password=payload.password,
    )
    _set_auth_cookies(response, user.id)
    return user


@router.post("/refresh", response_model=UserResponse)
async def refresh(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> UserResponse:
    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required.",
        )

    user_id = decode_token(refresh_token, "refresh")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    _set_token_cookie(
        response,
        "access_token",
        create_access_token(user.id),
        ACCESS_TOKEN_TTL_SECONDS,
        "/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("refresh_token", path="/auth")


@router.get("/me", response_model=UserResponse)
async def current_user(
    user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return user
