# StartupValo v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild StartupValo as a framework-free, tool-grounded multi-agent valuation engine: FastAPI SSE backend + LiteLLM tool-calling loop + Serper/scraping research tools + React dashboard.

**Architecture:** Six sequential "analyst" agents each run a LiteLLM tool-calling loop with `web_search` (Serper) and `scrape_page` tools, passing reports forward; a pipeline emits progress events through a queue that the FastAPI server streams as SSE; a React (Vite) frontend renders live agent cards and the final memo. No CrewAI.

**Tech Stack:** Python 3.13, FastAPI, LiteLLM (Groq `llama-3.3-70b-versatile`), httpx, BeautifulSoup4, pytest · React 18, Vite 5, marked, vitest.

**Spec:** `docs/superpowers/specs/2026-07-06-startupvalo-v2-design.md`

## Global Constraints

- Python venv is the existing `.venv` at the project root. All backend commands run **from `backend/`** using `../.venv/bin/<tool>`.
- Env vars live in the root `.env` (already populated and verified): `GROQ_API_KEY`, `SERPER_API_KEY`, `LLM_MODEL=groq/llama-3.3-70b-versatile`. Never commit `.env`.
- Groq free tier ≈ 30 req/min: the LLM wrapper must pace calls (default 2s between calls, `LLM_PACING_SECONDS` overridable — tests set it to `0`) and retry 429/5xx with exponential backoff.
- Every agent report must cite source URLs; agent prompts cap tool use at 4 calls, the loop hard-caps at 8.
- SSE event types (exact): `agent_init`, `agent_active`, `tool_call`, `agent_done`, `agent_error`, `complete`. All events except `complete` and `agent_init` carry the agent `id`.
- Frontend dev server: port 3000, proxying `/api` → `http://localhost:8000`.
- Commit after every task with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Backend scaffold + research tools (`tools.py`)

**Files:**
- Create: `backend/requirements.txt`, `backend/conftest.py` (empty), `backend/src/__init__.py`, `backend/src/engine/__init__.py`, `backend/src/api/__init__.py`, `backend/src/reporting/__init__.py` (all `__init__.py` empty)
- Create: `backend/src/engine/tools.py`
- Test: `backend/tests/test_tools.py`

**Interfaces:**
- Produces: `web_search(query: str) -> str`, `scrape_page(url: str) -> str` — always return a string; failures return a string starting with `"ERROR:"`, never raise. `TOOL_SCHEMAS: list[dict]` (OpenAI function-call format), `TOOL_FUNCTIONS: dict[str, callable]`.

- [ ] **Step 1: Scaffold and install**

```bash
cd backend  # create it first: mkdir -p backend/src/engine backend/src/api backend/src/reporting backend/tests
touch conftest.py src/__init__.py src/engine/__init__.py src/api/__init__.py src/reporting/__init__.py
```

`backend/requirements.txt`:

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
litellm>=1.60.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

Run: `../.venv/bin/pip install -r requirements.txt` — expect success (most packages already present via v1).

The empty `backend/conftest.py` makes pytest add `backend/` to `sys.path`, so tests import `from src.engine import tools`.

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_tools.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_tools.py -v` · Expected: FAIL / import error (`tools` missing).

- [ ] **Step 4: Implement** — `backend/src/engine/tools.py`:

```python
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
    except httpx.HTTPError as exc:
        return f"ERROR: search failed: {exc}"
    data = resp.json()
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_tools.py -v` · Expected: 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/
git commit -m "feat: backend scaffold + Serper search and scrape tools"
```

---

### Task 2: LLM tool-calling loop (`llm.py`)

**Files:**
- Create: `backend/src/engine/llm.py`
- Test: `backend/tests/test_llm.py`

**Interfaces:**
- Consumes: nothing from other tasks (tool schemas/functions are passed in).
- Produces: `run_agent(system_prompt: str, user_message: str, tool_schemas: list | None = None, tool_functions: dict | None = None, on_event: callable | None = None) -> str`. `on_event` receives `{"type": "tool_call", "tool": <name>, "detail": <query-or-url>}` (no `id` — the pipeline adds it). Raises on non-retryable LLM errors or retry exhaustion.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_llm.py`:

```python
from types import SimpleNamespace as NS

import litellm
import pytest

from src.engine import llm


