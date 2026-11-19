def test_three_dimensional_pareto_endpoint_returns_duration_points(client):
    from app.core.models import DataBundle

    client.app.state.repo.import_bundle(
        DataBundle.model_validate(
            {
                "requirements": [
                    {"id": "R1", "title": "R1"},
                    {"id": "R2", "title": "R2"},
                ],
                "items": [
                    {"id": "A", "kind": "org", "name": "A", "covers": ["R1"]},
                    {"id": "B", "kind": "org", "name": "B", "covers": ["R1"]},
                    {"id": "C", "kind": "org", "name": "C", "covers": ["R2"]},
                    {"id": "D", "kind": "tool", "name": "D", "covers": ["R1", "R2"]},
                ],
                "profiles": [],
            }
        )
    )
    body = {
        "algorithm": "boolean-ilp",
        "mode": "min_cost",
        "scenario": {
            "requirements": ["R1", "R2"],
            "mandatory": ["R1"],
            "period_months": 12,
            "candidates": [
                {"item_id": "A", "capex": 10, "opex_month": 0, "implement_days": 5},
                {"item_id": "B", "capex": 20, "opex_month": 0, "implement_days": 1},
                {"item_id": "C", "capex": 5, "opex_month": 0, "implement_days": 1},
                {"item_id": "D", "capex": 20, "opex_month": 0, "implement_days": 10},
            ],
        },
    }

    response = client.post("/api/pareto/3d", json=body)
    assert response.status_code == 200, response.text
    points = response.json()
    assert isinstance(points, list) and points
    assert all("total_implementation_days" in point for point in points)
    assert any(
        point["cost"] == 15
        and point["covered_count"] == 2
        and point["total_implementation_days"] == 6
        for point in points
    )
