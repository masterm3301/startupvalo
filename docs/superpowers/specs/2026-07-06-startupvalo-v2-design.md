# StartupValo v2 — Design

**Date:** 2026-07-06
**Status:** Approved

## Problem

StartupValo v1 does not work well:

1. The Groq API key was expired — every run failed on the first LLM call. (A new working key is now in `.env`.)
2. The six analyst agents have **no tools**. All market sizes, competitors, and comparable deals in the output are hallucinated, defeating the "skeptical, data-grounded valuation" premise.
3. Everything lives in one `main.py` (317 lines) plus one 21KB `index.html`. There is no `src/` structure, no git history, no error recovery mid-run, and the promised deliverables (`logs/agent-trace.md`, `docs/valuation-logic.md`) don't exist.
4. Input is a bare startup name, giving agents almost nothing real to analyze.

## Goals

- **Grounded valuations**: every agent researches real data via web search and page scraping, and cites sources for every number.
- **Reliability**: survive Groq free-tier rate limits, fail loudly on bad keys, preserve partial results.
- **Structure**: small, readable modules; git history; the originally promised trace logs and valuation-logic docs.
- **Better input**: startup name + free-text pitch description.
- **React dashboard** showing live agent progress including real-time tool activity.

## Decisions (settled with user)

| Decision | Choice |
|---|---|
| LLM provider | Groq (`groq/llama-3.3-70b-versatile` via LiteLLM), model configurable via `LLM_MODEL` |
| Research tools | Serper.dev search **plus** webpage scraping (user must supply a free `SERPER_API_KEY`) |
| Input | Startup name + pitch description (no URL field) |
| Frontend | Rebuild in React (Vite) |
| Agent framework | **None** — drop CrewAI, use a direct LiteLLM tool-calling loop |

## Architecture

```
startupvalo/
├── backend/
│   ├── src/
│   │   ├── api/
│   │   │   └── server.py        # FastAPI app: valuation SSE endpoint, health check, serves built frontend
│   │   ├── engine/
│   │   │   ├── llm.py           # LiteLLM chat wrapper + tool-calling loop, 429 retry/backoff, pacing
│   │   │   ├── tools.py         # web_search (Serper) and scrape_page (httpx + BeautifulSoup)
│   │   │   ├── agents.py        # 6 agent definitions as plain data (id, role, system prompt, output format)
│   │   │   └── pipeline.py      # sequential runner; yields progress events
│   │   └── reporting/
│   │       └── trace.py         # writes logs/agent-trace-<timestamp>.md per run
│   ├── tests/                   # pytest: loop logic, event ordering, retry behavior (mocked LLM/tools)
│   └── requirements.txt         # fastapi, uvicorn, litellm, httpx, beautifulsoup4, python-dotenv, pytest
├── frontend/                    # React + Vite (dev on :3000, proxies /api to :8000)
├── docs/valuation-logic.md      # formulas and multipliers used for the final valuation
├── logs/                        # one agent-trace file per run (gitignored)
└── .env                         # GROQ_API_KEY, SERPER_API_KEY, LLM_MODEL (gitignored)
```

The v1 `main.py`, `index.html`, `crewai.txt`, and root `requirements.txt` are removed once v2 is working (git preserves them).

## Components

### engine/llm.py — tool-calling loop
- `run_agent(system_prompt, user_message, tools, on_event) -> str`
- Loop: call LiteLLM → if the response requests a tool, execute it, append the result, repeat → until the model returns a final text report. Hard cap of 8 tool calls per agent.
- Retries on 429/5xx with exponential backoff (Groq free tier allows ~30 req/min; a full run is ~20–30 LLM calls). Small fixed delay between successive LLM calls for pacing.
- Emits `tool_call` events through `on_event` so the UI can show live research activity.

### engine/tools.py
- `web_search(query)` → Serper.dev API, returns top ~8 results (title, snippet, URL) as compact text.
- `scrape_page(url)` → httpx GET + BeautifulSoup text extraction, truncated to ~6k chars. Timeouts and non-HTML content return a readable error string to the model rather than raising.

### engine/agents.py — the six personas (kept from v1, now grounded)
Sequential order, each receives the pitch plus all prior reports:
1. **Team Auditor** — founder/team assessment → Team Multiplier (0.5x–2.0x)
2. **Market Validator** (Skeptical Economist) — TAM/SAM/SOM from real sources → Market Score
3. **Defensibility Analyst** — real competitors + moat → Defensibility Score (1–10)
4. **Unit Economics CFO** — margins, CAC/LTV, revenue-multiple valuation from real comparables
5. **Hype & Sentiment** — sector funding climate → Hype Premium/Discount (±%)
6. **Investment Committee** — synthesizes: base valuation × team multiplier × defensibility adj × hype adj → bear/base/bull range + INVEST/WATCH/PASS memo

Every prompt requires: search before asserting, cite each number with its source URL, max ~250 words. Agents 1–5 get both tools; agent 6 gets none (synthesis only).

### engine/pipeline.py
- `run_valuation(name, pitch) -> iterator of events`
- Runs agents in order on a worker thread; forwards events via a per-run `queue.Queue` (same mechanism as v1, without the CrewAI callback-registry workaround).
- If an agent fails after retries, emits `agent_error` for that card and stops the pipeline; prior reports remain delivered.

### api/server.py
- `POST /api/valuation` (JSON: `{name, pitch}`) → SSE stream of events.
- `GET /api/health` → validates Groq and Serper keys with minimal live calls; the frontend surfaces failures before any run.
- Serves `frontend/dist` statically in production so one process runs the whole app.

### SSE event protocol
`agent_init` (×6 upfront) · `agent_active {id}` · `tool_call {id, tool, detail}` · `agent_done {id, output}` · `agent_error {id, message}` · `complete {memo}`

### reporting/trace.py
Appends per run: input, each agent's searches/scrapes with URLs, each report, final memo → `logs/agent-trace-<timestamp>.md`.

### frontend/ — React + Vite
Single page, three stages: pitch form (name + textarea) → live agent board (6 cards: pending/active/done/error, current tool activity line, expandable report) → final memo rendered from markdown with a download (.md) button. Visual style carried over from the v1 dashboard (dark theme). Dev: Vite on :3000 proxying `/api` to FastAPI on :8000.

## Error handling
- Dead/missing API keys → caught by `/api/health` at page load, shown as a banner before the user wastes a run.
- 429s mid-run → backoff/retry inside `llm.py`, invisible to the user beyond slower progress.
- Tool failures (scrape timeout, Serper error) → returned to the model as text so it can adapt; never abort the agent.
- Agent failure after retries → `agent_error` event, partial results preserved in UI and trace log.

## Testing
- Pytest with mocked LLM/tools: tool-loop termination and cap, retry/backoff on 429, event ordering, pipeline stop-on-error with partial results.
- One live smoke script (`backend/tests/smoke.py`): runs a single agent end-to-end to verify keys and wiring cheaply.

## Deliverables
- Running app: React UI where a name + pitch produces a grounded, cited Investment Memo with live progress.
- `logs/agent-trace-<timestamp>.md` per run.
- `docs/valuation-logic.md` documenting the multipliers and formulas.
- Git repository with `.gitignore` covering `.env`, `.venv`, `node_modules`, `logs/`, `__pycache__`, `dist`.

## Out of scope
- Pitch-deck/URL ingestion, user accounts, run history persistence, PDF export, deploying beyond localhost.
