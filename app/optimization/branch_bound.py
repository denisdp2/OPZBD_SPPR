"""Точный поиск ветвей и границ по булевым переменным выбора средств."""

from __future__ import annotations

from dataclasses import replace
from typing import List, Tuple

from app.optimization.encoding import INF, CoverInstance, popcount
from app.optimization.search import Choice, SearchBudget, combine, components, frontier, pick

Point = Tuple[List[str], float, int, bool]


def _extra_cost(instance: CoverInstance, mask: int) -> float:
    missing = instance.mandatory_mask & ~mask
    if missing == 0:
        return 0.0
    extra = 0.0
    for bit in range(instance.m):
        if missing & (1 << bit) == 0:
            continue
        cheapest = INF
        for cost, item_mask in zip(instance.costs, instance.masks):
            if item_mask & (1 << bit):
                cheapest = min(cheapest, cost)
        extra = max(extra, cheapest)
    return extra


def _metrics(instance: CoverInstance, chosen: list[int], budget: float | None) -> Point:
    mask = 0
    cost = 0.0
    selected = [instance.item_ids[j] for j in chosen]
    for j in chosen:
        mask |= instance.masks[j]
        cost += instance.costs[j]
    covered = popcount(mask)
    feasible = (mask & instance.mandatory_mask) == instance.mandatory_mask
    if budget is not None and cost > budget + 1e-12:
        feasible = False
    return selected, cost, covered, feasible


def _better(mode: str, cost: float, covered: int, best_cost: float, best_covered: int) -> bool:
    if mode == "min_cost":
        if cost < best_cost - 1e-12:
            return True
        return abs(cost - best_cost) <= 1e-12 and covered > best_covered
    if covered > best_covered:
        return True
    return covered == best_covered and cost < best_cost - 1e-12


def _dominates(left: Point, right: Point) -> bool:
    cost_le = left[1] <= right[1] + 1e-12
    cov_ge = left[2] >= right[2]
    strictly = left[1] < right[1] - 1e-12 or left[2] > right[2]
    return cost_le and cov_ge and strictly and (left[3] or not right[3])


def _add_point(frontier: list[Point], point: Point) -> None:
    key = (round(point[1], 6), point[2], point[3])
    if any((round(other[1], 6), other[2], other[3]) == key for other in frontier):
        return
    if any(_dominates(other, point) for other in frontier):
        return
    frontier[:] = [other for other in frontier if not _dominates(point, other)]
    frontier.append(point)


def branch_bound_solve(
    instance: CoverInstance, *, mode: str, budget: float | None
) -> tuple[list[str], float, int, bool]:
    if mode not in {"min_cost", "max_coverage"}:
        raise ValueError("Выберите минимальную стоимость или покрытие в бюджете")
    if mode == "max_coverage" and budget is None:
        raise ValueError("Для mode=max_coverage нужен budget")

    parts = components(instance, cost_only=True)
    if not parts:
        return [], 0.0, 0, instance.mandatory_mask == 0
    if len(parts) > 1:
        limits = SearchBudget()
        options = [_component_choices(part, limits) for part in parts]
        return pick(instance, combine(instance, options, limits), mode, budget)
    if len(parts) == 1:
        instance = replace(parts[0], mandatory_mask=instance.mandatory_mask)
    if instance.n > 700:
        raise ValueError("Для этого набора используйте динамическое программирование")
    order = sorted(
        range(instance.n),
        key=lambda j: (
            instance.costs[j] / max(popcount(instance.masks[j] & instance.mandatory_mask), 1),
            instance.costs[j],
            j,
        ),
    )
    suffix_union = [0] * (instance.n + 1)
    for pos in range(instance.n - 1, -1, -1):
        suffix_union[pos] = suffix_union[pos + 1] | instance.masks[order[pos]]

    limits = SearchBudget()
    memo: dict[tuple[int, int], float] = {}
    best_chosen: list[int] = []
    best_cost = INF
    best_covered = -1
    found = False
    effort: tuple[list[int], float, int, int] = ([], 0.0, 0, -1)

    def consider(chosen: list[int], cost: float, mask: int) -> None:
        nonlocal best_chosen, best_cost, best_covered, found, effort
        if budget is not None and cost > budget + 1e-12:
            return
        covered = popcount(mask)
        feasible = (mask & instance.mandatory_mask) == instance.mandatory_mask
        if feasible and _better(mode, cost, covered, best_cost, best_covered):
            best_chosen = list(chosen)
            best_cost = cost
            best_covered = covered
            found = True
            return
        if found or feasible:
            return
        hits = popcount(mask & instance.mandatory_mask)
        _sel, effort_cost, effort_cov, effort_hits = effort
        better_effort = hits > effort_hits or (
            hits == effort_hits
            and (covered > effort_cov or (covered == effort_cov and cost < effort_cost - 1e-12))
        )
        if better_effort:
            effort = (list(chosen), cost, covered, hits)

    def dfs(pos: int, chosen: list[int], cost: float, mask: int) -> None:
        limits.check(len(memo))
        key = (pos, mask)
        previous = memo.get(key)
        if previous is not None and previous <= cost:
            return
        memo[key] = cost
        possible = mask | suffix_union[pos]
        if found and possible & instance.mandatory_mask != instance.mandatory_mask:
            return
        if not found and effort is not None:
            hits = popcount(possible & instance.mandatory_mask)
            if hits < effort[3] or (hits == effort[3] and popcount(possible) < effort[2]):
                return
        if budget is not None and cost > budget + 1e-12:
            return
        if mode == "min_cost" and found:
            if cost > best_cost + 1e-12 or cost + _extra_cost(instance, mask) > best_cost + 1e-12:
                return
        if mode == "max_coverage" and found:
            if popcount(mask | suffix_union[pos]) < best_covered:
                return
        if pos == instance.n:
            consider(chosen, cost, mask)
            return
        j = order[pos]
        chosen.append(j)
        dfs(pos + 1, chosen, cost + instance.costs[j], mask | instance.masks[j])
        chosen.pop()
        dfs(pos + 1, chosen, cost, mask)

    dfs(0, [], 0.0, 0)
    if found:
        return _metrics(instance, best_chosen, budget)
    chosen, cost, covered, _hits = effort
    selected = [instance.item_ids[j] for j in chosen]
    return selected, cost, covered, False


