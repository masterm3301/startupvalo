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
