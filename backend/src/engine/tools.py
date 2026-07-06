import os

import httpx
from bs4 import BeautifulSoup

SERPER_URL = "https://google.serper.dev/search"
MAX_PAGE_CHARS = 6000
USER_AGENT = "Mozilla/5.0 (StartupValo research bot)"


def web_search(query: str) -> str:
    """Google search via Serper.dev. Returns compact text results with URLs."""
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return "ERROR: SERPER_API_KEY is not set."
    try:
        resp = httpx.post(
            SERPER_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        return f"ERROR: search failed: {exc}"
    except ValueError as exc:
        return f"ERROR: search returned invalid JSON: {exc}"
    lines = []
    box = data.get("answerBox")
    if box:
        snippet = box.get("snippet") or box.get("answer", "")
        lines.append(f"Answer: {snippet} (source: {box.get('link', 'answer box')})")
    for item in data.get("organic", [])[:8]:
        lines.append(f"- {item.get('title')}: {item.get('snippet')} ({item.get('link')})")
    return "\n".join(lines) or "No results found."


def scrape_page(url: str) -> str:
    """Fetch a web page and return its readable text, truncated."""
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return f"ERROR: could not fetch {url}: {exc}"
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type:
        return f"ERROR: {url} is not an HTML page (content-type: {content_type})."
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[:MAX_PAGE_CHARS] or "ERROR: page contained no readable text."


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search Google for current facts: market sizes, competitors, "
                           "funding rounds, benchmarks. Returns titles, snippets, and URLs.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scrape_page",
            "description": "Fetch and read the text of a specific web page when a search "
                           "snippet is not detailed enough.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full URL to read"}},
                "required": ["url"],
            },
        },
    },
]

TOOL_FUNCTIONS = {"web_search": web_search, "scrape_page": scrape_page}
