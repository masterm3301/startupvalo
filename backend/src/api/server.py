import json
import os
from pathlib import Path

import litellm
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.engine import pipeline
from src.engine.deck import DeckError, extract_deck_text
from src.engine.tools import web_search

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(title="StartupValo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_DECK_BYTES = 15 * 1024 * 1024


def _sse(events):
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"


@app.post("/api/valuation")
async def valuation(name: str = Form(...), deck: UploadFile = File(...)):
    data = await deck.read()
    if len(data) > MAX_DECK_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"Deck file is larger than {MAX_DECK_BYTES // (1024 * 1024)} MB — upload a smaller file.",
        )
    try:
        pitch = extract_deck_text(deck.filename, data)
    except DeckError as err:
        raise HTTPException(status_code=422, detail=str(err))
    return StreamingResponse(
        _sse(pipeline.run_valuation(name, pitch)),
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
