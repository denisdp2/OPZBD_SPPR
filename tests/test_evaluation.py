from app.core.models import Item, Problem
from app.evaluation import evaluate


def make_problem() -> Problem:
    return Problem(
        requirements=["REQ-1", "REQ-2", "REQ-3"],
        mandatory=["REQ-1", "REQ-2"],
        items=[
            Item(id="ORG-01", kind="org", name="Организационная мера 1", covers=["REQ-1"]),
            Item(id="TOOL-01", kind="tool", name="Средство защиты 1", covers=["REQ-2"]),
        ],
        costs={"ORG-01": 160, "TOOL-01": 320},
        period_months=6,
    )


def test_evaluate_calculates_coverage_cost_and_sources():
    result = evaluate(make_problem())

    assert result.all_mandatory_covered is True
    assert result.uncovered_mandatory == []
    assert result.covered == ["REQ-1", "REQ-2"]
    assert result.uncovered == ["REQ-3"]
    assert result.covered_optional == 0
    assert result.total_optional == 1
    assert result.total_cost == 480
    assert result.covered_by == {
        "REQ-1": ["ORG-01"],
        "REQ-2": ["TOOL-01"],
    }


def test_evaluate_reports_uncovered_mandatory_requirements():
    problem = make_problem().model_copy(
        update={
            "items": [make_problem().items[0]],
            "costs": {"ORG-01": 160},
        }
    )

    result = evaluate(problem)

    assert result.all_mandatory_covered is False
    assert result.uncovered_mandatory == ["REQ-2"]
    assert result.covered == ["REQ-1"]
    assert result.uncovered == ["REQ-2", "REQ-3"]
    assert result.total_cost == 160


def test_evaluate_empty_selection_marks_all_requirements_uncovered():
    problem = make_problem().model_copy(update={"items": [], "costs": {}})

    result = evaluate(problem)

    assert result.all_mandatory_covered is False
    assert result.uncovered_mandatory == ["REQ-1", "REQ-2"]
    assert result.covered == []
    assert result.uncovered == ["REQ-1", "REQ-2", "REQ-3"]
    assert result.total_cost == 0


def test_evaluate_counts_all_selected_items_even_without_coverage():
    problem = make_problem().model_copy(
        update={
            "items": [
                *make_problem().items,
                Item(id="NO-COVER", kind="org", name="Мера без связи", covers=[]),
            ],
            "costs": {"ORG-01": 160, "TOOL-01": 320, "NO-COVER": 25},
        }
    )

    result = evaluate(problem)

    assert result.total_cost == 505
    assert result.covered == ["REQ-1", "REQ-2"]


def seed_client(client):
    from app.core.models import Profile, Requirement

    repo = client.app.state.repo
    for requirement_id in ("REQ-1", "REQ-2", "REQ-3"):
        repo.upsert_requirement(Requirement(id=requirement_id, title=requirement_id))
    repo.upsert_item(Item(id="ORG-01", kind="org", name="Мера 1", covers=["REQ-1"]))
    repo.upsert_item(Item(id="ORG-02", kind="org", name="Мера 2", covers=["REQ-2"]))
    repo.upsert_item(Item(id="TOOL-01", kind="tool", name="Средство 1", covers=["ORG-02"]))
    repo.upsert_profile(Profile(id="K1", name="К1", mandatory=["REQ-1", "REQ-2"]))


def test_evaluate_api_returns_result(client):
    seed_client(client)
    response = client.post("/api/evaluate", json={
        "profile_id": "K1",
        "period_months": 6,
        "requirements": ["REQ-1", "REQ-2", "REQ-3"],
        "candidates": [
            {"item_id": "ORG-01", "capex": 100, "opex_month": 10},
            {"item_id": "TOOL-01", "capex": 200, "opex_month": 20},
        ],
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["all_mandatory_covered"] is True
    assert result["covered"] == ["REQ-1", "REQ-2"]
    assert result["uncovered"] == ["REQ-3"]
    assert result["total_cost"] == 480
    assert result["covered_by"] == {"REQ-1": ["ORG-01"], "REQ-2": ["TOOL-01"]}


def test_evaluate_api_returns_422_for_unknown_item(client):
    seed_client(client)
    response = client.post("/api/evaluate", json={
        "profile_id": "K1",
        "requirements": ["REQ-1"],
        "candidates": [{"item_id": "MISSING", "capex": 0, "opex_month": 0}],
    })
    assert response.status_code == 422
    assert "MISSING" in response.json()["detail"]
