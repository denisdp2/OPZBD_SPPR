from app.core.models import Candidate, Item, Profile, Requirement, Scenario
from app.core.problem import build_problem, item_cost, make_solution
from app.storage.sqlite import SQLiteRepository


def _repo(tmp_path):
    repo = SQLiteRepository(tmp_path / "catalog.sqlite3")
    repo.upsert_requirement(Requirement(id="REQ-01", title="A"))
    repo.upsert_requirement(Requirement(id="REQ-02", title="B"))
    repo.upsert_item(Item(id="t1", kind="tool", name="One", covers=["REQ-01", "REQ-02", "OTHER"]))
    repo.upsert_profile(Profile(id="p1", name="P", mandatory=["REQ-01"]))
    return repo


def test_item_cost_is_capex_plus_opex_times_period():
    assert item_cost(100, 10, 12) == 220


def test_build_problem_filters_covers_and_uses_profile(tmp_path):
    repo = _repo(tmp_path)
    problem = build_problem(
        Scenario(
            profile_id="p1",
            requirements=["REQ-01", "REQ-02"],
            period_months=12,
            candidates=[Candidate(item_id="t1", capex=100, opex_month=10)],
        ),
        repo,
    )
    assert problem.mandatory == ["REQ-01"]
    assert problem.costs["t1"] == 220
    assert problem.items[0].covers == ["REQ-01", "REQ-02"]


def test_make_solution_marks_feasible_when_mandatory_covered(tmp_path):
    repo = _repo(tmp_path)
    problem = build_problem(
        Scenario(
            mandatory=["REQ-01"],
            requirements=["REQ-01", "REQ-02"],
            candidates=[Candidate(item_id="t1", capex=50, opex_month=0)],
        ),
        repo,
    )
    solution = make_solution(problem, ["t1"], "test")
    assert solution.feasible is True
    assert solution.covered_count == 2
    assert solution.cost == 50
