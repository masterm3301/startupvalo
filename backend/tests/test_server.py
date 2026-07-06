from fastapi.testclient import TestClient

from src.api import server
from src.engine.deck import DeckError


def _post_deck(client, name="Acme", filename="pitch.pptx", content=b"deck-bytes"):
    return client.post(
        "/api/valuation",
        data={"name": name},
        files={"deck": (filename, content, "application/octet-stream")},
    )


def test_valuation_accepts_deck_upload(monkeypatch):
    monkeypatch.setattr(server, "extract_deck_text",
                        lambda filename, data: "extracted pitch text")
    captured = {}

    def fake_run(name, pitch):
        captured["name"], captured["pitch"] = name, pitch
        return iter([{"type": "complete", "memo": "m"}])

    monkeypatch.setattr(server.pipeline, "run_valuation", fake_run)
    client = TestClient(server.app)
    resp = _post_deck(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "complete", "memo": "m"}' in resp.text
    assert captured == {"name": "Acme", "pitch": "extracted pitch text"}


def test_valuation_rejects_bad_deck(monkeypatch):
    def boom(filename, data):
        raise DeckError("The deck contains almost no readable text")

    monkeypatch.setattr(server, "extract_deck_text", boom)
    client = TestClient(server.app)
    resp = _post_deck(client)
    assert resp.status_code == 422
    assert "no readable text" in resp.json()["detail"]


def test_valuation_requires_name_and_deck():
    client = TestClient(server.app)
    assert client.post("/api/valuation", data={"name": "Acme"}).status_code == 422
    assert client.post(
        "/api/valuation",
        files={"deck": ("p.pptx", b"x", "application/octet-stream")},
    ).status_code == 422


def test_valuation_rejects_oversized_deck(monkeypatch):
    monkeypatch.setattr(server, "MAX_DECK_BYTES", 10)
    client = TestClient(server.app)
    resp = _post_deck(client, content=b"x" * 11)
    assert resp.status_code == 422
    assert "larger than" in resp.json()["detail"]


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
