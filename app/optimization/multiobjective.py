

from __future__ import annotations

import math

from app.core.cover import expand_covers
from app.core.models import Problem, Solution
from app.optimization.boolean_ilp import exact_pareto
from app.optimization.encoding import CoverInstance
from app.optimization.pareto_3d import pareto_front_3d

Point = tuple[list[str], float, int, bool]


def _ideal_distance(points: list[Solution]) -> Solution:
    costs = [point.cost for point in points]
    covered = [point.covered_count for point in points]
    days = [point.total_implementation_days for point in points]
    ideal_cost = min(costs)
    ideal_cover = max(covered)
    ideal_days = min(days)
    cost_span = max(costs) - ideal_cost
    cover_span = ideal_cover - min(covered)
    day_span = max(days) - ideal_days

    def rho(point: Solution) -> tuple[float, int, float, float]:
        delta_cost = 0.0 if cost_span <= 1e-9 else (point.cost - ideal_cost) / cost_span
        delta_cover = 0.0 if cover_span == 0 else (ideal_cover - point.covered_count) / cover_span
        delta_days = (
            0.0 if day_span <= 1e-9 else (point.total_implementation_days - ideal_days) / day_span
        )
        distance = math.sqrt(delta_cost**2 + delta_cover**2 + delta_days**2)
        return (distance, -point.covered_count, point.cost, point.total_implementation_days)

    return min(points, key=rho)


def _neutral_free(problem: Problem, selected: list[str]) -> list[str]:
    """Бесплатные позиции без срока не меняют ни один из трёх критериев."""
    chosen = list(selected)
    seen = set(chosen)
    known = set(problem.requirements)
    for item in problem.items:
        if item.id in seen:
            continue
        if float(problem.costs.get(item.id, 0.0)) > 1e-12:
            continue
        if float(problem.implementation_days.get(item.id, 0.0)) > 1e-12:
            continue
        covers = [req_id for req_id in expand_covers(item, problem.items, known) if req_id in known]
        if not covers:
            continue
        seen.add(item.id)
        chosen.append(item.id)
    return chosen


def compromise(problem: Problem, *, budget: float | None) -> list[str]:
    points = pareto_front_3d(problem)
    if budget is not None:
        points = [point for point in points if point.cost <= budget + 1e-12]
    if not points:
        return []
    feasible = [point for point in points if point.feasible]
    chosen = _ideal_distance(feasible or points)
    return _neutral_free(problem, list(chosen.selected))


def pareto_front(instance: CoverInstance) -> list[Point]:
    return exact_pareto(instance)
