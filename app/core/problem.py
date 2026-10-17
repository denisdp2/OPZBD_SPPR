"""Сборка задачи (Problem) из пользовательского сценария и данных хранилища."""

from __future__ import annotations

from app.core.interfaces import Repository
from app.core.models import Problem, Scenario, Solution


class ScenarioError(ValueError):
    """Сценарий ссылается на несуществующие данные или противоречив."""


def item_cost(capex: float, opex_month: float, period_months: float) -> float:
    """Полная стоимость элемента за период: внедрение + эксплуатация × период."""
    raise NotImplementedError


def build_problem(scenario: Scenario, repo: Repository) -> Problem:
    """Превратить Scenario в самодостаточную Problem.

    * подтянуть элементы из хранилища по id кандидатов;
    * определить обязательные требования (явный список или профиль);
    * посчитать стоимость каждого элемента за период;
    * оставить в covers только рассматриваемые требования.
    Бросает ScenarioError при ссылке на несуществующие данные.
    """
    raise NotImplementedError


def make_solution(problem: Problem, selected: list[str], algorithm: str) -> Solution:
    """Посчитать стоимость и покрытие набора (для использования в алгоритмах)."""
    raise NotImplementedError
