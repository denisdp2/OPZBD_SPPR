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

from app.core.cover import expand_covers
from app.core.models import Problem, Solution
from app.core.problem import make_solution
from app.optimization.cancel import raise_if_stopped

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
        if not (
            candidate.cost <= current.cost + _EPS
            and candidate.days <= current.days + _EPS
        ):
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
    requirement_ids = tuple(dict.fromkeys(problem.requirements))
    requirement_index = {requirement_id: bit for bit, requirement_id in enumerate(requirement_ids)}
    known = set(requirement_ids)

    candidates: list[tuple[str, float, float, int]] = []
    free_mask = 0
    free_days = 0.0
    for item in problem.items:
        mask = 0
        for requirement_id in expand_covers(item, problem.items, known):
            bit = requirement_index.get(requirement_id)
            if bit is not None:
                mask |= 1 << bit
        if mask == 0:
            continue

        cost = float(problem.costs.get(item.id, 0.0))
        days = float(getattr(problem, "implementation_days", {}).get(item.id, 0.0))
        if not isfinite(cost) or not isfinite(days) or cost < 0 or days < 0:
            raise ValueError(f"Некорректные стоимость или срок внедрения для позиции «{item.id}»")

        # make_solution автоматически включает бесплатные позиции, закрывающие
        # хотя бы одно требование. Фиксируем их в каждой альтернативе заранее,
        # чтобы маска DP и фактические метрики Solution всегда совпадали.
        if cost <= 1e-12:
            free_mask |= mask
            free_days += days
            continue
        candidates.append((item.id, cost, days, mask))

    # mask -> локальный недоминируемый набор пар (стоимость, дни).
    states: dict[int, list[_Label]] = {free_mask: [_Label(0.0, free_days, ())]}
    for item_id, item_cost, item_days, item_mask in candidates:
        raise_if_stopped()
        snapshot = [(mask, tuple(labels)) for mask, labels in states.items()]
        next_states = {mask: list(labels) for mask, labels in states.items()}

        for covered_mask, labels in snapshot:
            raise_if_stopped()
            next_mask = covered_mask | item_mask
            bucket = next_states.setdefault(next_mask, [])
            for label_index, label in enumerate(labels):
                if label_index % 1024 == 0:
                    raise_if_stopped()
                new_label = _Label(
                    cost=label.cost + item_cost,
                    days=label.days + item_days,
                    selected=label.selected + (item_id,),
                )
                _insert_for_same_coverage(bucket, new_label)

        states = {mask: labels for mask, labels in next_states.items() if labels}
        label_count = sum(len(labels) for labels in states.values())
        if label_count > max_labels:
            raise ValueError(
                "Трёхкритериальный фронт слишком велик для точного расчёта "
                f"(превышен лимит {max_labels:,} состояний). "
                "Сократите число выбранных позиций или используйте обычный 2D-фронт."
            )

    # make_solution применяет общие правила проекта, включая автоматическое
    # включение бесплатных мер, если они закрывают требования.
    solutions: list[Solution] = []
    seen_solutions: set[tuple[float, float, int, bool]] = set()
    for labels in states.values():
        for label in labels:
            raise_if_stopped()
            solution = make_solution(problem, list(label.selected), "pareto-3d-dp")
            key = (
                round(float(solution.cost), 6),
                round(float(solution.total_implementation_days), 6),
                int(solution.covered_count),
                bool(solution.feasible),
            )
            if key not in seen_solutions:
                seen_solutions.add(key)
                solutions.append(solution)

    return _global_frontier(solutions)
