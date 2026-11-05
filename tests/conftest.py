import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SZI_DATA_DIR", str(tmp_path))
    return TestClient(create_app())
