"""Комбинаторное жадное покрытие: цена за новое обязательное требование."""

from __future__ import annotations

from app.optimization.cancel import raise_if_stopped
from app.optimization.encoding import INF, CoverInstance, popcount


def _greedy_min_cost(instance: CoverInstance) -> list[int]:
    need = instance.mandatory_mask
    chosen: list[int] = []
    used = [False] * instance.n
    while need:
        raise_if_stopped()
        best_j = -1
        best_score = INF
        for j in range(instance.n):
            if used[j]:
                continue
            gain = popcount(instance.masks[j] & need)
            if gain == 0:
                continue
            score = instance.costs[j] / gain
            if score < best_score - 1e-12 or (
                abs(score - best_score) <= 1e-12
                and (best_j < 0 or instance.costs[j] < instance.costs[best_j])
            ):
                best_j = j
                best_score = score
        if best_j < 0:
            break
        used[best_j] = True
        chosen.append(best_j)
        need &= ~instance.masks[best_j]

    ordered = sorted(chosen, key=lambda j: instance.costs[j], reverse=True)
    kept = set(chosen)
    for j in ordered:
        if instance.costs[j] <= 1e-12:
            continue
        probe_without = 0
        for k in kept:
            if k == j:
                continue
            probe_without |= instance.masks[k]
        if (probe_without & instance.mandatory_mask) == instance.mandatory_mask:
            kept.remove(j)
    return [j for j in chosen if j in kept]


def _greedy_max_coverage(instance: CoverInstance, budget: float) -> list[int]:
    chosen = _greedy_min_cost(instance)
    cost = sum(instance.costs[j] for j in chosen)
    if cost > budget + 1e-12:
        chosen = []
        cost = 0.0
        need = instance.mandatory_mask
        used = [False] * instance.n
        while need:
            raise_if_stopped()
            best_j = -1
            best_score = INF
            for j in range(instance.n):
                if used[j] or cost + instance.costs[j] > budget + 1e-12:
                    continue
                gain = popcount(instance.masks[j] & need)
                if gain == 0:
                    continue
                score = instance.costs[j] / gain
                if score < best_score:
                    best_j = j
                    best_score = score
            if best_j < 0:
                break
            used[best_j] = True
            chosen.append(best_j)
            cost += instance.costs[best_j]
            need &= ~instance.masks[best_j]

    used = [False] * instance.n
    for j in chosen:
        used[j] = True
    cover = 0
    for j in chosen:
        cover |= instance.masks[j]
    while True:
        raise_if_stopped()
        best_j = -1
        best_ratio = -1.0
        for j in range(instance.n):
            if used[j] or cost + instance.costs[j] > budget + 1e-12:
                continue
            gain = popcount(instance.masks[j] & ~cover)
            if gain == 0:
                continue
            denom = instance.costs[j] if instance.costs[j] > 1e-12 else 1e-12
            ratio = gain / denom
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
        if best_j < 0:
            break
        used[best_j] = True
        chosen.append(best_j)
        cost += instance.costs[best_j]
        cover |= instance.masks[best_j]
    return chosen


def greedy_solve(
    instance: CoverInstance, *, mode: str, budget: float | None
) -> tuple[list[str], float, int, bool]:
    if mode == "max_coverage":
        if budget is None:
            raise ValueError("Для mode=max_coverage нужен budget")
        indices = _greedy_max_coverage(instance, budget)
    else:
        indices = _greedy_min_cost(instance)
    selected = [instance.item_ids[j] for j in indices]
    mask = 0
    cost = 0.0
    for j in indices:
        mask |= instance.masks[j]
        cost += instance.costs[j]
    covered = popcount(mask)
    feasible = (mask & instance.mandatory_mask) == instance.mandatory_mask
    if mode == "max_coverage" and budget is not None and cost > budget + 1e-12:
        feasible = False
    return selected, cost, covered, feasible


def greedy_pareto(instance: CoverInstance) -> list[tuple[list[str], float, int, bool]]:
    order = sorted(
        range(instance.n),
        key=lambda j: (
            -(
                popcount(instance.masks[j])
                / (instance.costs[j] if instance.costs[j] > 1e-12 else 1e-12)
            ),
            instance.costs[j],
            j,
        ),
    )
    points: list[tuple[list[str], float, int, bool]] = [([], 0.0, 0, instance.mandatory_mask == 0)]
    selected: list[str] = []
    mask = 0
    cost = 0.0
    for j in order:
        selected = [*selected, instance.item_ids[j]]
        mask |= instance.masks[j]
        cost += instance.costs[j]
        points.append(
            (
                list(selected),
                cost,
                popcount(mask),
                (mask & instance.mandatory_mask) == instance.mandatory_mask,
            )
        )
    points.append(greedy_solve(instance, mode="min_cost", budget=None))

    pareto: list[tuple[list[str], float, int, bool]] = []
    for cand in points:
        dominated = False
        for other in points:
            if other is cand:
                continue
            cost_le = other[1] <= cand[1] + 1e-12
            cov_ge = other[2] >= cand[2]
            strictly = other[1] < cand[1] - 1e-12 or other[2] > cand[2]
            feas_ok = other[3] or not cand[3]
            if cost_le and cov_ge and strictly and feas_ok:
                dominated = True
                break
        if dominated:
            continue
        key = (round(cand[1], 6), cand[2], cand[3])
        if any((round(p[1], 6), p[2], p[3]) == key for p in pareto):
            continue
        pareto.append(cand)
    pareto.sort(key=lambda row: (row[1], -row[2], not row[3]))
    return pareto
