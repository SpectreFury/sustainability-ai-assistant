import bcrypt
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import User


async def signup_user(
    session: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    username = username.strip()
    email = email.strip().lower()
    password_bytes = password.encode("utf-8")

    if len(password_bytes) > 72:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be 72 bytes or fewer.",
        )

    existing_user = await session.scalar(
        select(User).where(or_(User.username == username, User.email == email))
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered.",
        )

    user = User(
        username=username,
        email=email,
        hashed_password=bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode(
            "utf-8"
        ),
    )
    session.add(user)

    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered.",
        ) from error

    await session.refresh(user)
    return user


async def login_user(session: AsyncSession, email: str, password: str) -> User:
    email = email.strip().lower()
    password_bytes = password.encode("utf-8")
    user = await session.scalar(select(User).where(User.email == email))

    if (
        user is None
        or len(password_bytes) > 72
        or not bcrypt.checkpw(password_bytes, user.hashed_password.encode("utf-8"))
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    return user
