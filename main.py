import asyncio
import json
import os
import queue
import threading
from pathlib import Path

from crewai import Agent, Crew, Process, Task
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Thread-safe queue registry ───────────────────────────────────────────────
# Callbacks must be module-level named functions (not closures) so CrewAI can
# serialize them for checkpointing. We look up the per-request queue by the
# worker thread's ID instead of capturing it in a closure.
_queue_registry: dict[int, queue.Queue] = {}
_registry_lock = threading.Lock()

# Maps agent role → (this_agent_id, next_agent_id | None)
_ROLE_MAP = {
    "Lead Talent Scout":            ("talent",    "market"),
    "Skeptical Economist":          ("market",    "moat"),
    "Competitive Intelligence Officer": ("moat",  "finance"),
    "Startup CFO":                  ("finance",   "sentiment"),
    "Market Sentiment Analyst":     ("sentiment", "memo"),
    "Investment Committee Chair":   ("memo",      None),
}

_META_BY_ID = {}  # populated after AGENTS_META is defined


def _task_callback(task_output):
    """Module-level callback — safe to serialize by CrewAI/Pydantic."""
    tid = threading.current_thread().ident
    with _registry_lock:
        q = _queue_registry.get(tid)
    if not q:
        return

    current_id, next_id = _ROLE_MAP.get(task_output.agent, (None, None))
    if not current_id:
        return

    q.put({"type": "agent_done", "id": current_id, "output": task_output.raw})

    if next_id:
        meta = _META_BY_ID.get(next_id, {})
        q.put({"type": "agent_active", "id": next_id, "name": meta.get("name", next_id)})

app = FastAPI(title="StartupValo")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# LLM string — CrewAI uses LiteLLM under the hood, so any provider works:
#   "gpt-4o-mini"                      → needs OPENAI_API_KEY
#   "groq/llama-3.3-70b-versatile"     → needs GROQ_API_KEY
#   "anthropic/claude-3-5-haiku-20241022" → needs ANTHROPIC_API_KEY
#   "ollama/llama3"                    → needs Ollama running locally
LLM = os.getenv("LLM_MODEL", "gpt-4o-mini")

AGENTS_META = [
    {"id": "talent",    "name": "Team Auditor",          "icon": "👤", "color": "#ec4899"},
    {"id": "market",    "name": "Market Validator",       "icon": "📊", "color": "#3b82f6"},
    {"id": "moat",      "name": "Defensibility Analyst",  "icon": "🏰", "color": "#8b5cf6"},
    {"id": "finance",   "name": "Unit Economics CFO",     "icon": "💰", "color": "#10b981"},
    {"id": "sentiment", "name": "Hype & Sentiment",       "icon": "📡", "color": "#f97316"},
    {"id": "memo",      "name": "Investment Committee",   "icon": "📋", "color": "#f59e0b"},
]

_META_BY_ID.update({m["id"]: m for m in AGENTS_META})


