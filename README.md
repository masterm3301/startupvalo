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
