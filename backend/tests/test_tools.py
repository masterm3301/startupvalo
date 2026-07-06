import httpx
from src.engine import tools


class FakeResponse:
    def __init__(self, json_data=None, text="", content_type="application/json", status_code=200):
        self._json = json_data or {}
        self.text = text
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)


def test_web_search_formats_results(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    fake = FakeResponse(json_data={
        "answerBox": {"snippet": "Market is $1.85B", "link": "https://a.com"},
        "organic": [{"title": "Report", "snippet": "CAGR 12%", "link": "https://b.com"}],
    })
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **k: fake)
    out = tools.web_search("dog walking market")
    assert "Market is $1.85B" in out
    assert "https://b.com" in out


def test_web_search_failure_returns_error_string(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    def boom(*a, **k):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(tools.httpx, "post", boom)
    assert tools.web_search("x").startswith("ERROR:")


def test_web_search_missing_key_returns_error(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert tools.web_search("x").startswith("ERROR:")


def test_web_search_invalid_json_returns_error(monkeypatch):
    """Test that non-JSON response body is handled gracefully."""
    monkeypatch.setenv("SERPER_API_KEY", "test-key")

    class BadJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("Invalid JSON")

    fake = BadJsonResponse()
    monkeypatch.setattr(tools.httpx, "post", lambda *a, **k: fake)
    result = tools.web_search("x")
    assert result.startswith("ERROR:"), f"Expected error message, got: {result}"


def test_scrape_page_extracts_text_and_strips_chrome(monkeypatch):
    html = ("<html><head><style>x{}</style></head><body>"
            "<nav>menu</nav><p>Real   content here</p><footer>foot</footer></body></html>")
    fake = FakeResponse(text=html, content_type="text/html; charset=utf-8")
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: fake)
    out = tools.scrape_page("https://example.com")
    assert "Real content here" in out
    assert "menu" not in out and "foot" not in out


def test_scrape_page_rejects_non_html(monkeypatch):
    fake = FakeResponse(text="%PDF", content_type="application/pdf")
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: fake)
    assert tools.scrape_page("https://example.com/x.pdf").startswith("ERROR:")


def test_scrape_page_truncates(monkeypatch):
    fake = FakeResponse(text=f"<html><body><p>{'word ' * 5000}</p></body></html>",
                        content_type="text/html")
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: fake)
    assert len(tools.scrape_page("https://example.com")) <= 6000