def build_and_run_crew(startup_name: str, q: queue.Queue):
    talent_agent = Agent(
        role="Lead Talent Scout",
        goal="Evaluate the founding team quality and Product-Market-Founder fit",
        backstory=(
            "You are a seasoned VC talent scout with 15 years evaluating founding teams. "
            "You instantly spot execution capability, technical depth, and founder-market fit. "
            "You apply a Team Multiplier (0.5x–2.0x) that directly adjusts the base valuation."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    market_agent = Agent(
        role="Skeptical Economist",
        goal="Validate the market size — challenge inflated TAM claims with real data",
        backstory=(
            "You have been burned by founders claiming '$100B markets' that include unrelated sectors. "
            "You cross-reference every claim against real industry data and comparable companies. "
            "You calculate valuation on the Realistic SOM, not fantasy TAM."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    moat_agent = Agent(
        role="Competitive Intelligence Officer",
        goal="Map the competitive landscape and score the startup's defensibility",
        backstory=(
            "You think like a well-funded competitor trying to kill this startup. "
            "You identify network effects, proprietary tech, switching costs, and distribution edges. "
            "You assign a Defensibility Score [1–10] that bumps or cuts the valuation."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    finance_agent = Agent(
        role="Startup CFO",
        goal="Stress-test unit economics and identify 'Leaky Bucket' patterns",
        backstory=(
            "You ignore vision and focus only on math. "
            "You catch companies spending $10 to make $5 instantly. "
            "You use DCF and Comparable Company Analysis to produce revenue-multiple valuations."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    sentiment_agent = Agent(
        role="Market Sentiment Analyst",
        goal="Gauge sector hype and VC sentiment to apply a Hype Premium or Discount",
        backstory=(
            "You track VC capital flows, sector trends, and deal multiples obsessively. "
            "You know when FOMO is inflating valuations and when a sector is cooling fast. "
            "You apply a Hype Factor adjustment (+/-%) to the base valuation."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    committee_agent = Agent(
        role="Investment Committee Chair",
        goal="Synthesize all five specialist reports into a Final Investment Memo with pre-money valuation",
        backstory=(
            "You are the senior partner who has evaluated 1,000+ deals. "
            "You weigh team quality, market reality, defensibility, unit economics, and sentiment "
            "to produce the definitive investment verdict that LPs trust."
        ),
        llm=LLM, verbose=False, allow_delegation=False,
    )

    task1 = Task(
        description=(
            f"Analyze the founding team for startup: **{startup_name}**.\n\n"
            "Assess: backgrounds, technical depth, past shipping/exit history, "
            "founder-market fit, team completeness (tech + business + domain).\n\n"
            "Format:\n"
            "**Founder Profile**: what we know or can infer\n"
            "**Strengths**: top 2-3 positives\n"
            "**Red Flags**: gaps or risks\n"
            "**Team Multiplier**: [0.5x – 2.0x] with one-line justification\n\n"
            "Max 200 words."
        ),
        expected_output="Structured team analysis with a Team Multiplier score.",
        agent=talent_agent,
    )

    task2 = Task(
        description=(
            f"Validate the market size for startup: **{startup_name}**.\n\n"
            "Estimate TAM, SAM, SOM with real numbers. Challenge inflated claims. "
            "Identify timing and structural tailwinds or headwinds.\n\n"
            "Format:\n"
            "**TAM / SAM / SOM**: sizes with estimates\n"
            "**Market Timing**: why now (or why not)\n"
            "**Growth Rate**: estimated CAGR\n"
            "**Realistic SOM**: $X capturable in 5 years\n"
            "**Market Score**: [1-10] with reasoning\n\n"
            "Max 200 words."
        ),
        expected_output="Market size validation with realistic SOM and Market Score.",
        agent=market_agent,
    )

    task3 = Task(
        description=(
            f"Assess moat and defensibility for startup: **{startup_name}**.\n\n"
            "Identify top 3-4 direct competitors. Evaluate defensibility vectors.\n\n"
            "Format:\n"
            "**Top Competitors**: 3 real companies with funding/stage\n"
            "**Moat Analysis**: network effects / proprietary tech / switching costs / data\n"
            "**Distribution Edge**: GTM advantage if any\n"
            "**Defensibility Score**: [1-10]\n"
            "**Competitive Risk**: Low / Medium / High — one-line reason\n\n"
            "Max 200 words."
        ),
        expected_output="Competitive landscape with Defensibility Score.",
        agent=moat_agent,
    )

    task4 = Task(
        description=(
            f"Stress-test unit economics for startup: **{startup_name}**.\n\n"
            "Format:\n"
            "**Revenue Model**: SaaS / marketplace / transactional / etc.\n"
            "**Gross Margin**: estimated % with reasoning\n"
            "**CAC / LTV**: rough ratio and dynamics\n"
            "**Payback Period**: estimated months\n"
            "**Burn Profile**: lean vs capital-intensive\n"
            "**Financial Health**: Healthy / Leaky / Critical\n"
            "**Implied Valuation**: $X – $Y from revenue multiples\n\n"
            "State assumptions. Max 200 words."
        ),
        expected_output="Unit economics analysis with Financial Health and Implied Valuation range.",
        agent=finance_agent,
    )

    task5 = Task(
        description=(
            f"Gauge market sentiment for startup: **{startup_name}**'s sector.\n\n"
            "Format:\n"
            "**Sector**: identify it specifically\n"
            "**VC Inflows**: capital flowing in or pulling back?\n"
            "**Comparable Deals**: recent pre-money averages for this stage/sector\n"
            "**Hype Cycle**: Peak / Plateau / Trough / Rising\n"
            "**Hype Factor**: Overcrowded / Hot / Warm / Cold\n"
            "**Valuation Adjustment**: [+/-X%] Hype Premium or Discount\n\n"
            "Max 200 words."
        ),
        expected_output="Sentiment analysis with Hype Factor and valuation adjustment.",
        agent=sentiment_agent,
    )

    task6 = Task(
        description=(
            f"Write the Final Investment Memo for: **{startup_name}**.\n\n"
            "Synthesize findings from the Team Auditor, Market Validator, Defensibility Analyst, "
            "Unit Economics CFO, and Sentiment Analyst.\n"
            "Apply: Base Valuation × Team Multiplier × Defensibility adjustment × Hype adjustment.\n\n"
            "Format EXACTLY as:\n\n"
            "## Executive Summary\n"
            "[2-3 sentences: what the company does and the investment thesis]\n\n"
            "## Valuation Range\n"
            "**Bear case**: $X  |  **Base case**: $Y  |  **Bull case**: $Z\n\n"
            "## Why Invest\n"
            "- [reason 1]\n"
            "- [reason 2]\n"
            "- [reason 3]\n\n"
            "## Key Risks\n"
            "- [risk 1]\n"
            "- [risk 2]\n"
            "- [risk 3]\n\n"
            "## Verdict\n"
            "**[INVEST / WATCH / PASS]** — [one sentence rationale]\n\n"
            "Use specific dollar amounts. Be bold."
        ),
        expected_output="Complete Investment Memo with valuation range and INVEST/WATCH/PASS verdict.",
        agent=committee_agent,
        context=[task1, task2, task3, task4, task5],
    )

    crew = Crew(
        agents=[talent_agent, market_agent, moat_agent, finance_agent, sentiment_agent, committee_agent],
        tasks=[task1, task2, task3, task4, task5, task6],
        process=Process.sequential,
        task_callback=_task_callback,
        verbose=False,
    )

    # Register this thread's queue before kickoff, clean up after
    tid = threading.current_thread().ident
    with _registry_lock:
        _queue_registry[tid] = q
    try:
        crew.kickoff()
        q.put({"type": "complete"})
    except Exception as e:
        q.put({"type": "error", "message": str(e)})
    finally:
        with _registry_lock:
            _queue_registry.pop(tid, None)


async def valuation_stream(startup_name: str):
    q: queue.Queue = queue.Queue()

    for meta in AGENTS_META:
        yield f"data: {json.dumps({'type': 'agent_init', 'id': meta['id'], 'name': meta['name'], 'icon': meta['icon'], 'color': meta['color']})}\n\n"

    first = AGENTS_META[0]
    yield f"data: {json.dumps({'type': 'agent_active', 'id': first['id'], 'name': first['name']})}\n\n"

    thread = threading.Thread(target=build_and_run_crew, args=(startup_name, q), daemon=True)
    thread.start()

    while True:
        try:
            event = q.get(timeout=0.1)
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("complete", "error"):
                break
        except queue.Empty:
            if not thread.is_alive():
                yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                break
            await asyncio.sleep(0.05)


@app.get("/api/valuation")
async def get_valuation(name: str):
    return StreamingResponse(
        valuation_stream(name),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return (Path(__file__).parent / "index.html").read_text()
