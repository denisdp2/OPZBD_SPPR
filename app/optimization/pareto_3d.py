"""Точный трёхкритериальный фронт Парето для сценария защиты.

Критерии:
- стоимость за период — минимизировать;
- пользовательское время внедрения — минимизировать;
- число закрытых требований — максимизировать.

Алгоритм строит динамический фронт по маскам покрытия. Для каждой маски
хранятся только недоминируемые пары (стоимость, время), после чего выполняется
трёхкритериальная фильтрация итоговых решений.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from app.core.models import Problem, Solution
from app.core.problem import make_solution
from app.optimization.cancel import raise_if_stopped
from app.optimization.encoding import encode
from app.optimization.search import SearchBudget, components

_EPS = 1e-9
_MAX_LABELS = 150_000


@dataclass(frozen=True, slots=True)
class _Label:
    cost: float
    days: float
    selected: tuple[str, ...]


def _insert_for_same_coverage(frontier: list[_Label], candidate: _Label) -> bool:
    """Добавить метку, если она не доминируется при одинаковом покрытии."""
    for index, current in enumerate(frontier):
        if index % 1024 == 0:
            raise_if_stopped()
        if current.cost <= candidate.cost + _EPS and current.days <= candidate.days + _EPS:
            return False

    kept: list[_Label] = []
    for index, current in enumerate(frontier):
        if index % 1024 == 0:
            raise_if_stopped()
        if not (candidate.cost <= current.cost + _EPS and candidate.days <= current.days + _EPS):
            kept.append(current)
    frontier[:] = kept
    frontier.append(candidate)
    return True


class _FenwickMax:
    """Fenwick tree для максимума покрытия на префиксе времени."""

    def __init__(self, size: int) -> None:
        # -1 отличает пустой префикс от решения, закрывающего 0 требований.
        self._tree = [-1] * (size + 1)

    def update(self, index: int, value: int) -> None:
        while index < len(self._tree):
            if value > self._tree[index]:
                self._tree[index] = value
            index += index & -index

    def query(self, index: int) -> int:
        result = -1
        while index > 0:
            result = max(result, self._tree[index])
            index -= index & -index
        return result


def _global_frontier(solutions: list[Solution]) -> list[Solution]:
    """Оставить недоминируемые точки в (cost min, days min, coverage max).

    Допустимые решения имеют приоритет над недопустимыми, как и в обычном
    двухкритериальном фронте проекта: недопустимое решение не может вытеснить
    допустимое только за счёт более выгодных числовых показателей.
    """
    unique: dict[tuple[float, float, int, bool], Solution] = {}
    for solution in solutions:
        key = (
            round(float(solution.cost), 6),
            round(float(solution.total_implementation_days), 6),
            int(solution.covered_count),
            bool(solution.feasible),
        )
        unique.setdefault(key, solution)

    rows = list(unique.values())
    if not rows:
        return []

    day_values = sorted({float(row.total_implementation_days) for row in rows})
    day_index = {value: index + 1 for index, value in enumerate(day_values)}
    feasible_tree = _FenwickMax(len(day_values))
    infeasible_tree = _FenwickMax(len(day_values))

    # При равенстве стоимости сначала идут меньшие сроки, затем большее
    # покрытие; допустимые варианты идут раньше недопустимых.
    rows.sort(
        key=lambda row: (
            float(row.cost),
            float(row.total_implementation_days),
            -int(row.covered_count),
            not bool(row.feasible),
            tuple(row.selected),
        )
    )

    result: list[Solution] = []
    for row_index, row in enumerate(rows):
        if row_index % 1024 == 0:
            raise_if_stopped()
        days = float(row.total_implementation_days)
        index = day_index[days]
        best_coverage = feasible_tree.query(index)
        if not row.feasible:
            best_coverage = max(best_coverage, infeasible_tree.query(index))

        if best_coverage >= int(row.covered_count):
            continue

        result.append(row)
        target_tree = feasible_tree if row.feasible else infeasible_tree
        target_tree.update(index, int(row.covered_count))

    return sorted(
        result,
        key=lambda row: (
            float(row.cost),
            -int(row.covered_count),
            float(row.total_implementation_days),
        ),
    )


def pareto_front_3d(problem: Problem, *, max_labels: int = _MAX_LABELS) -> list[Solution]:
    """Вернуть точный недоминируемый фронт по стоимости, покрытию и времени.

    Расчёт не перебирает все комбинации в лоб: после каждого кандидата
    состояния объединяются по маске закрытых требований и внутри каждой маски
    отбрасываются доминируемые пары «стоимость / время».

    Для защиты от чрезмерного расхода памяти установлен лимит меток. При его
    превышении API возвращает понятную ошибку, а не зависает и не выдаёт
    неполный фронт за точный.
    """
    instance = encode(problem)
    limits = SearchBudget()

    def check(count: int) -> None:
        limits.check(count)
        if count > max_labels:
            raise ValueError(f"Превышен лимит {max_labels} меток 3D-фронта. Сократите набор.")

    combined: dict[tuple[int, int], list[_Label]] = {(0, 0): [_Label(0.0, 0.0, ())]}
    for group in components(instance):
        states: dict[int, list[_Label]] = {0: [_Label(0.0, 0.0, ())]}
        for item_id, cost, mask in zip(group.item_ids, group.costs, group.masks, strict=True):
            days = float(problem.implementation_days.get(item_id, 0.0))
            if not isfinite(cost) or not isfinite(days) or cost < 0 or days < 0:
                raise ValueError(f"Некорректные стоимость или срок для позиции «{item_id}»")
            snapshot = [(covered, tuple(labels)) for covered, labels in states.items()]
            for covered, labels in snapshot:
                limits.check()
                bucket = states.setdefault(covered | mask, [])
                for label in labels:
                    _insert_for_same_coverage(
                        bucket,
                        _Label(label.cost + cost, label.days + days, label.selected + (item_id,)),
                    )
            check(sum(map(len, states.values())))
        merged: dict[tuple[int, int], list[_Label]] = {}
        for (covered, hits), prefixes in combined.items():
            for mask, labels in states.items():
                limits.check()
                key = (covered + mask.bit_count(), hits + (mask & group.mandatory_mask).bit_count())
                bucket = merged.setdefault(key, [])
                for left in prefixes:
                    for right in labels:
                        _insert_for_same_coverage(
                            bucket,
                            _Label(
                                left.cost + right.cost,
                                left.days + right.days,
                                left.selected + right.selected,
                            ),
                        )
            check(sum(map(len, merged.values())))
        combined = merged
    mandatory_count = instance.mandatory_mask.bit_count()
    known_mandatory = set(problem.mandatory) <= set(instance.requirement_ids)
    candidates = [
        Solution(
            algorithm="pareto-3d-dp",
            selected=list(label.selected),
            cost=label.cost,
            covered_count=covered,
            feasible=known_mandatory and hits == mandatory_count,
            total_implementation_days=round(label.days, 1),
        )
        for (covered, hits), labels in combined.items()
        for label in labels
    ]
    return [
        make_solution(problem, row.selected, "pareto-3d-dp", include_free_items=False)
        for row in _global_frontier(candidates)
    ]
