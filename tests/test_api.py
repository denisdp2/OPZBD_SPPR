def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_openapi_available(client):
    assert client.get("/openapi.json").status_code == 200
