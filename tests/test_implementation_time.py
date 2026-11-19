import pytest
from pydantic import ValidationError

from app.auth.schemas import DraftPrice
from app.core.models import Candidate, Item, Problem, Requirement, Scenario
from app.core.problem import build_problem, make_solution
from app.evaluation import evaluate


class FakeRepository:
    def __init__(self):
        self.item = Item(
            id="ORG-01",
            kind="org",
            name="Управление уязвимостями",
            covers=["REQ-1"],
        )
        self.requirements = {"REQ-1": Requirement(id="REQ-1", title="Контроль уязвимостей")}

    def list_items(self, kind=None):
        return [self.item]

    def get_item(self, item_id):
        if item_id != self.item.id:
            raise KeyError(item_id)
        return self.item

    def get_requirement(self, requirement_id):
        if requirement_id not in self.requirements:
            raise KeyError(requirement_id)
        return self.requirements[requirement_id]


def test_candidate_accepts_fractional_user_entered_days():
    candidate = Candidate(item_id="ORG-01", implement_days=2.5)
    assert candidate.implement_days == 2.5


def test_candidate_rejects_negative_implementation_days():
    with pytest.raises(ValidationError):
        Candidate(item_id="ORG-01", implement_days=-0.1)


def test_legacy_candidate_defaults_implementation_days_to_zero():
    candidate = Candidate(item_id="ORG-01", capex=100, opex_month=10)
    assert candidate.implement_days == 0


def test_build_problem_carries_user_duration_into_calculation():
    scenario = Scenario(
        profile_id=None,
        requirements=["REQ-1"],
        candidates=[
            Candidate(
                item_id="ORG-01",
                capex=100,
                opex_month=10,
                implement_days=2.5,
            )
        ],
        period_months=6,
    )

    problem = build_problem(scenario, FakeRepository())

    assert problem.costs["ORG-01"] == 160
    assert problem.implementation_days["ORG-01"] == 2.5


def test_evaluation_returns_total_implementation_days():
    problem = Problem(
        requirements=["REQ-1", "REQ-2"],
        mandatory=["REQ-1"],
        items=[
            Item(id="ORG-01", kind="org", name="Мера 1", covers=["REQ-1"]),
            Item(id="TOOL-01", kind="tool", name="Средство 1", covers=["REQ-2"]),
        ],
        costs={"ORG-01": 160, "TOOL-01": 320},
        period_months=6,
        implementation_days={"ORG-01": 2.5, "TOOL-01": 1.5},
    )

    result = evaluate(problem)

    assert result.total_cost == 480
    assert result.total_implementation_days == 4.0


def test_optimizer_solution_returns_duration_of_selected_items_only():
    problem = Problem(
        requirements=["REQ-1", "REQ-2"],
        mandatory=["REQ-1"],
        items=[
            Item(id="ORG-01", kind="org", name="Мера 1", covers=["REQ-1"]),
            Item(id="TOOL-01", kind="tool", name="Средство 1", covers=["REQ-2"]),
        ],
        costs={"ORG-01": 160, "TOOL-01": 320},
        period_months=6,
        implementation_days={"ORG-01": 2.5, "TOOL-01": 1.5},
    )

    solution = make_solution(problem, ["ORG-01"], "test")

    assert solution.selected == ["ORG-01"]
    assert solution.total_implementation_days == 2.5


def test_draft_price_persists_implementation_days():
    price = DraftPrice(capex=100, opex_month=10, implement_days=3.5)
    assert price.implement_days == 3.5
