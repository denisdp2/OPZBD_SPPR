"""Точное покрытие: динамика по маскам внутри независимых групп требований."""

from __future__ import annotations

from app.optimization.encoding import CoverInstance
from app.optimization.search import Choice, SearchBudget, combine, components, frontier, pick


def _choices(instance: CoverInstance, limits: SearchBudget) -> list[Choice]:
    states = {0: Choice(0, 0.0, ())}
    for item_id, cost, mask in zip(instance.item_ids, instance.costs, instance.masks):
        limits.check(len(states))
        for step, row in enumerate(list(states.values())):
            if step % 1024 == 0:
                limits.check(len(states))
            covered = row.mask | mask
            total = row.cost + cost
            previous = states.get(covered)
            if previous is None or total < previous.cost:
                states[covered] = Choice(covered, total, row.selected + (item_id,))
    limits.check(len(states))
    return list(states.values())


def _all_choices(instance: CoverInstance) -> list[Choice]:
    limits = SearchBudget()
    groups = [_choices(group, limits) for group in components(instance, cost_only=True)]
    return combine(instance, groups, limits)


def exact_solve(
    instance: CoverInstance, *, mode: str, budget: float | None
) -> tuple[list[str], float, int, bool]:
    return pick(instance, _all_choices(instance), mode, budget)


def exact_pareto(instance: CoverInstance) -> list[tuple[list[str], float, int, bool]]:
    return frontier(instance, _all_choices(instance))
