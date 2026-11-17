"""Точное булево (0-1) программирование: динамика по маске закрытых требований.

min Σ_j c_j x_j,  x_j ∈ {0,1},
Σ_{j: i ∈ covers_j} x_j ≥ 1 для каждого обязательного i.

Либо max Σ_i y_i при Σ_j c_j x_j ≤ budget и y_i = 1 для обязательных i.
"""

from __future__ import annotations

from app.optimization.cancel import raise_if_stopped
from app.optimization.encoding import INF, CoverInstance, popcount


def _min_cost_table(
    instance: CoverInstance,
) -> tuple[dict[int, float], dict[int, tuple[int, int]]]:
    dp: dict[int, float] = {0: 0.0}
    parent: dict[int, tuple[int, int]] = {0: (-1, 0)}

    for index, (cost, mask) in enumerate(zip(instance.costs, instance.masks, strict=True)):
        raise_if_stopped()
        if mask == 0:
            continue
        snapshot = list(dp.items())
        for step, (covered, current) in enumerate(snapshot):
            if step % 2048 == 0:
                raise_if_stopped()
            nxt = covered | mask
            total = current + cost
            previous = dp.get(nxt)
            if previous is None or total < previous:
                dp[nxt] = total
                parent[nxt] = (index, covered)
    return dp, parent


def _reconstruct(
    instance: CoverInstance, parent: dict[int, tuple[int, int]], mask: int
) -> list[str]:
    selected: list[str] = []
    seen: set[int] = set()
    current = mask
    while current:
        index, prev = parent[current]
        if index < 0 or index in seen:
            break
        selected.append(instance.item_ids[index])
        seen.add(index)
        if prev == current:
            break
        current = prev
    selected.reverse()
    return selected


def _better_min_cost(cost: float, covered: int, best_cost: float, best_covered: int) -> bool:
    if cost < best_cost - 1e-12:
        return True
    return abs(cost - best_cost) <= 1e-12 and covered > best_covered


def _better_max_coverage(covered: int, cost: float, best_covered: int, best_cost: float) -> bool:
    if covered > best_covered:
        return True
    return covered == best_covered and cost < best_cost - 1e-12


def _pick_from_dp(
    instance: CoverInstance,
    dp: dict[int, float],
    parent: dict[int, tuple[int, int]],
    *,
    mode: str,
    budget: float | None,
) -> tuple[list[str], float, int, bool]:
    mandatory = instance.mandatory_mask
    best_mask = 0
    best_cost = INF
    best_covered = -1
    found_feasible = False

    for mask, cost in dp.items():
        if budget is not None and cost > budget + 1e-12:
            continue
        feasible = (mask & mandatory) == mandatory
        if not feasible:
            continue
        covered = popcount(mask)
        if mode == "min_cost":
            if _better_min_cost(cost, covered, best_cost, best_covered):
                best_mask, best_cost, best_covered = mask, cost, covered
                found_feasible = True
        elif _better_max_coverage(covered, cost, best_covered, best_cost):
            best_mask, best_cost, best_covered = mask, cost, covered
            found_feasible = True

    if found_feasible:
        return _reconstruct(instance, parent, best_mask), best_cost, best_covered, True
    return _best_effort_from_dp(instance, dp, parent, budget)


def _best_effort_from_dp(
    instance: CoverInstance,
    dp: dict[int, float],
    parent: dict[int, tuple[int, int]],
    budget: float | None,
) -> tuple[list[str], float, int, bool]:
    mandatory = instance.mandatory_mask
    best_mask = 0
    best_cost = 0.0 if dp.get(0) == 0 else INF
    best_mandatory = -1
    best_covered = -1
    for mask, cost in dp.items():
        if budget is not None and cost > budget + 1e-12:
            continue
        mandatory_hits = popcount(mask & mandatory)
        covered = popcount(mask)
        better = mandatory_hits > best_mandatory or (
            mandatory_hits == best_mandatory
            and (covered > best_covered or (covered == best_covered and cost < best_cost - 1e-12))
        )
        if better:
            best_mask, best_cost, best_mandatory, best_covered = (
                mask,
                cost,
                mandatory_hits,
                covered,
            )
    if best_cost >= INF:
        return [], 0.0, 0, False
    return _reconstruct(instance, parent, best_mask), best_cost, best_covered, False


def _dominates(
    left_cost: float,
    left_cov: int,
    left_ok: bool,
    right_cost: float,
    right_cov: int,
    right_ok: bool,
) -> bool:
    cost_le = left_cost <= right_cost + 1e-12
    cov_ge = left_cov >= right_cov
    strictly = left_cost < right_cost - 1e-12 or left_cov > right_cov
    return cost_le and cov_ge and strictly and (left_ok or not right_ok)


def _dp_pareto(
    instance: CoverInstance, dp: dict[int, float], parent: dict[int, tuple[int, int]]
) -> list[tuple[list[str], float, int, bool]]:
    mandatory = instance.mandatory_mask
    compact: list[tuple[float, int, int, bool]] = []
    for step, (mask, cost) in enumerate(dp.items()):
        if step % 2048 == 0:
            raise_if_stopped()
        covered = popcount(mask)
        feasible = (mask & mandatory) == mandatory
        key = (round(cost, 6), covered, feasible)
        if any((round(other[0], 6), other[1], other[3]) == key for other in compact):
            continue
        if any(
            _dominates(other[0], other[1], other[3], cost, covered, feasible) for other in compact
        ):
            continue
        compact = [
            other
            for other in compact
            if not _dominates(cost, covered, feasible, other[0], other[1], other[3])
        ]
        compact.append((cost, covered, mask, feasible))
    compact.sort(key=lambda row: (row[0], -row[1], not row[3]))
    return [
        (_reconstruct(instance, parent, mask), cost, covered, feasible)
        for cost, covered, mask, feasible in compact
    ]


def exact_solve(
    instance: CoverInstance, *, mode: str, budget: float | None
) -> tuple[list[str], float, int, bool]:
    if mode == "max_coverage" and budget is None:
        raise ValueError("Для mode=max_coverage нужен budget")
    dp, parent = _min_cost_table(instance)
    return _pick_from_dp(instance, dp, parent, mode=mode, budget=budget)


def exact_pareto(instance: CoverInstance) -> list[tuple[list[str], float, int, bool]]:
    dp, parent = _min_cost_table(instance)
    return _dp_pareto(instance, dp, parent)
