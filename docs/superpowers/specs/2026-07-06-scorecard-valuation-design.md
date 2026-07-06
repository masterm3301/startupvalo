# Scorecard-Driven Valuation — Design Spec

**Date:** 2026-07-06
**Goal:** Port the methodology of the user's `startup-evaluator.skill` (v2, zip in repo root; source of truth for rubric wording) into StartupValo's 6-agent pipeline, so valuations are verification-driven, harshly scored, North-Africa-calibrated, and computed deterministically from a scorecard instead of estimated by the LLM.

**Why:** Current output trusts deck claims, uses US-calibrated multiples, and lets the committee LLM multiply its way to inflated numbers (sample run: $127M for a pre-seed 3-city marketplace; the skill's method yields low-hundreds of $K).

**Approach chosen:** Deterministic scorecard engine (user-approved). Agents emit structured scores; Python computes the weighted total and valuation; the committee writes prose around numbers it is handed. Full research depth accepted at the cost of fewer free-tier runs per day.

---

## 1. Score block protocol

Every research agent (all except the committee) ends its report with a fenced block:

````
```scores
{"traction": 2, "funding": 0}
```
````

- Keys are fixed per agent (see §3). Values: integers 0–10, or `null` only where N/A is allowed (`deep_tech`).
- Parsing (`scorecard.parse_scores`): last ` ```scores ` fenced block in the report, `json.loads`, ignore unknown keys, clamp to 0–10.
- **Missing or unparseable score → 0** (skill rule: assume the worst). The scorecard result records which dimensions defaulted so the committee can flag them as "unverified — defaulted to 0".

## 2. Scorecard engine — `backend/src/engine/scorecard.py` (new, pure)

### Dimensions and weights (from the skill's output table; sum = 20)

| Key          | Dimension                                 | Weight | Scored by |
|--------------|-------------------------------------------|--------|-----------|
| `market`     | Market Size, Competition & Business Model | 2      | Market Validator |
| `founders`   | Founder Experience & Team                 | 3      | Founder Verifier |
| `uniqueness` | Product Uniqueness & Innovation           | 1      | Product & Moat Analyst |
| `mvp`        | MVP / Product Status                      | 3      | Reality Checker |
| `reality`    | Morocco / North Africa Reality            | 1      | Reality Checker |
| `growth`     | Growth Difficulty                         | 2      | Market Validator |
| `traction`   | Revenue & Traction                        | 4      | Traction & Funding Auditor |
| `funding`    | Funding Status                            | 4      | Traction & Funding Auditor |
| `deep_tech`  | Deep Tech Bonus (0–10 or null = N/A)      | —      | Product & Moat Analyst |

`overall = sum(score_i * weight_i) / 20` → 0–10, reported to one decimal.

### Valuation tiers (North Africa; authoritative)

| Overall  | Valuation range |
|----------|-----------------|
| 0–2      | $0 – $15K       |
| 2–3      | $25K – $50K     |
| 3–4      | $50K – $150K    |
| 4–5      | $100K – $250K   |
| 5–6      | $150K – $400K   |
| 6–7      | $300K – $600K   |
| 7–8      | $500K – $1M     |
| 8–10     | $750K – $2M     |

Boundary rule: a score of exactly N uses the tier starting at N (tiers are [low, high)).

### Hard rules (enforced in code, after tier lookup)

1. **Idea-stage cap:** `mvp <= 1 and traction == 0` → valuation forced to $10K–$30K regardless of overall score. Result carries `idea_stage_cap: true`.
2. **Deep-tech multiplier** (concretization of the skill's vague "bonus added separately"): if `deep_tech` is not null and ≥ 4, multiply both ends of the range by `1 + deep_tech/10` (e.g. 7 → 1.7x). Below 4 or null → no multiplier. Applied **after** the idea-stage cap check but never to a capped range (an idea-stage startup gets no deep-tech uplift — no product means no applied invention).

### Output

`compute_scorecard(scores: dict) -> dict` returns: per-dimension rows (score, weight, weighted, defaulted-flag), `overall`, `valuation_low`, `valuation_high`, `deep_tech_multiplier` (or null), `idea_stage_cap` (bool). This dict is JSON-serialized into the committee's task and recorded in the trace.

## 3. Agent roster — `backend/src/engine/agents.py`

Six agents, same pipeline order and ids (UI cards keep working); three renamed. Prompts embed compressed rubrics **copied faithfully from the skill** — score anchors, verification rules, and hard zeros must match the skill's wording in intent (compressed for token budget, not softened). Shared research rules change: **at most 8 tool calls** (was 4), report cap **400 words** (was 250) plus the scores block, citation and "unverified" rules unchanged.

| id (unchanged) | New name | Scores | Duties (from the skill) |
|---|---|---|---|
| `talent` | Founder Verifier | `founders` | LinkedIn verification per claimed founder: search `"[Name]" "[Startup]" linkedin`; verified if headline OR experience OR Google-result title ties them to the startup; otherwise not a co-founder — state verified count vs claimed. Per-founder 1–10 doer score, commitment level; `founders` = average of verified founders, deduct if verified team < claimed; solo founder = flagged risk. Advisory/mentor roles count for nothing. Emits founders-table rows (Name, Claimed Role, Headline, In Experience?, URL, Verdict). |
| `market` | Market Validator | `market`, `growth` | TAM/SAM/SOM with sources, competitors, monetization clarity, unit-economics plausibility → `market`. Growth difficulty rubric: 0–3 near-impossible (capital-heavy, regulated, linear), 4–6 difficult, 7–10 built-for-growth (near-zero marginal cost, network effects, organic acquisition) → `growth`. Harsh: most early North African startups average 3–5. |
| `moat` | Product & Moat Analyst | `uniqueness`, `deep_tech` | Unique value prop, defensible IP, real problem → `uniqueness`. Deep-tech gate: blockchain/metaverse/AI-wrappers/off-the-shelf-ML are NEVER deep tech (null); "could a good dev replicate the core in weeks?" yes → null; otherwise 1–10 per the skill's table, verified via Scholar/patent/competitor searches → `deep_tech`. |
| `sentiment` | Reality Checker | `mvp`, `reality` | Replaces Hype & Sentiment (no hype dimension in the skill). Visit website via scrape_page — dead URL/DNS error/"coming soon" = no product; search App Store / Play Store if an app is claimed; search GitHub if an MVP is claimed (no public repo + no live product → MVP claim unverified, score 0–1); collect LinkedIn company page and socials. Emits online-presence table rows. `mvp` per the skill's 0–10 existence rubric (claims without proof = 0). `reality` per the Morocco filter: hard 0 for blockchain/crypto/metaverse targeting Morocco and LLM-wrapper-that-ChatGPT-does; thin AI wrapper 1; Morocco-licensed fintech 2; dominated e-commerce 2; SaaS for non-paying market 3; real local problem (logistics/agri/edu/health) 7–10; B2B serving EU/US from Morocco 6–8. Hard zeros are non-negotiable; a global-market blockchain project is judged on its actual target market instead. |
| `finance` | Traction & Funding Auditor | `traction`, `funding` | `traction` rubric: 0 nothing; 1 waitlist; 2 <50 users no revenue; 3 50–500; 4 500+ engaged no revenue; 5 <$1K/mo; 6 $1–5K; 7 $5–20K; 8 $20K+ growing; 9 + proven retention; 10 revenue machine. No retention data anywhere → assume no retention. Unverifiable self-reported metrics → assume ≤50% of claimed; "interested", hackathon praise, incubator graduation are NOT traction (0). `funding` rubric: 0 nothing; 1 bootstrapped >$0; 2 small prize; 3–5 Tamwilcom/1000 FIKRA-class grant; 5–6 named verifiable angel; 6–7 pre-seed with real VC; 7–8 seed $100K+; 9–10 significant round. Moroccan incubator rules: MRTB, MDJS/Accelab, U-Founders give no funds → 0; OST/OSTX counts only if funds explicitly confirmed; "in talks" = $0; unverifiable investor = doesn't count. Also flags each major deck claim: Confirmed / Exaggerated / Contradicted / Unverifiable. |
| `memo` | Investment Committee | — | No tools. Receives the five reports **and the computed scorecard JSON**. Writes the skill's verdict structure (§4). May not alter, re-derive, or "adjust" the computed overall score or valuation range; prose explains, never overrides. If the startup clearly targets US/EU, it may note "North Africa tiers applied; a US/EU-market comparable would command more" — prose only. |

Deck-vs-reality inputs: every research agent already marks claims confirmed/contradicted/unverified; the auditor's explicit claim table plus the others' findings feed the committee's table.

## 4. Committee output format (replaces the current memo template)

Markdown, in this order (skill's Step-4 template, trimmed of chat-only phrasing):

1. `## 🚀 [Name] — Startup Evaluation` + 1–2 sentence overview
2. `### Online Presence` — table from Reality Checker (Website, LinkedIn, App stores if claimed, socials, Crunchbase; ✅/⚠️/❌)
3. `### Founders (Verified)` — table from Founder Verifier + "Verified founder count: X out of Y claimed"
4. `### Evaluation Scorecard` — the computed table verbatim (dimension, score, weight, one-line justification quoted from the owning agent) + `**Overall: X.X / 10**`; defaulted dimensions marked "unverified — defaulted to 0"
5. `### Estimated Valuation` — the computed range, the tier that produced it, idea-stage cap and deep-tech multiplier called out when applied
6. `### Strengths` (top 2–3) and `### Risks & Concerns` (top 2–3)
7. `### Pitch Deck vs. Reality` — claim / independent finding / verdict table
8. `### 📊 Final Summary` — Project Score, Valuation range, Founder Rating, Innovation Rating (or "Standard business — no deep tech bonus"), each with one blunt sentence
9. `### 💡 Pitch Deck Advice` — missing slides (checklist: Problem, Solution, Market Size, Business Model, Traction/Metrics, Retention, Competition, Team, Financials/Ask — judged from the extracted deck text) + concrete improvements
10. Speculation disclaimer line

## 5. Pipeline changes — `backend/src/engine/pipeline.py`

- `_worker` collects the five research reports as today, then: `scores = parse_scores(reports)` (union of all agents' blocks), `card = compute_scorecard(scores)`, and formats the committee task with reports + `json.dumps(card)`.
- The committee's task template gains a `{scorecard}` slot; AGENTS data stays pure (formatting happens in the pipeline as today via `.format`).
- No new SSE event types; the memo carries the scorecard to the UI. Trace gains the computed scorecard JSON via the existing report text (committee input is not traced today — the scorecard is visible in the memo and in each agent's scores block, which is sufficient).
- `llm.MAX_TOOL_CALLS` 8 → 10 (headroom above the prompt's "at most 8").

## 6. Frontend

- Agent names/icons come from `agent_init` events — renames are backend-only.
- `marked` already renders GFM tables; add minimal `.memo-body table` CSS (borders, padding, `overflow-x: auto` wrapper not needed — tables are narrow).
- `PitchForm` copy stays.

## 7. Testing

- `tests/test_scorecard.py` (new): weight math; every tier boundary; idea-stage cap (incl. deep-tech-not-applied-when-capped); deep-tech multiplier on/off/null; missing key → 0 + defaulted flag; malformed/absent scores block → all-0; clamping.
- `tests/test_agents.py`: adapt — six agents, ids unchanged, each research agent's prompt mentions its scores keys and the fenced block instruction; committee prompt forbids altering computed numbers.
- `tests/test_pipeline.py`: fake agents emit reports with scores blocks → committee task contains computed scorecard JSON; missing block → defaulted scores present.
- Existing deck/server/trace tests: unchanged.
- Live e2e: one full run with the sample deck; verify the memo contains the scorecard table, a sub-$1M valuation for the Rover sample, and the presence/founders tables.

## 8. Constraints & non-goals

- Free-tier reality: a full-depth run roughly doubles tool calls (~40–60k tokens); 1–2 runs/day on `llama-3.3-70b` free tier. `LLM_MODEL` override remains the escape hatch. Accepted by user.
- Non-goals: no Quick/Deep UI toggle; no region selector (North Africa default, prose-level adjustment only); no new SSE events; no changes to deck extraction or upload flow.
- The Berkus-breakdown supporting table from the skill is **dropped**: the scorecard already drives the number deterministically, and a second LLM-estimated breakdown would reintroduce the drift this design removes.
