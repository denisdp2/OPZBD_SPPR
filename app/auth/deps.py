"""Зависимости FastAPI: текущий пользователь и доступ только для администратора."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.auth.store import AuthStore, User

COOKIE_NAME = "szi_session"


def auth_store(request: Request) -> AuthStore:
    return request.app.state.auth


def current_user(request: Request) -> User | None:
    return auth_store(request).user_for_token(request.cookies.get(COOKIE_NAME))


def require_login(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Нужна авторизация")
    return user


def require_admin(request: Request) -> User:
    user = require_login(request)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Доступ только для администратора")
    return user
