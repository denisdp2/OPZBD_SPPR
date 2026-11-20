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
    "tool-1": {
        "capex": 1250.5,
        "opex_month": 0,
        "implement_days": "",
    },
    "tool-2": {
        "capex": "",
        "opex_month": 75,
        "implement_days": "",
    },
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


def test_admin_can_update_another_users_role_and_password(client):
    client.post("/api/auth/login", json={"login": "user", "password": "user"})
    user_id = client.get("/api/auth/me").json()["id"]
    route = f"/api/admin/users/{user_id}"
    update = {"role": "admin", "current_password": "admin", "new_password": "new-test-pass"}
    assert client.put(route, json=update).status_code == 403
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    assert client.put(route, json={**update, "current_password": "wrong"}).status_code == 403
    assert client.put(route, json=update).json()["role"] == "admin"
    assert (
        client.post("/api/auth/login", json={"login": "user", "password": "user"}).status_code
        == 401
    )
    assert (
        client.post("/api/auth/login", json={"login": "user", "password": "new-test-pass"}).json()[
            "role"
        ]
        == "admin"
    )


def test_admin_can_delete_user_and_invalidate_drafts_and_sessions(client):
    user = client.post(
        "/api/auth/register", json={"login": "delete-me", "password": "delete-test-pass"}
    ).json()
    client.post("/api/auth/login", json={"login": user["login"], "password": "delete-test-pass"})
    user_cookie = dict(client.cookies)
    route = f"/api/admin/users/{user['id']}"
    assert client.put(f"/api/users/{user['id']}/draft", json={}).status_code == 204
    assert client.request("DELETE", route, json={"current_password": "admin"}).status_code == 403
    admin = client.post("/api/auth/login", json={"login": "admin", "password": "admin"}).json()
    password = {"current_password": "admin"}
    self_route = f"/api/admin/users/{admin['id']}"
    assert client.request("DELETE", self_route, json=password).status_code == 409
    assert client.request("DELETE", route, json={"current_password": "bad"}).status_code == 403
    assert client.request("DELETE", route, json=password).status_code == 204
    assert client.app.state.auth.read_draft(user["id"]) is None
    client.cookies.clear()
    client.cookies.update(user_cookie)
    assert client.get("/api/auth/me").status_code == 401
