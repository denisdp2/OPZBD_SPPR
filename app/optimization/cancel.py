"""Остановка расчёта по кнопке пользователя."""

from __future__ import annotations

import contextvars
import threading


class OptimizationCancelled(Exception):
    """Пользователь остановил расчёт."""


_event: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "opt_cancel", default=None
)


def bind(event: threading.Event):
    return _event.set(event)


def reset(token) -> None:
    _event.reset(token)


def raise_if_stopped() -> None:
    event = _event.get()
    if event is not None and event.is_set():
        raise OptimizationCancelled()
