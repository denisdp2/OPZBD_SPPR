"""Точный поиск ветвей и границ по булевым переменным выбора средств."""

from __future__ import annotations

from app.optimization.cancel import raise_if_stopped
from app.optimization.encoding import INF, CoverInstance

Point = tuple[list[str], float, int, bool]


def _extra_cost(instance: CoverInstance, mask: int) -> float:
    missing = instance.mandatory_mask & ~mask
    if missing == 0:
        return 0.0
    extra = 0.0
    for bit in range(instance.m):
        if missing & (1 << bit) == 0:
            continue
        cheapest = INF
        for cost, item_mask in zip(instance.costs, instance.masks, strict=True):
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
    covered = mask.bit_count()
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
    if mode == "max_coverage" and budget is None:
        raise ValueError("Для mode=max_coverage нужен budget")

    order = sorted(
        range(instance.n),
        key=lambda j: (
            instance.costs[j] / max((instance.masks[j] & instance.mandatory_mask).bit_count(), 1),
            instance.costs[j],
            j,
        ),
    )
    suffix_union = [0] * (instance.n + 1)
    for pos in range(instance.n - 1, -1, -1):
        suffix_union[pos] = suffix_union[pos + 1] | instance.masks[order[pos]]

    best_chosen: list[int] = []
    best_cost = INF
    best_covered = -1
    found = False
    effort: tuple[list[int], float, int, int] = ([], 0.0, 0, -1)

    def consider(chosen: list[int], cost: float, mask: int) -> None:
        nonlocal best_chosen, best_cost, best_covered, found, effort
        if budget is not None and cost > budget + 1e-12:
            return
        covered = mask.bit_count()
        feasible = (mask & instance.mandatory_mask) == instance.mandatory_mask
        if feasible and _better(mode, cost, covered, best_cost, best_covered):
            best_chosen = list(chosen)
            best_cost = cost
            best_covered = covered
            found = True
            return
        if found or feasible:
            return
        hits = (mask & instance.mandatory_mask).bit_count()
        _sel, effort_cost, effort_cov, effort_hits = effort
        better_effort = hits > effort_hits or (
            hits == effort_hits
            and (covered > effort_cov or (covered == effort_cov and cost < effort_cost - 1e-12))
        )
        if better_effort:
            effort = (list(chosen), cost, covered, hits)

    def dfs(pos: int, chosen: list[int], cost: float, mask: int) -> None:
        raise_if_stopped()
        if budget is not None and cost > budget + 1e-12:
            return
        if mode == "min_cost" and found:
            if cost > best_cost + 1e-12 or cost + _extra_cost(instance, mask) > best_cost + 1e-12:
                return
        if mode == "max_coverage" and found:
            if (mask | suffix_union[pos]).bit_count() < best_covered:
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


def branch_bound_pareto(instance: CoverInstance) -> list[Point]:
    frontier: list[Point] = []

    def dfs(pos: int, chosen: list[int], cost: float, mask: int) -> None:
        raise_if_stopped()
        if pos == instance.n:
            _add_point(
                frontier,
                (
                    [instance.item_ids[j] for j in chosen],
                    cost,
                    mask.bit_count(),
                    (mask & instance.mandatory_mask) == instance.mandatory_mask,
                ),
            )
            return
        chosen.append(pos)
        dfs(pos + 1, chosen, cost + instance.costs[pos], mask | instance.masks[pos])
        chosen.pop()
        dfs(pos + 1, chosen, cost, mask)

    dfs(0, [], 0.0, 0)
    frontier.sort(key=lambda row: (row[1], -row[2], not row[3]))
    return frontier
