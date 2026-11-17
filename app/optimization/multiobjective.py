"""Приближение по локальным критериям к идеальной точке.

На множестве альтернатив X (Парето-фронт допустимых наборов):

    f1(x) = cost(x)     → min
    f2(x) = covered(x)  → max

    f1* = min_x f1(x)
    f2* = max_x f2(x)

    δ1(x) = (f1(x) - f1*) / (max f1 - f1*)
    δ2(x) = (f2* - f2(x)) / (f2* - min f2)

    ρ(x) = sqrt( δ1(x)^2 + δ2(x)^2 )
    x* = argmin_x ρ(x)
"""

from __future__ import annotations

import math

from app.optimization.boolean_ilp import exact_pareto
from app.optimization.encoding import CoverInstance

Point = tuple[list[str], float, int, bool]


def _ideal_distance(points: list[Point]) -> Point:
    costs = [point[1] for point in points]
    covered = [point[2] for point in points]
    ideal_cost = min(costs)
    ideal_cover = max(covered)
    cost_span = max(costs) - ideal_cost
    cover_span = ideal_cover - min(covered)

    def rho(point: Point) -> tuple[float, int, float]:
        delta_cost = 0.0 if cost_span <= 1e-9 else (point[1] - ideal_cost) / cost_span
        delta_cover = 0.0 if cover_span == 0 else (ideal_cover - point[2]) / cover_span
        distance = math.sqrt(delta_cost**2 + delta_cover**2)
        return (distance, -point[2], point[1])

    return min(points, key=rho)


def compromise(
    instance: CoverInstance, *, budget: float | None
) -> tuple[list[str], float, int, bool]:
    points = exact_pareto(instance)
    if budget is not None:
        affordable = [point for point in points if point[1] <= budget + 1e-12]
        points = affordable or points
    feasible = [point for point in points if point[3]]
    return _ideal_distance(feasible or points)


def pareto_front(instance: CoverInstance) -> list[Point]:
    return exact_pareto(instance)
