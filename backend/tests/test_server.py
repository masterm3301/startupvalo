from fastapi.testclient import TestClient

from src.api import server


def test_valuation_streams_events(monkeypatch):
    monkeypatch.setattr(server.pipeline, "run_valuation",
                        lambda name, pitch: iter([{"type": "complete", "memo": "m"}]))
    client = TestClient(server.app)
    resp = client.post("/api/valuation", json={"name": "Acme", "pitch": "p"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "complete", "memo": "m"}' in resp.text


def test_valuation_requires_name_and_pitch():
    client = TestClient(server.app)
    assert client.post("/api/valuation", json={"name": "Acme"}).status_code == 422


def test_health_reports_missing_keys(monkeypatch):
    for var in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SERPER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    client = TestClient(server.app)
    data = client.get("/api/health").json()
    assert data["ok"] is False


def test_health_ok_when_keys_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("SERPER_API_KEY", "y")
    client = TestClient(server.app)
    assert client.get("/api/health").json()["ok"] is True
