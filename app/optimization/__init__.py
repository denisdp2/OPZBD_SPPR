"""Алгоритмы подбора набора средств и мер."""

from __future__ import annotations

from app.core.models import OptimizerInfo
from app.optimization.solvers import OPTIMIZERS


class UnknownOptimizer(KeyError):
    """Неизвестное имя алгоритма."""


def list_optimizers() -> list[OptimizerInfo]:
    return [
        OptimizerInfo(
            name=optimizer.name,
            title=optimizer.title,
            exact=optimizer.exact,
            description=optimizer.description,
            supports_pareto=optimizer.supports_pareto,
            supported_modes=list(optimizer.supported_modes),
        )
        for optimizer in OPTIMIZERS
    ]


def get_optimizer(name: str):
    for optimizer in OPTIMIZERS:
        if optimizer.name == name:
            return optimizer
    raise UnknownOptimizer(name)