def _component_choices(instance: CoverInstance, limits: SearchBudget) -> list[Choice]:
    rows = {0: Choice(0, 0.0, ())}
    memo: dict[tuple[int, int], float] = {}
    stack = [(0, Choice(0, 0.0, ()))]
    while stack:
        pos, row = stack.pop()
        limits.check(len(memo))
        key = (pos, row.mask)
        if key in memo and memo[key] <= row.cost:
            continue
        memo[key] = row.cost
        previous = rows.get(row.mask)
        if previous is None or row.cost < previous.cost:
            rows[row.mask] = row
        if pos == instance.n:
            continue
        stack.append((pos + 1, row))
        stack.append(
            (
                pos + 1,
                Choice(
                    row.mask | instance.masks[pos],
                    row.cost + instance.costs[pos],
                    row.selected + (instance.item_ids[pos],),
                ),
            )
        )
    return list(rows.values())


def _component_pareto(instance: CoverInstance, limits: SearchBudget) -> list[Choice]:
    if instance.n > 700:
        return _component_choices(instance, limits)
    order = sorted(
        range(instance.n),
        key=lambda j: (instance.costs[j] / max(popcount(instance.masks[j]), 1), j),
    )
    suffix = [0] * (instance.n + 1)
    for pos in range(instance.n - 1, -1, -1):
        suffix[pos] = suffix[pos + 1] | instance.masks[order[pos]]
    points: list[Point] = []
    memo: dict[tuple[int, int], float] = {}

    def dfs(pos: int, selected: list[str], cost: float, mask: int) -> None:
        limits.check(len(memo))
        key = (pos, mask)
        previous = memo.get(key)
        if previous is not None and previous <= cost:
            return
        memo[key] = cost
        possible = mask | suffix[pos]
        upper: Point = (
            [],
            cost,
            popcount(possible),
            possible & instance.mandatory_mask == instance.mandatory_mask,
        )
        for point in points:
            if _dominates(point, upper) or point[1:] == upper[1:]:
                return
        _add_point(
            points,
            (
                list(selected),
                cost,
                popcount(mask),
                mask & instance.mandatory_mask == instance.mandatory_mask,
            ),
        )
        if pos == instance.n:
            return
        j = order[pos]
        selected.append(instance.item_ids[j])
        dfs(pos + 1, selected, cost + instance.costs[j], mask | instance.masks[j])
        selected.pop()
        dfs(pos + 1, selected, cost, mask)

    dfs(0, [], 0.0, 0)
    masks = dict(zip(instance.item_ids, instance.masks))
    rows = []
    for selected, cost, _, _ in points:
        mask = 0
        for item_id in selected:
            mask |= masks[item_id]
        rows.append(Choice(mask, cost, tuple(selected)))
    return rows


def branch_bound_pareto(instance: CoverInstance) -> list[Point]:
    limits = SearchBudget()
    groups = [_component_pareto(group, limits) for group in components(instance, cost_only=True)]
    return frontier(instance, combine(instance, groups, limits))
