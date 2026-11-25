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
    problem: Problem,
    selected: list[str],
    algorithm: str,
    started: float,
    *,
    include_free_items: bool = True,
) -> Solution:
    solution = make_solution(problem, selected, algorithm, include_free_items=include_free_items)
    payload = solution.model_dump()
    payload["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return Solution.model_validate(payload)


class BooleanILPOptimizer(Optimizer):

    name = "boolean-ilp"
    title = "Булево программирование"
    exact = True
    supports_pareto = True
    description = ""

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
    """ дискретный поиск по переменным «брать / не брать»."""

    name = "branch-bound"
    title = "Ветви и границы"
    exact = True
    supports_pareto = True
    description = ""

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
    title = "Жадное покрытие"
    exact = False
    supports_pareto = True
    description = ""

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
    """Компромисс по стоимости, покрытию и сроку внедрения."""

    name = "multiobjective"
    title = "Компромисс по стоимости, покрытию и сроку"
    exact = True
    supports_pareto = True
    supported_modes = ("compromise",)
    description = ""

    def solve(
        self, problem: Problem, mode: OptimizeMode = "compromise", budget: float | None = None
    ) -> Solution:
        started = time.perf_counter()
        if mode != "compromise":
            raise ValueError("Многокритериальный алгоритм доступен в режиме «Компромисс»")
        selected = compromise(problem, budget=budget)
        return _timed_solution(problem, selected, self.name, started, include_free_items=False)

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
