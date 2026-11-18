"""Оценка выбранного набора (кнопка «Рассчитать»).

Вход — ``app.core.models.Problem``, выход — ``app.core.models.EvaluationResult``.
"""

from app.evaluation.evaluator import evaluate

__all__ = ["evaluate"]
