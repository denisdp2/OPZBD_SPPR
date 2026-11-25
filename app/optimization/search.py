"""Независимые группы покрытия и ограничения точного поиска."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.optimization.cancel import raise_if_stopped
from app.optimization.encoding import CoverInstance, popcount

MAX_STATES = 200_000
MAX_SECONDS = 10.0


class SearchBudget:
    def __init__(self) -> None:
        self.started = perf_counter()

    def check(self, size: int = 0) -> None:
        raise_if_stopped()
        if size > MAX_STATES or perf_counter() - self.started > MAX_SECONDS:
            raise ValueError(
                "Превышен предел точного поиска. Сократите выбранный набор "
                "или используйте жадный алгоритм. Приближённый результат не вычислялся."
            )


@dataclass(frozen=True)
class Choice:
    mask: int
    cost: float
    selected: tuple[str, ...]


def components(instance: CoverInstance, *, cost_only: bool = False) -> list[CoverInstance]:
    parents = list(range(instance.n))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    active = set(range(instance.n))
    if cost_only:
        cheapest: dict[int, int] = {}
        for index, mask in enumerate(instance.masks):
            previous = cheapest.get(mask)
            if previous is None or instance.costs[index] < instance.costs[previous]:
                cheapest[mask] = index
        active = set(cheapest.values())
    owners: dict[int, int] = {}
    for index, mask in enumerate(instance.masks):
        raise_if_stopped()
        if index not in active:
            continue
        while mask:
            bit = mask & -mask
            if bit in owners:
                parents[root(index)] = root(owners[bit])
            else:
                owners[bit] = index
            mask ^= bit
    groups: dict[int, list[int]] = {}
    for index, mask in enumerate(instance.masks):
        if mask and index in active:
            groups.setdefault(root(index), []).append(index)
    result = []
    for indexes in groups.values():
        union = 0
        for index in indexes:
            union |= instance.masks[index]
        result.append(
            CoverInstance(
                item_ids=tuple(instance.item_ids[i] for i in indexes),
                costs=tuple(instance.costs[i] for i in indexes),
                masks=tuple(instance.masks[i] for i in indexes),
                requirement_ids=instance.requirement_ids,
                mandatory_mask=instance.mandatory_mask & union,
                full_mask=union,
            )
        )
    return result


def combine(
    instance: CoverInstance, groups: list[list[Choice]], limits: SearchBudget
) -> list[Choice]:
    rows = [Choice(0, 0.0, ())]
    for group in groups:
        merged: dict[tuple[int, int], Choice] = {}
        for left in rows:
            limits.check(len(merged))
            for right in group:
                mask = left.mask | right.mask
                key = (popcount(mask & instance.mandatory_mask), popcount(mask))
                cost = left.cost + right.cost
                previous = merged.get(key)
                if previous is None or cost < previous.cost:
                    merged[key] = Choice(mask, cost, left.selected + right.selected)
        limits.check(len(merged))
        rows = list(merged.values())
    return rows


def frontier(
    instance: CoverInstance, rows: list[Choice]
) -> list[tuple[list[str], float, int, bool]]:
    result: list[tuple[list[str], float, int, bool]] = []
    best = {True: -1, False: -1}
    ordered = sorted(rows, key=lambda row: (row.cost, -popcount(row.mask)))
    seen = set()
    for row in ordered:
        raise_if_stopped()
        covered = popcount(row.mask)
        feasible = row.mask & instance.mandatory_mask == instance.mandatory_mask
        key = (row.cost, covered, feasible)
        if key in seen:
            continue
        seen.add(key)
        if best[feasible] >= covered:
            continue
        if not feasible and any(
            ok and cost <= row.cost and cov >= covered and (cost < row.cost or cov > covered)
            for _, cost, cov, ok in result
        ):
            continue
        result.append((list(row.selected), row.cost, covered, feasible))
        best[feasible] = covered
    return result


def pick(
    instance: CoverInstance, rows: list[Choice], mode: str, budget: float | None
) -> tuple[list[str], float, int, bool]:
    if mode not in {"min_cost", "max_coverage"}:
        raise ValueError("Выберите минимальную стоимость или покрытие в бюджете")
    if mode == "max_coverage" and budget is None:
        raise ValueError("Для mode=max_coverage нужен budget")
    rows = [row for row in rows if budget is None or row.cost <= budget + 1e-12]
    feasible = [
        row for row in rows if row.mask & instance.mandatory_mask == instance.mandatory_mask
    ]
    if feasible:
        key = (
            (lambda row: (row.cost, -popcount(row.mask)))
            if mode == "min_cost"
            else (lambda row: (-popcount(row.mask), row.cost))
        )
        chosen = min(feasible, key=key)
    else:
        chosen = min(
            rows,
            key=lambda row: (
                -popcount(row.mask & instance.mandatory_mask),
                -popcount(row.mask),
                row.cost,
            ),
            default=Choice(0, 0.0, ()),
        )
    return list(chosen.selected), chosen.cost, popcount(chosen.mask), bool(feasible)
