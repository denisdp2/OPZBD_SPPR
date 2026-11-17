def test_admin_api_requires_login(client):
    assert client.get("/api/admin/gaps").status_code == 401


def test_login_rejects_bad_password(client):
    res = client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
    assert res.status_code == 401


def test_admin_can_reach_admin_api(client):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin"
    assert client.get("/api/admin/gaps").status_code == 200


def test_user_cannot_reach_admin_api(client):
    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    me = client.get("/api/auth/me").json()
    assert me["role"] == "user"
    res = client.get("/api/admin/gaps")
    assert res.status_code == 403


def test_logout_clears_session(client):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/admin/gaps").status_code == 401


def test_admin_page_requires_admin(client):
    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].endswith("/")

    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"].endswith("/denied")

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 200


def test_registration_and_draft_survive_restart(client):
    from fastapi.testclient import TestClient

    from app.api import create_app

    credentials = {"login": "anna", "password": "local-test-pass"}
    registered = client.post("/api/auth/register", json={**credentials, "role": "admin"})
    assert registered.status_code == 201
    assert registered.json()["role"] == "user"
    path = f"/api/users/{registered.json()['id']}/draft"
    assert client.get(path).status_code == 401
    assert (
        client.post("/api/auth/register", json={**credentials, "login": "ANNA"}).status_code == 409
    )
    assert client.post("/api/auth/login", json=credentials).status_code == 200
    assert client.get("/api/admin/gaps").status_code == 403
    assert client.get(path).json() is None

    draft = {
        "profile_id": "K1",
        "period_months": 6,
        "requirements": ["ИАФ.1"],
        "candidates": ["tool-1"],
        "prices": {
            "tool-1": {"capex": 1250.5, "opex_month": 0},
            "tool-2": {"capex": "", "opex_month": 75},
        },
        "algorithm": "test",
        "mode": "max_coverage",
        "budget": "5000",
    }
    assert client.put(path, json=draft).status_code == 204
    assert client.post("/api/auth/logout").status_code == 200

    with TestClient(create_app()) as restarted:
        restarted.post("/api/auth/login", json={"login": "user", "password": "user"})
        assert restarted.get(path).status_code == 403
        assert restarted.put(path, json=draft).status_code == 403
        assert restarted.post("/api/auth/login", json=credentials).status_code == 200
        assert restarted.get(path).json() == draft


def test_admin_profile_updates_login_and_revokes_sessions_on_password_change(client):
    endpoint = "/api/admin/profile"
    body = {"login": "local-admin", "current_password": "admin", "new_password": "test-pass-27"}
    assert client.put(endpoint, json=body).status_code == 401
    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    assert client.get("/api/admin/users").status_code == 403
    assert client.put(endpoint, json=body).status_code == 403
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    assert client.put(endpoint, json={**body, "current_password": "bad"}).status_code == 403
    assert client.put(endpoint, json={**body, "login": "user"}).status_code == 409
    assert client.put(endpoint, json=body).json()["login"] == "local-admin"
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post("/api/auth/login", json={"login": "admin", "password": "admin"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"login": "local-admin", "password": "test-pass-27"}
        ).status_code
        == 200
    )
    assert {user["login"] for user in client.get("/api/admin/users").json()} == {
        "local-admin",
        "user",
    }