def _resp(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


def _tool_call(name, arguments, id="call_1"):
    return NS(id=id, function=NS(name=name, arguments=arguments))


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setenv("LLM_PACING_SECONDS", "0")


def test_returns_final_text_without_tools(monkeypatch):
    monkeypatch.setattr(litellm, "completion", lambda **k: _resp(content="report"))
    assert llm.run_agent("sys", "user") == "report"


def test_executes_requested_tool_and_feeds_result_back(monkeypatch):
    responses = [
        _resp(tool_calls=[_tool_call("echo", '{"query": "hi"}')]),
        _resp(content="done"),
    ]
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    events = []
    out = llm.run_agent(
        "sys", "user",
        tool_schemas=[{"type": "function", "function": {"name": "echo"}}],
        tool_functions={"echo": lambda query: f"echo:{query}"},
        on_event=events.append,
    )
    assert out == "done"
    tool_msgs = [m for m in calls[1]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "echo:hi"
    assert events == [{"type": "tool_call", "tool": "echo", "detail": "hi"}]


def test_tool_cap_forces_final_answer(monkeypatch):
    def always_wants_tools(**kwargs):
        if "tools" in kwargs:
            return _resp(tool_calls=[_tool_call("echo", '{"query": "again"}')])
        return _resp(content="forced final")

    monkeypatch.setattr(litellm, "completion", always_wants_tools)
    out = llm.run_agent(
        "sys", "user",
        tool_schemas=[{"type": "function", "function": {"name": "echo"}}],
        tool_functions={"echo": lambda query: "r"},
    )
    assert out == "forced final"


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            err = Exception("rate limited")
            err.status_code = 429
            raise err
        return _resp(content="ok")

    monkeypatch.setattr(litellm, "completion", flaky)
    assert llm.run_agent("sys", "user") == "ok"
    assert len(attempts) == 3


def test_non_retryable_error_raises(monkeypatch):
    def bad(**kwargs):
        err = Exception("invalid key")
        err.status_code = 401
        raise err

    monkeypatch.setattr(litellm, "completion", bad)
    with pytest.raises(Exception, match="invalid key"):
        llm.run_agent("sys", "user")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_llm.py -v` · Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — `backend/src/engine/llm.py`:

```python
import json
import os
import time

import litellm

MAX_TOOL_CALLS = 8
MAX_RETRIES = 5


def _model() -> str:
    return os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")


def _pacing() -> float:
    return float(os.environ.get("LLM_PACING_SECONDS", "2"))


def _completion_with_retry(**kwargs):
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        try:
            response = litellm.completion(**kwargs)
            time.sleep(_pacing())  # stay under Groq free-tier req/min limits
            return response
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            retryable = status == 429 or (status is not None and status >= 500)
            if not retryable or attempt == MAX_RETRIES - 1:
                raise
            time.sleep(delay)
            delay *= 2


def run_agent(system_prompt, user_message, tool_schemas=None, tool_functions=None,
              on_event=None):
    """Run one agent to completion, executing any tools it requests.

    Returns the agent's final text report. After MAX_TOOL_CALLS tool executions,
    the next LLM call omits tools to force a final answer.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tools_used = 0
    while True:
        kwargs = {"model": _model(), "messages": messages}
        if tool_schemas and tools_used < MAX_TOOL_CALLS:
            kwargs["tools"] = tool_schemas
        msg = _completion_with_retry(**kwargs).choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return msg.content or ""
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = (tool_functions or {}).get(name)
            result = fn(**args) if fn else f"ERROR: unknown tool {name}"
            if on_event:
                detail = args.get("query") or args.get("url") or ""
                on_event({"type": "tool_call", "tool": name, "detail": detail})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            tools_used += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_llm.py -v` · Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/engine/llm.py backend/tests/test_llm.py
git commit -m "feat: LiteLLM tool-calling loop with retry, pacing, and tool cap"
```

---

### Task 3: Agent definitions (`agents.py`)

**Files:**
- Create: `backend/src/engine/agents.py`
- Test: `backend/tests/test_agents.py`

**Interfaces:**
- Produces: `AGENTS: list[dict]` — six dicts in pipeline order, each with keys `id`, `name`, `icon`, `color`, `uses_tools`, `system_prompt`, `task_template`. Templates contain `{name}` and `{pitch}` placeholders (nothing else in braces — escape any literal braces).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_agents.py`:

```python
from src.engine.agents import AGENTS


def test_six_agents_in_pipeline_order():
    assert [a["id"] for a in AGENTS] == [
        "talent", "market", "moat", "finance", "sentiment", "memo",
    ]


def test_agent_shape_and_placeholders():
    for a in AGENTS:
        for key in ("id", "name", "icon", "color", "uses_tools",
                    "system_prompt", "task_template"):
            assert key in a, f"{a.get('id')} missing {key}"
        # must format cleanly with exactly these two placeholders
        a["task_template"].format(name="X", pitch="Y")


def test_only_the_committee_lacks_tools():
    assert [a["uses_tools"] for a in AGENTS] == [True] * 5 + [False]


def test_research_agents_demand_citations():
    for a in AGENTS[:5]:
        assert "cite" in a["system_prompt"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_agents.py -v` · Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — `backend/src/engine/agents.py`:

```python
"""The six analyst personas, in pipeline order. Pure data — no logic."""

RESEARCH_RULES = (
    " You have two tools: web_search(query) and scrape_page(url). Use web_search "
    "BEFORE asserting any market size, competitor name, funding amount, or benchmark; "
    "use scrape_page when a snippet is not enough. Cite the source URL in parentheses "
    "after every number or named fact. If you cannot verify a claim after searching, "
    "write 'unverified' rather than inventing data. Make at most 4 tool calls, then "
    "write your report. Keep the report under 250 words."
)

AGENTS = [
    {
        "id": "talent",
        "name": "Team Auditor",
        "icon": "👤",
        "color": "#ec4899",
        "uses_tools": True,
        "system_prompt": (
            "You are a seasoned VC talent scout with 15 years evaluating founding teams. "
            "You spot execution capability, technical depth, and founder-market fit, and "
            "you apply a Team Multiplier (0.5x-2.0x) to the base valuation."
            + RESEARCH_RULES
        ),
        "task_template": (
            "Analyze the founding team for **{name}**.\nPitch: {pitch}\n\n"
            "Search for the company and its founders. Assess backgrounds, shipping/exit "
            "history, founder-market fit, and team completeness (tech + business + domain).\n\n"
            "Format:\n**Founder Profile**\n**Strengths** (2-3)\n**Red Flags**\n"
            "**Team Multiplier**: [0.5x-2.0x] with one-line justification"
        ),
    },
    {
        "id": "market",
        "name": "Market Validator",
        "icon": "📊",
        "color": "#3b82f6",
        "uses_tools": True,
        "system_prompt": (
            "You are a skeptical economist who has been burned by founders claiming "
            "'$100B markets'. You cross-reference every claim against real industry data "
            "and value companies on realistic SOM, not fantasy TAM."
            + RESEARCH_RULES
        ),
        "task_template": (
            "Validate the market size for **{name}**.\nPitch: {pitch}\n\n"
            "Search for real market reports and comparable companies in this sector.\n\n"
            "Format:\n**TAM / SAM / SOM** (with sources)\n**Market Timing**: why now or why not\n"
            "**Growth Rate**: sourced CAGR\n**Realistic SOM**: $X capturable in 5 years\n"
            "**Market Score**: [1-10] with reasoning"
        ),
    },
    {
        "id": "moat",
        "name": "Defensibility Analyst",
        "icon": "🏰",
        "color": "#8b5cf6",
        "uses_tools": True,
        "system_prompt": (
            "You are a competitive intelligence officer who thinks like a well-funded "
            "competitor trying to kill this startup. You hunt for network effects, "
            "proprietary tech, switching costs, and distribution edges."
            + RESEARCH_RULES
        ),
        "task_template": (
            "Assess moat and defensibility for **{name}**.\nPitch: {pitch}\n\n"
            "Search for its actual competitors and their funding/stage.\n\n"
            "Format:\n**Top Competitors**: 3 real companies with funding/stage (sourced)\n"
            "**Moat Analysis**: network effects / proprietary tech / switching costs / data\n"
            "**Distribution Edge**\n**Defensibility Score**: [1-10]\n"
            "**Competitive Risk**: Low / Medium / High — one-line reason"
        ),
    },
    {
        "id": "finance",
        "name": "Unit Economics CFO",
        "icon": "💰",
        "color": "#10b981",
        "uses_tools": True,
        "system_prompt": (
            "You are a startup CFO who ignores vision and focuses only on math. You catch "
            "companies spending $10 to make $5, and you derive valuations from real "
            "revenue multiples of comparable companies."
            + RESEARCH_RULES
        ),
        "task_template": (
            "Stress-test unit economics for **{name}**.\nPitch: {pitch}\n\n"
            "Search for benchmark margins and revenue multiples for this business model.\n\n"
            "Format:\n**Revenue Model**\n**Gross Margin**: sourced benchmark %\n"
            "**CAC / LTV**: dynamics\n**Payback Period**\n**Burn Profile**\n"
            "**Financial Health**: Healthy / Leaky / Critical\n"
            "**Implied Valuation**: $X-$Y from sourced revenue multiples"
        ),
    },
    {
        "id": "sentiment",
        "name": "Hype & Sentiment",
        "icon": "📡",
        "color": "#f97316",
        "uses_tools": True,
        "system_prompt": (
            "You are a market sentiment analyst who tracks VC capital flows, sector "
            "trends, and deal multiples obsessively. You know when FOMO is inflating "
            "valuations and when a sector is cooling."
            + RESEARCH_RULES
        ),
        "task_template": (
            "Gauge current market sentiment for **{name}**'s sector.\nPitch: {pitch}\n\n"
            "Search for recent funding news and deal activity in this sector.\n\n"
            "Format:\n**Sector**\n**VC Inflows**: flowing in or pulling back (sourced)\n"
            "**Comparable Deals**: recent rounds for this stage/sector (sourced)\n"
            "**Hype Cycle**: Peak / Plateau / Trough / Rising\n"
            "**Valuation Adjustment**: [+/-X%] Hype Premium or Discount"
        ),
    },
    {
        "id": "memo",
        "name": "Investment Committee",
        "icon": "📋",
        "color": "#f59e0b",
        "uses_tools": False,
        "system_prompt": (
            "You are the senior partner chairing the investment committee, having "
            "evaluated 1,000+ deals. You synthesize specialist reports into a decisive "
            "memo. Preserve the specialists' source citations for every number you use. "
            "Use specific dollar amounts. Be bold but honest about uncertainty."
        ),
        "task_template": (
            "Write the Final Investment Memo for **{name}**.\nPitch: {pitch}\n\n"
            "Synthesize the specialist reports below. Apply:\n"
            "Base Valuation (CFO's implied range anchored on Market Validator's realistic "
            "SOM) x Team Multiplier x Defensibility adjustment x Hype adjustment.\n\n"
            "Format EXACTLY as:\n\n"
            "## Executive Summary\n[2-3 sentences]\n\n"
            "## Valuation Range\n**Bear case**: $X  |  **Base case**: $Y  |  **Bull case**: $Z\n\n"
            "## Valuation Math\n[one short paragraph showing the formula applied with the "
            "actual numbers from the reports]\n\n"
            "## Why Invest\n- [reason 1]\n- [reason 2]\n- [reason 3]\n\n"
            "## Key Risks\n- [risk 1]\n- [risk 2]\n- [risk 3]\n\n"
            "## Verdict\n**[INVEST / WATCH / PASS]** — [one sentence rationale]"
        ),
    },
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_agents.py -v` · Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/engine/agents.py backend/tests/test_agents.py
git commit -m "feat: six grounded analyst agent definitions"
```

---

### Task 4: Trace recorder (`trace.py`)

**Files:**
- Create: `backend/src/reporting/trace.py`
- Test: `backend/tests/test_trace.py`

**Interfaces:**
- Produces: `TraceRecorder(name: str, pitch: str, logs_dir: Path | None = None)` with `.record(event: dict) -> None` and `.finish() -> Path` (writes `logs/agent-trace-<YYYYmmdd-HHMMSS>.md` and returns its path). Default `logs_dir` is `<project root>/logs`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_trace.py`:

```python
from src.reporting.trace import TraceRecorder


def _run_events():
    return [
        {"type": "agent_active", "id": "market"},
        {"type": "tool_call", "id": "market", "tool": "web_search", "detail": "dog TAM"},
        {"type": "agent_done", "id": "market", "output": "**TAM**: $1.85B (https://a.com)"},
        {"type": "complete", "memo": "final"},
    ]


def test_writes_trace_file_with_searches_and_reports(tmp_path):
    rec = TraceRecorder("Acme", "AI dog walking", logs_dir=tmp_path)
    for e in _run_events():
        rec.record(e)
    path = rec.finish()
    text = path.read_text()
    assert path.name.startswith("agent-trace-") and path.suffix == ".md"
    assert "Acme" in text and "AI dog walking" in text
    assert "web_search" in text and "dog TAM" in text
    assert "$1.85B" in text


def test_records_errors(tmp_path):
    rec = TraceRecorder("Acme", "p", logs_dir=tmp_path)
    rec.record({"type": "agent_error", "id": "moat", "message": "rate limited"})
    assert "rate limited" in rec.finish().read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_trace.py -v` · Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — `backend/src/reporting/trace.py`:

```python
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TraceRecorder:
    """Accumulates one run's events and writes logs/agent-trace-<timestamp>.md."""

    def __init__(self, name: str, pitch: str, logs_dir: Path | None = None):
        self.logs_dir = Path(logs_dir) if logs_dir else PROJECT_ROOT / "logs"
        self.started = datetime.now()
        self.lines = [
            f"# Agent Trace — {name}",
            f"\n**Run started:** {self.started:%Y-%m-%d %H:%M:%S}",
            f"\n**Pitch:** {pitch}\n",
        ]

    def record(self, event: dict) -> None:
        etype = event["type"]
        if etype == "agent_active":
            self.lines.append(f"\n## Agent: {event['id']}\n")
        elif etype == "tool_call":
            self.lines.append(f"- 🔧 `{event['tool']}` → {event['detail']}")
        elif etype == "agent_done":
            self.lines.append(f"\n### Report\n\n{event['output']}\n")
        elif etype == "agent_error":
            self.lines.append(f"\n### ERROR\n\n{event['message']}\n")

    def finish(self) -> Path:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        path = self.logs_dir / f"agent-trace-{self.started:%Y%m%d-%H%M%S}.md"
        path.write_text("\n".join(self.lines))
        return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_trace.py -v` · Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/reporting/trace.py backend/tests/test_trace.py
git commit -m "feat: per-run agent trace recorder"
```

---

### Task 5: Valuation pipeline (`pipeline.py`)

**Files:**
- Create: `backend/src/engine/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `llm.run_agent(...)` (Task 2), `AGENTS` (Task 3), `TOOL_SCHEMAS`/`TOOL_FUNCTIONS` (Task 1), `TraceRecorder` (Task 4).
- Produces: `run_valuation(name: str, pitch: str, logs_dir=None) -> Iterator[dict]` — yields, in order: six `agent_init` events (with `id`, `name`, `icon`, `color`), then interleaved `agent_active`/`tool_call`/`agent_done` per agent, ending with either `{"type": "complete", "memo": <final report>}` or `{"type": "agent_error", "id", "message"}`. Writes the trace file on completion either way.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_pipeline.py`:

```python
from src.engine import pipeline


def test_happy_path_event_order(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline.llm, "run_agent", lambda *a, **k: "report")
    events = list(pipeline.run_valuation("Acme", "AI dog walking", logs_dir=tmp_path))
    types = [e["type"] for e in events]
    assert types[:6] == ["agent_init"] * 6
    assert types.count("agent_active") == 6
    assert types.count("agent_done") == 6
    assert types[-1] == "complete"
    assert events[-1]["memo"] == "report"


def test_prior_reports_flow_forward(monkeypatch, tmp_path):
    seen = []

    def fake(system_prompt, task, **kwargs):
        seen.append(task)
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", fake)
    list(pipeline.run_valuation("Acme", "pitch", logs_dir=tmp_path))
    assert "earlier analysts" not in seen[0]
    assert "earlier analysts" in seen[5]


def test_tool_events_carry_agent_id(monkeypatch, tmp_path):
    def fake(system_prompt, task, tool_schemas=None, tool_functions=None, on_event=None):
        if on_event:
            on_event({"type": "tool_call", "tool": "web_search", "detail": "q"})
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", fake)
    events = list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    tool_events = [e for e in events if e["type"] == "tool_call"]
    assert tool_events and all("id" in e for e in tool_events)


def test_failure_stops_pipeline_and_preserves_partials(monkeypatch, tmp_path):
    calls = []

    def flaky(system_prompt, task, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("boom")
        return "r"

    monkeypatch.setattr(pipeline.llm, "run_agent", flaky)
    events = list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    types = [e["type"] for e in events]
    assert types.count("agent_done") == 2
    assert types[-1] == "agent_error"
    assert len(calls) == 3  # agents 4-6 never ran


def test_trace_file_written(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline.llm, "run_agent", lambda *a, **k: "report text")
    list(pipeline.run_valuation("Acme", "p", logs_dir=tmp_path))
    files = list(tmp_path.glob("agent-trace-*.md"))
    assert len(files) == 1
    assert "report text" in files[0].read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_pipeline.py -v` · Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — `backend/src/engine/pipeline.py`:

```python
import queue
import threading

from src.engine import llm
from src.engine.agents import AGENTS
from src.engine.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from src.reporting.trace import TraceRecorder


def _worker(name: str, pitch: str, q: queue.Queue) -> None:
    reports = []
    output = ""
    for agent in AGENTS:
        q.put({"type": "agent_active", "id": agent["id"]})
        task = agent["task_template"].format(name=name, pitch=pitch)
        if reports:
            prior = "\n\n---\n\n".join(reports)
            task += f"\n\nReports from earlier analysts:\n\n{prior}"

        def on_event(event, agent_id=agent["id"]):
            q.put({**event, "id": agent_id})

        try:
            output = llm.run_agent(
                agent["system_prompt"], task,
                tool_schemas=TOOL_SCHEMAS if agent["uses_tools"] else None,
                tool_functions=TOOL_FUNCTIONS if agent["uses_tools"] else None,
                on_event=on_event,
            )
        except Exception as exc:
            q.put({"type": "agent_error", "id": agent["id"], "message": str(exc)})
            return
        reports.append(f"### {agent['name']}\n\n{output}")
        q.put({"type": "agent_done", "id": agent["id"], "output": output})
    q.put({"type": "complete", "memo": output})


def run_valuation(name: str, pitch: str, logs_dir=None):
    """Yield SSE-ready event dicts for one full valuation run."""
    for agent in AGENTS:
        yield {"type": "agent_init", "id": agent["id"], "name": agent["name"],
               "icon": agent["icon"], "color": agent["color"]}
    trace = TraceRecorder(name, pitch, logs_dir=logs_dir)
    q: queue.Queue = queue.Queue()
    thread = threading.Thread(target=_worker, args=(name, pitch, q), daemon=True)
    thread.start()
    while True:
        event = q.get()
        trace.record(event)
        yield event
        if event["type"] in ("complete", "agent_error"):
            break
    trace.finish()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_pipeline.py -v` · Expected: 5 PASS. Also run the whole suite: `../.venv/bin/pytest -v` — all green.

- [ ] **Step 5: Commit**

```bash
git add backend/src/engine/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: sequential valuation pipeline with event streaming and tracing"
```

---

### Task 6: FastAPI server (`server.py`)

**Files:**
- Create: `backend/src/api/server.py`
- Test: `backend/tests/test_server.py`

**Interfaces:**
- Consumes: `pipeline.run_valuation(name, pitch)` (Task 5), `web_search` (Task 1).
- Produces: `POST /api/valuation` (JSON body `{"name": str, "pitch": str}`) → SSE stream (`data: <json>\n\n` per event); `GET /api/health` → `{"ok": bool, "llm_key": bool, "serper_key": bool}` (+ `llm_live`/`serper_live` when called with `?live=1`); serves `frontend/dist` at `/` when it exists. App object: `src.api.server:app`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_server.py -v` · Expected: FAIL (module missing).

- [ ] **Step 3: Implement** — `backend/src/api/server.py`:

```python
import json
import os
from pathlib import Path

import litellm
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.engine import pipeline
from src.engine.tools import web_search

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(title="StartupValo")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


class ValuationRequest(BaseModel):
    name: str
    pitch: str


def _sse(events):
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"


@app.post("/api/valuation")
def valuation(req: ValuationRequest):
    return StreamingResponse(
        _sse(pipeline.run_valuation(req.name, req.pitch)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health(live: bool = False):
    status = {
        "llm_key": bool(
            os.environ.get("GROQ_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        ),
        "serper_key": bool(os.environ.get("SERPER_API_KEY")),
    }
    if live:  # costs one tiny LLM call + one Serper credit; used by smoke checks
        try:
            litellm.completion(
                model=os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile"),
                messages=[{"role": "user", "content": "hi"}], max_tokens=1,
            )
            status["llm_live"] = "ok"
        except Exception as exc:
            status["llm_live"] = f"error: {exc}"
        result = web_search("startup valuation")
        status["serper_live"] = "ok" if not result.startswith("ERROR") else result
    status["ok"] = status["llm_key"] and status["serper_key"]
    return status


dist = PROJECT_ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
```

Design note: the default health check only verifies key *presence* (free, fast — the frontend calls it on every page load); `?live=1` does real calls and is used by the smoke script. This refines the spec's "minimal live calls" so page loads don't burn Serper credits.

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_server.py -v` · Expected: 4 PASS.

- [ ] **Step 5: Manual boot check**

Run: `../.venv/bin/uvicorn src.api.server:app --port 8000` (from `backend/`), then `curl -s http://localhost:8000/api/health` → `{"llm_key":true,"serper_key":true,"ok":true}`. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add backend/src/api/server.py backend/tests/test_server.py
git commit -m "feat: FastAPI SSE server with health check and static serving"
```

---

### Task 7: Frontend scaffold + SSE client (`frontend/`)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`, `frontend/src/main.jsx`, `frontend/src/api.js`
- Test: `frontend/src/api.test.js`

**Interfaces:**
- Produces: `parseSSE(buffer: string) -> [events: object[], rest: string]` (pure), `streamValuation(name, pitch, onEvent) -> Promise<void>` (POSTs to `/api/valuation`, calls `onEvent` per parsed event), `fetchHealth() -> Promise<object>`. Task 8 imports all three from `./api`.

- [ ] **Step 1: Scaffold files**

`frontend/package.json`:

```json
{
  "name": "startupvalo-frontend",
  "private": true,
  "version": "2.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "marked": "^12.0.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
```

`frontend/vite.config.js`:

```js
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: { port: 3000, proxy: { "/api": "http://localhost:8000" } },
});
```

`frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>StartupValo — AI Valuation Engine</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

`frontend/src/main.jsx`:

```jsx
import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(<App />);
```

Run: `cd frontend && npm install` — expect a clean install and a `package-lock.json`.

- [ ] **Step 2: Write the failing test** — `frontend/src/api.test.js`:

```js
import { expect, it } from "vitest";
import { parseSSE } from "./api";

it("parses complete events and keeps the partial tail", () => {
  const [events, rest] = parseSSE('data: {"type":"a"}\n\ndata: {"ty');
  expect(events).toEqual([{ type: "a" }]);
  expect(rest).toBe('data: {"ty');
});

it("parses multiple events in one chunk", () => {
  const [events, rest] = parseSSE('data: {"n":1}\n\ndata: {"n":2}\n\n');
  expect(events.map((e) => e.n)).toEqual([1, 2]);
  expect(rest).toBe("");
});

it("ignores non-data lines", () => {
  const [events] = parseSSE(': keepalive\n\ndata: {"n":3}\n\n');
  expect(events).toEqual([{ n: 3 }]);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test` (from `frontend/`) · Expected: FAIL (`./api` missing).

- [ ] **Step 4: Implement** — `frontend/src/api.js`:

```js
export function parseSSE(buffer) {
  const events = [];
  let idx;
  while ((idx = buffer.indexOf("\n\n")) !== -1) {
    const chunk = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    if (chunk.startsWith("data: ")) events.push(JSON.parse(chunk.slice(6)));
  }
  return [events, buffer];
}

export async function streamValuation(name, pitch, onEvent) {
  const resp = await fetch("/api/valuation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, pitch }),
  });
  if (!resp.ok) throw new Error(`Server error: HTTP ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let events;
    [events, buffer] = parseSSE(buffer);
    events.forEach(onEvent);
  }
}

export async function fetchHealth() {
  const resp = await fetch("/api/health");
  return resp.json();
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm test` · Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.js frontend/index.html frontend/src/
git commit -m "feat: frontend scaffold with fetch-based SSE client"
```

---

### Task 8: Frontend UI (form, agent board, memo)

**Files:**
- Create: `frontend/src/App.jsx`, `frontend/src/PitchForm.jsx`, `frontend/src/AgentBoard.jsx`, `frontend/src/AgentCard.jsx`, `frontend/src/MemoView.jsx`, `frontend/src/styles.css`

**Interfaces:**
- Consumes: `parseSSE`/`streamValuation`/`fetchHealth` from `./api` (Task 7); backend SSE event shapes from the Global Constraints.
- Produces: the complete single-page UI. No exports consumed elsewhere.

- [ ] **Step 1: Implement `App.jsx`** (state machine + event reducer):

```jsx
import { useEffect, useState } from "react";
import AgentBoard from "./AgentBoard";
import MemoView from "./MemoView";
import PitchForm from "./PitchForm";
import { fetchHealth, streamValuation } from "./api";

export default function App() {
  const [phase, setPhase] = useState("form"); // form | running | done
  const [agents, setAgents] = useState([]);
  const [memo, setMemo] = useState("");
  const [banner, setBanner] = useState("");

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        if (!h.ok)
          setBanner(
            "Missing API keys — set GROQ_API_KEY and SERPER_API_KEY in .env, then restart the backend."
          );
      })
      .catch(() => setBanner("Backend not reachable on /api — is uvicorn running on :8000?"));
  }, []);

  const patchAgent = (id, patch) =>
    setAgents((prev) => prev.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  const onEvent = (e) => {
    switch (e.type) {
      case "agent_init":
        setAgents((prev) => [...prev, { ...e, status: "pending", activity: "", output: "" }]);
        break;
      case "agent_active":
        patchAgent(e.id, { status: "active" });
        break;
      case "tool_call":
        patchAgent(e.id, {
          activity: `${e.tool === "web_search" ? "🔍 searching" : "📄 reading"}: ${e.detail}`,
        });
        break;
      case "agent_done":
        patchAgent(e.id, { status: "done", activity: "", output: e.output });
        break;
      case "agent_error":
        patchAgent(e.id, { status: "error", activity: "", output: e.message });
        setPhase("done");
        break;
      case "complete":
        setMemo(e.memo);
        setPhase("done");
        break;
      default:
        break;
    }
  };

  const start = async (name, pitch) => {
    setAgents([]);
    setMemo("");
    setPhase("running");
    try {
      await streamValuation(name, pitch, onEvent);
    } catch (err) {
      setBanner(String(err));
      setPhase("form");
    }
  };

  return (
    <div className="app">
      <header>
        <span className="logo">💎 StartupValo</span>
        {phase === "done" && (
          <button className="ghost" onClick={() => setPhase("form")}>New valuation</button>
        )}
      </header>
      {banner && <div className="banner">{banner}</div>}
      {phase === "form" && <PitchForm onSubmit={start} />}
      {phase !== "form" && <AgentBoard agents={agents} />}
      {phase === "done" && memo && <MemoView memo={memo} />}
    </div>
  );
}
```

- [ ] **Step 2: Implement the components**

`frontend/src/PitchForm.jsx`:

```jsx
import { useState } from "react";

export default function PitchForm({ onSubmit }) {
  const [name, setName] = useState("");
  const [pitch, setPitch] = useState("");

  const submit = (e) => {
    e.preventDefault();
    if (name.trim() && pitch.trim()) onSubmit(name.trim(), pitch.trim());
  };

  return (
    <form className="pitch-form" onSubmit={submit}>
      <h1>Get a grounded startup valuation</h1>
      <p className="sub">Six AI analysts research real market data and produce a cited investment memo.</p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Startup name"
        required
      />
      <textarea
        value={pitch}
        onChange={(e) => setPitch(e.target.value)}
        rows={6}
        placeholder="Pitch: what it does, stage, traction, team…"
        required
      />
      <button type="submit">Run valuation</button>
    </form>
  );
}
```

`frontend/src/AgentBoard.jsx`:

```jsx
import AgentCard from "./AgentCard";

export default function AgentBoard({ agents }) {
  return (
    <section className="board">
      {agents.map((a) => (
        <AgentCard key={a.id} agent={a} />
      ))}
    </section>
  );
}
```

`frontend/src/AgentCard.jsx`:

```jsx
export default function AgentCard({ agent }) {
  const { name, icon, color, status, activity, output } = agent;
  return (
    <div className={`card ${status}`} style={{ "--accent": color }}>
      <div className="card-head">
        <span className="card-icon">{icon}</span>
        <span className="card-name">{name}</span>
        <span className={`pill ${status}`}>{status}</span>
      </div>
      {activity && <div className="activity">{activity}</div>}
      {output && (
        <details>
          <summary>{status === "error" ? "Error details" : "Report"}</summary>
          <pre>{output}</pre>
        </details>
      )}
    </div>
  );
}
```

`frontend/src/MemoView.jsx`:

```jsx
import { marked } from "marked";

export default function MemoView({ memo }) {
  const download = () => {
    const blob = new Blob([memo], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "investment-memo.md";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <section className="memo">
      <div className="memo-head">
        <h2>📋 Investment Memo</h2>
        <button onClick={download}>Download .md</button>
      </div>
      <div className="memo-body" dangerouslySetInnerHTML={{ __html: marked.parse(memo) }} />
    </section>
  );
}
```

`frontend/src/styles.css` (dark theme carried over from v1):

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #07070f; --surface: #0d0d1a; --card: #111120;
  --border: #1c1c2e; --text-1: #f0f4ff; --text-2: #8b96b8;
  --green: #10b981; --amber: #f59e0b; --red: #f43f5e; --blue: #3b82f6;
}

body {
  background: var(--bg); color: var(--text-1); min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}

.app { max-width: 60rem; margin: 0 auto; padding: 0 1.5rem 4rem; }

header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1rem 0; border-bottom: 1px solid var(--border); margin-bottom: 2rem;
}
.logo { font-weight: 700; font-size: 1.1rem; }

.banner {
  background: #2a1420; border: 1px solid var(--red); color: var(--text-1);
  padding: 0.75rem 1rem; border-radius: 8px; margin-bottom: 1.5rem;
}

.pitch-form { display: flex; flex-direction: column; gap: 1rem; max-width: 34rem; margin: 3rem auto; }
.pitch-form h1 { font-size: 1.6rem; letter-spacing: -0.02em; }
.pitch-form .sub { color: var(--text-2); }
.pitch-form input, .pitch-form textarea {
  background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  color: var(--text-1); padding: 0.75rem 1rem; font: inherit; resize: vertical;
}
.pitch-form input:focus, .pitch-form textarea:focus { outline: 1px solid var(--blue); }

button {
  background: var(--blue); color: white; border: none; border-radius: 8px;
  padding: 0.75rem 1.25rem; font: inherit; font-weight: 600; cursor: pointer;
}
button.ghost { background: transparent; border: 1px solid var(--border); color: var(--text-2); }

.board { display: grid; grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); gap: 1rem; }

.card {
  background: var(--card); border: 1px solid var(--border); border-left: 3px solid var(--accent);
  border-radius: 10px; padding: 1rem; opacity: 0.55; transition: opacity 0.3s;
}
.card.active, .card.done, .card.error { opacity: 1; }
.card.active { box-shadow: 0 0 0 1px var(--accent); }
.card-head { display: flex; align-items: center; gap: 0.5rem; }
.card-name { font-weight: 600; flex: 1; }

.pill { font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 999px; text-transform: uppercase; }
.pill.pending { color: var(--text-2); border: 1px solid var(--border); }
.pill.active { color: var(--amber); border: 1px solid var(--amber); }
.pill.done { color: var(--green); border: 1px solid var(--green); }
.pill.error { color: var(--red); border: 1px solid var(--red); }

.activity {
  margin-top: 0.6rem; color: var(--text-2); font-size: 0.85rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

details { margin-top: 0.6rem; }
summary { color: var(--text-2); cursor: pointer; font-size: 0.85rem; }
details pre {
  white-space: pre-wrap; font-family: inherit; font-size: 0.85rem;
  color: var(--text-2); margin-top: 0.5rem; max-height: 16rem; overflow-y: auto;
}

.memo { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-top: 2rem; }
.memo-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.memo-body h2 { margin: 1.25rem 0 0.5rem; font-size: 1.15rem; }
.memo-body p, .memo-body li { color: var(--text-2); line-height: 1.6; }
.memo-body ul { padding-left: 1.25rem; }
```

- [ ] **Step 3: Verify build and tests**

Run (from `frontend/`): `npm test` → 3 PASS, then `npm run build` → builds `dist/` without errors.

- [ ] **Step 4: Manual smoke of the UI wiring**

Terminal A (from `backend/`): `../.venv/bin/uvicorn src.api.server:app --port 8000`
Terminal B (from `frontend/`): `npm run dev`
Open http://localhost:3000 — expect the pitch form, no error banner (keys are present). Don't run a full valuation yet (that's Task 9's live test). Stop both.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: React dashboard with live agent board and memo view"
```

---

### Task 9: Live smoke test, docs, and v1 removal

**Files:**
- Create: `backend/tests/smoke.py`, `docs/valuation-logic.md`, `README.md`
- Modify: `.env.example` (replace contents)
- Delete: `main.py`, `index.html`, `requirements.txt` (root), `crewai.txt`, `__pycache__/`

**Interfaces:**
- Consumes: everything. This task proves the system end-to-end with real keys.

- [ ] **Step 1: Write the live smoke script** — `backend/tests/smoke.py`:

```python
"""Live smoke test: runs the Market Validator agent once with real keys.

Costs a few Groq calls and ~1-4 Serper credits.
Run from backend/:  ../.venv/bin/python tests/smoke.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.engine import llm
from src.engine.agents import AGENTS
from src.engine.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

agent = AGENTS[1]  # Market Validator
task = agent["task_template"].format(
    name="Rover",
    pitch="Marketplace app connecting dog owners with vetted dog walkers; live in 3 cities.",
)
report = llm.run_agent(
    agent["system_prompt"], task,
    tool_schemas=TOOL_SCHEMAS, tool_functions=TOOL_FUNCTIONS, on_event=print,
)
print("\n=== REPORT ===\n", report)
assert "http" in report.lower(), "expected at least one cited source URL in the report"
print("\nSMOKE OK")
```

- [ ] **Step 2: Run it live**

Run (from `backend/`): `../.venv/bin/python tests/smoke.py`
Expected: printed `tool_call` events (real searches), a market report containing source URLs, and `SMOKE OK`. If it fails, debug before proceeding — this is the gate for the rest of the task.

- [ ] **Step 3: Write `docs/valuation-logic.md`**:

```markdown
# StartupValo — Valuation Logic

How the final pre-money valuation range is produced.

## Inputs (one per specialist agent)

| Agent | Output | Range |
|---|---|---|
| Team Auditor | **Team Multiplier** | 0.5x – 2.0x |
| Market Validator | **Realistic SOM** ($ capturable in 5 years) + Market Score | score 1–10 |
| Defensibility Analyst | **Defensibility Score** | 1–10 |
| Unit Economics CFO | **Implied Valuation range** from sourced revenue multiples | $X – $Y |
| Hype & Sentiment | **Hype adjustment** | ±% |

All numbers must be grounded: agents search the web (Serper) and read sources
(scraper) before asserting figures, and cite the source URL for each one.

## Formula (applied by the Investment Committee agent)

```
Base Valuation  = CFO's implied range, anchored on the Market Validator's realistic SOM
Adjusted        = Base × Team Multiplier
                       × Defensibility adjustment  (score 1–10 → roughly 0.7x–1.3x)
                       × (1 + Hype adjustment %)
```

The committee reports **Bear / Base / Bull** cases (low end, midpoint, high end
of the adjusted range) and a verdict: **INVEST / WATCH / PASS**.

## Caveats

This is an LLM-driven estimate for exploration, not investment advice. Sources
are cited per figure in each run's `logs/agent-trace-<timestamp>.md`; judge the
output by its sources.
```

- [ ] **Step 4: Replace `.env.example`** with:

```
# LLM — any LiteLLM-supported provider works
GROQ_API_KEY=gsk_...
LLM_MODEL=groq/llama-3.3-70b-versatile
# Alternatives: gemini/gemini-2.5-flash (GEMINI_API_KEY), gpt-4o-mini (OPENAI_API_KEY)

# Web research (free key: https://serper.dev)
SERPER_API_KEY=...

# Seconds between LLM calls (Groq free tier pacing); set 0 for paid tiers
LLM_PACING_SECONDS=2
```

- [ ] **Step 5: Write `README.md`**:

```markdown
# StartupValo

Multi-agent startup valuation engine. Six AI analysts research real market data
(web search + scraping) and produce a cited Investment Memo with a bear/base/bull
pre-money valuation.

## Run

```bash
# 1. keys
cp .env.example .env   # fill in GROQ_API_KEY and SERPER_API_KEY

# 2. backend (from backend/)
../.venv/bin/pip install -r requirements.txt
../.venv/bin/uvicorn src.api.server:app --port 8000

# 3. frontend (from frontend/)
npm install
npm run dev            # → http://localhost:3000
```

Production: `npm run build` in `frontend/`, then the backend alone serves
everything at http://localhost:8000.

## Tests

- Backend: `cd backend && ../.venv/bin/pytest`
- Frontend: `cd frontend && npm test`
- Live smoke (uses real API credits): `cd backend && ../.venv/bin/python tests/smoke.py`

## Docs

- `docs/valuation-logic.md` — how the valuation is computed
- `logs/agent-trace-<timestamp>.md` — full research trace per run
```

- [ ] **Step 6: Remove v1**

```bash
git rm main.py index.html requirements.txt crewai.txt
rm -rf __pycache__
```

(`text.txt` stays — it's the original project brief. The old `docs/agent-teams-reference.md` stays too.)

- [ ] **Step 7: Full verification**

1. `cd backend && ../.venv/bin/pytest` → all pass.
2. `cd frontend && npm test && npm run build` → pass + clean build.
3. Start backend only (`../.venv/bin/uvicorn src.api.server:app --port 8000`), open http://localhost:8000 — the **built** frontend loads (static serving works).
4. Run one full live valuation through the UI (name: "Rover", pitch: the smoke-test pitch). Expect: cards activate in order, tool activity lines appear, memo renders with citations, download works, and a new `logs/agent-trace-*.md` exists.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: live smoke test, valuation-logic docs, README; remove v1"
```

---

## Self-review notes

- **Spec coverage:** tools ✓ (T1), tool loop + retry/pacing ✓ (T2), six grounded agents ✓ (T3), trace logs ✓ (T4), pipeline + partial results ✓ (T5), SSE server + health + static serving ✓ (T6), SSE client ✓ (T7), UI with live tool activity + memo download ✓ (T8), smoke test + valuation-logic doc + v1 removal ✓ (T9). Git/.gitignore already done pre-plan.
- **Deviation from spec (intentional):** `/api/health` checks key presence by default and does live calls only with `?live=1`, so page loads don't burn Serper credits.
- **Type consistency check:** `run_agent` signature identical in T2 definition and T5/T9 call sites; event shapes match across T4/T5/T6/T8; `parseSSE` return shape matches T7 tests and usage.
