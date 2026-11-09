"""Smoke tests for the HTTP wrapper. ask() is patched — no live LLM call."""
import pytest
from fastapi.testclient import TestClient

from soccerhub.errors import SoccerhubError


@pytest.fixture
def client(monkeypatch):
    import soccerhub.api as api

    monkeypatch.setattr(api, "ask", lambda prompt: f"echo:{prompt}")
    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_ask_returns_answer(client):
    r = client.post("/ask", json={"prompt": "who leads in xG?"})
    assert r.status_code == 200
    assert r.json() == {"answer": "echo:who leads in xG?"}


def test_ask_rejects_empty_prompt(client):
    assert client.post("/ask", json={"prompt": ""}).status_code == 422


def test_ask_maps_agent_error_to_502(monkeypatch):
    import soccerhub.api as api

    def _boom(prompt):
        raise SoccerhubError("gemini down")

    monkeypatch.setattr(api, "ask", _boom)
    r = TestClient(api.app).post("/ask", json={"prompt": "x"})
    assert r.status_code == 502
    assert "gemini down" in r.json()["detail"]
