def test_admin_api_requires_login(client):
    assert client.get("/api/admin/gaps").status_code == 401


def test_login_rejects_bad_password(client):
    res = client.post("/api/auth/login", json={"login": "admin", "password": "wrong"})
    assert res.status_code == 401


def test_admin_can_reach_admin_api(client):
    client.post("/api/auth/login", json={"login": "admin", "password": "admin"})
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin"
    assert client.get("/api/admin/gaps").status_code == 501


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


def test_admin_page_is_served(client):
    assert client.get("/admin").status_code == 200
    assert client.get("/").status_code == 200
