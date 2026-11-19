"""Расчёт покрытия и стоимости выбранного пользователем набора."""

from __future__ import annotations

from math import fsum

from app.core.models import EvaluationResult, Problem


def evaluate(problem: Problem) -> EvaluationResult:
    """Оценить уже разрешённую задачу, собранную функцией ``build_problem``.

    ``Problem.items`` содержит только выбранные пользователем позиции, а их
    ``covers`` уже развёрнуты до кодов рассматриваемых требований. Поэтому
    оценка не обращается к БД и не пытается самостоятельно трактовать связи
    каталога.
    """
    requirement_ids = list(dict.fromkeys(problem.requirements))
    requirement_set = set(requirement_ids)
    mandatory_ids = list(dict.fromkeys(
        requirement_id
        for requirement_id in problem.mandatory
        if requirement_id in requirement_set
    ))
    mandatory_set = set(mandatory_ids)

    covered_by: dict[str, list[str]] = {}
    for item in problem.items:
        for requirement_id in item.covers:
            if requirement_id not in requirement_set:
                continue
            covering_items = covered_by.setdefault(requirement_id, [])
            if item.id not in covering_items:
                covering_items.append(item.id)

    covered_set = set(covered_by)
    covered = [
        requirement_id for requirement_id in requirement_ids if requirement_id in covered_set
    ]
    uncovered = [
        requirement_id for requirement_id in requirement_ids if requirement_id not in covered_set
    ]
    uncovered_mandatory = [
        requirement_id for requirement_id in mandatory_ids if requirement_id not in covered_set
    ]
    optional_ids = [
        requirement_id for requirement_id in requirement_ids if requirement_id not in mandatory_set
    ]

    total_cost = fsum(float(problem.costs.get(item.id, 0.0)) for item in problem.items)
    total_implementation_days = fsum(
        float(problem.implementation_days.get(item.id, 0.0)) for item in problem.items
    )
    return EvaluationResult(
        all_mandatory_covered=not uncovered_mandatory,
        uncovered_mandatory=uncovered_mandatory,
        covered=covered,
        uncovered=uncovered,
        covered_optional=sum(requirement_id in covered_set for requirement_id in optional_ids),
        total_optional=len(optional_ids),
        total_cost=round(total_cost, 2),
        total_implementation_days=round(total_implementation_days, 1),
        covered_by={requirement_id: covered_by[requirement_id] for requirement_id in covered},
    )
