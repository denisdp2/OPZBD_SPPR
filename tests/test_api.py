def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_openapi_available(client):
    assert client.get("/openapi.json").status_code == 200


def test_evaluate_uses_catalog_coverage_and_cost(client):
    repo = client.app.state.repo
    from app.core.models import DataBundle

    repo.import_bundle(
        DataBundle.model_validate(
            {
                "requirements": [
                    {"id": "Q.1", "title": "Required"},
                    {"id": "Q.2", "title": "Optional"},
                ],
                "items": [{"id": "tool-1", "kind": "tool", "name": "Tool", "covers": ["Q.1"]}],
                "profiles": [{"id": "p", "name": "Profile", "mandatory": ["Q.1"]}],
            }
        )
    )
    scenario = {
        "requirements": ["Q.1", "Q.2"],
        "profile_id": "p",
        "period_months": 6,
        "candidates": [{"item_id": "tool-1", "capex": 100, "opex_month": 10}],
    }
    response = client.post("/api/evaluate", json=scenario)
    assert response.status_code == 200
    assert response.json() == {
        "all_mandatory_covered": True,
        "uncovered_mandatory": [],
        "covered": ["Q.1"],
        "uncovered": ["Q.2"],
        "covered_optional": 0,
        "total_optional": 1,
        "total_cost": 160,
        "covered_by": {"Q.1": ["tool-1"]},
    }
    scenario["requirements"] = ["unknown"]
    assert client.post("/api/evaluate", json=scenario).status_code == 422
