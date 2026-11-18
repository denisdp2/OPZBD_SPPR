"""Сборка задачи из сценария пользователя и подсчёт готового набора."""

from __future__ import annotations

from app.core.cover import expand_covers
from app.core.interfaces import NotFoundError, Repository
from app.core.models import EvaluationResult, Problem, Scenario, Solution


class ScenarioError(ValueError):
    """Сценарий ссылается на несуществующие данные или противоречив."""


def item_cost(capex: float, opex_month: float, period_months: float) -> float:
    """Полная стоимость элемента за период: внедрение + эксплуатация × период."""
    return float(capex) + float(opex_month) * float(period_months)


def build_problem(scenario: Scenario, repo: Repository) -> Problem:
    """Собрать данные для расчёта из сценария и справочников."""
    requirements = list(dict.fromkeys(scenario.requirements))
    known = set(requirements)
    for req_id in requirements:
        try:
            repo.get_requirement(req_id)
        except NotFoundError as exc:
            raise ScenarioError(f"Требование «{req_id}» не найдено") from exc

    if scenario.mandatory is not None:
        mandatory = list(dict.fromkeys(scenario.mandatory))
        for req_id in mandatory:
            if req_id in known:
                continue
            try:
                repo.get_requirement(req_id)
            except NotFoundError as exc:
                raise ScenarioError(f"Требование «{req_id}» не найдено") from exc
            raise ScenarioError(f"Обязательное требование «{req_id}» не входит в рассматриваемые")
    elif scenario.profile_id:
        try:
            profile = repo.get_profile(scenario.profile_id)
        except NotFoundError as exc:
            raise ScenarioError(f"Профиль «{scenario.profile_id}» не найден") from exc
        mandatory = [req_id for req_id in dict.fromkeys(profile.mandatory) if req_id in known]
    else:
        mandatory = []

    catalog = repo.list_items()
    items = []
    costs: dict[str, float] = {}
    seen: set[str] = set()
    for candidate in scenario.candidates:
        if candidate.item_id in seen:
            continue
        seen.add(candidate.item_id)
        try:
            source = repo.get_item(candidate.item_id)
        except NotFoundError as exc:
            raise ScenarioError(f"Элемент «{candidate.item_id}» не найден") from exc
        covers = [req_id for req_id in expand_covers(source, catalog, known) if req_id in known]
        items.append(source.model_copy(update={"covers": covers}))
        costs[source.id] = item_cost(candidate.capex, candidate.opex_month, scenario.period_months)

    return Problem(
        requirements=requirements,
        mandatory=mandatory,
        items=items,
        costs=costs,
        period_months=scenario.period_months,
    )


def evaluate_problem(problem: Problem) -> EvaluationResult:
    covered_by: dict[str, list[str]] = {}
    for item in problem.items:
        for requirement in item.covers:
            covered_by.setdefault(requirement, []).append(item.id)
    mandatory = set(problem.mandatory)
    covered = [key for key in problem.requirements if key in covered_by]
    uncovered = [key for key in problem.requirements if key not in covered_by]
    uncovered_mandatory = [key for key in problem.mandatory if key not in covered_by]
    return EvaluationResult(
        all_mandatory_covered=not uncovered_mandatory,
        uncovered_mandatory=uncovered_mandatory,
        covered=covered,
        uncovered=uncovered,
        covered_optional=sum(key not in mandatory for key in covered),
        total_optional=len(problem.requirements) - len(mandatory),
        total_cost=sum(problem.costs.values()),
        covered_by=covered_by,
    )


def make_solution(problem: Problem, selected: list[str], algorithm: str) -> Solution:
    """Посчитать стоимость и покрытие набора."""
    by_id = {item.id: item for item in problem.items}
    known = set(problem.requirements)
    chosen: list[str] = []
    seen: set[str] = set()
    covered: set[str] = set()
    cost = 0.0
    for item_id in selected:
        if item_id in seen:
            continue
        seen.add(item_id)
        item = by_id.get(item_id)
        if item is None:
            continue
        chosen.append(item_id)
        cost += float(problem.costs.get(item_id, 0.0))
        for req_id in expand_covers(item, problem.items, known):
            if req_id in known:
                covered.add(req_id)
    for item in problem.items:
        if item.id in seen:
            continue
        if float(problem.costs.get(item.id, 0.0)) > 1e-12:
            continue
        extra = [req_id for req_id in expand_covers(item, problem.items, known) if req_id in known]
        if not extra:
            continue
        seen.add(item.id)
        chosen.append(item.id)
        covered.update(extra)
    return Solution(
        algorithm=algorithm,
        selected=chosen,
        cost=cost,
        covered_count=len(covered),
        feasible=set(problem.mandatory) <= covered,
    )
