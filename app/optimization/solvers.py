"""Подбор набора: булево программирование, ветви и границы, жадное покрытие и Парето."""

from __future__ import annotations

import time

from app.core.interfaces import Optimizer
from app.core.models import OptimizeMode, Problem, Solution
from app.core.problem import make_solution
from app.optimization.boolean_ilp import exact_pareto, exact_solve
from app.optimization.branch_bound import branch_bound_pareto, branch_bound_solve
from app.optimization.encoding import encode
from app.optimization.greedy import greedy_pareto, greedy_solve
from app.optimization.multiobjective import compromise, pareto_front


def _timed_solution(
    problem: Problem, selected: list[str], algorithm: str, started: float
) -> Solution:
    solution = make_solution(problem, selected, algorithm)
    payload = solution.model_dump()
    payload["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return Solution.model_validate(payload)


class BooleanILPOptimizer(Optimizer):
    """Точный 0-1 ILP для покрытия требований средствами и мерами."""

    name = "boolean-ilp"
    title = "Булево программирование (точный)"
    exact = True
    supports_pareto = True
    description = (
        "Целочисленная 0-1 модель: переменная «брать / не брать» для каждого средства. "
        "Один и тот же 0-1 метод решает обе постановки: взвешенное покрытие "
        "(Weighted Set Cover) — минимальная стоимость обязательных требований, "
        "и максимальное покрытие — как можно больше требований при заданном бюджете. "
        "Независимые группы покрытия рассчитываются отдельно."
    )

    def solve(
        self, problem: Problem, mode: OptimizeMode = "min_cost", budget: float | None = None
    ) -> Solution:
        started = time.perf_counter()
        instance = encode(problem)
        selected, _cost, _covered, _feasible = exact_solve(instance, mode=mode, budget=budget)
        return _timed_solution(problem, selected, self.name, started)

    def pareto(self, problem: Problem) -> list[Solution]:
        started = time.perf_counter()
        instance = encode(problem)
        solutions: list[Solution] = []
        for selected, _cost, _covered, _feasible in exact_pareto(instance):
            solution = make_solution(problem, selected, self.name)
            payload = solution.model_dump()
            payload["elapsed_ms"] = 0
            solutions.append(Solution.model_validate(payload))
        elapsed = (time.perf_counter() - started) * 1000
        return [solution.model_copy(update={"elapsed_ms": elapsed}) for solution in solutions]


class BranchBoundOptimizer(Optimizer):
    """Точный дискретный поиск по переменным «брать / не брать»."""

    name = "branch-bound"
    title = "Ветви и границы (точный)"
    exact = True
    supports_pareto = True
    description = (
        "Дискретная оптимизация тех же двух постановок: взвешенное покрытие "
        "и максимальное покрытие. Дерево «брать / не брать» отсекает ветвь, "
        "если она уже дороже найденного набора или нужное покрытие недостижимо; "
        "долгий расчёт можно остановить кнопкой."
    )

    def solve(
        self, problem: Problem, mode: OptimizeMode = "min_cost", budget: float | None = None
    ) -> Solution:
        started = time.perf_counter()
        instance = encode(problem)
        selected, _cost, _covered, _feasible = branch_bound_solve(
            instance, mode=mode, budget=budget
        )
        return _timed_solution(problem, selected, self.name, started)

    def pareto(self, problem: Problem) -> list[Solution]:
        started = time.perf_counter()
        instance = encode(problem)
        solutions: list[Solution] = []
        for selected, _cost, _covered, _feasible in branch_bound_pareto(instance):
            solution = make_solution(problem, selected, self.name)
            payload = solution.model_dump()
            payload["elapsed_ms"] = 0
            solutions.append(Solution.model_validate(payload))
        elapsed = (time.perf_counter() - started) * 1000
        return [solution.model_copy(update={"elapsed_ms": elapsed}) for solution in solutions]


class GreedyCoverOptimizer(Optimizer):
    """Комбинаторная эвристика покрытия множества (приближённый алгоритм)."""

    name = "greedy-cover"
    title = "Жадное покрытие (приближённый)"
    exact = False
    supports_pareto = True
    description = (
        "Комбинаторное приближение взвешенного покрытия: на каждом шаге берётся "
        "средство с лучшим отношением «новые обязательные требования / стоимость», "
        "затем убираются лишние позиции. В режиме максимального покрытия остаток "
        "бюджета тратится на ещё не закрытые требования."
    )

    def solve(
        self, problem: Problem, mode: OptimizeMode = "min_cost", budget: float | None = None
    ) -> Solution:
        started = time.perf_counter()
        instance = encode(problem)
        selected, _cost, _covered, _feasible = greedy_solve(instance, mode=mode, budget=budget)
        return _timed_solution(problem, selected, self.name, started)

    def pareto(self, problem: Problem) -> list[Solution]:
        started = time.perf_counter()
        instance = encode(problem)
        solutions: list[Solution] = []
        for selected, _cost, _covered, _feasible in greedy_pareto(instance):
            solution = make_solution(problem, selected, self.name)
            payload = solution.model_dump()
            payload["elapsed_ms"] = 0
            solutions.append(Solution.model_validate(payload))
        elapsed = (time.perf_counter() - started) * 1000
        return [solution.model_copy(update={"elapsed_ms": elapsed}) for solution in solutions]


class MultiObjectiveOptimizer(Optimizer):
    """Компромисс между стоимостью и покрытием на точном Парето-фронте."""

    name = "multiobjective"
    title = "Компромисс между стоимостью и покрытием"
    exact = True
    supports_pareto = True
    supported_modes = ("compromise",)
    description = (
        "Две локальные цели: минимальная стоимость и максимальное покрытие. "
        "Среди точек Парето-фронта берётся набор, ближайший к идеальной точке "
        "по евклидову расстоянию нормированных отклонений. "
        "Если задан бюджет, рассматриваются только наборы не дороже него."
    )

    def solve(
        self, problem: Problem, mode: OptimizeMode = "compromise", budget: float | None = None
    ) -> Solution:
        started = time.perf_counter()
        if mode != "compromise":
            raise ValueError("Многокритериальный алгоритм доступен в режиме «Компромисс»")
        instance = encode(problem)
        selected, _cost, _covered, _feasible = compromise(instance, budget=budget)
        return _timed_solution(problem, selected, self.name, started)

    def pareto(self, problem: Problem) -> list[Solution]:
        started = time.perf_counter()
        instance = encode(problem)
        solutions: list[Solution] = []
        for selected, _cost, _covered, _feasible in pareto_front(instance):
            solution = make_solution(problem, selected, self.name)
            payload = solution.model_dump()
            payload["elapsed_ms"] = 0
            solutions.append(Solution.model_validate(payload))
        elapsed = (time.perf_counter() - started) * 1000
        return [solution.model_copy(update={"elapsed_ms": elapsed}) for solution in solutions]


OPTIMIZERS: tuple[Optimizer, ...] = (
    BooleanILPOptimizer(),
    BranchBoundOptimizer(),
    GreedyCoverOptimizer(),
    MultiObjectiveOptimizer(),
)
