# Stock Bubble Index

A CBBI-style composite that answers "is the US stock market in a bubble?" with a
0–100 confidence score, built from 9 valuation, leverage, and structure metrics.

Live pipeline: `fetch_data.py` (pull raw series) → `compute.py` (score & compose)
→ `docs/` (static site, reads `docs/data.json`).

## The 9 metrics

| Metric | Weight | Source | Transform |
|---|---|---|---|
| Shiller CAPE | 14% | multpl.com | level + 3y momentum blend (30y window) |
| Household equity allocation | 13% | FRED (Z.1) | level + 3y momentum blend (30y window) |
| Price-to-sales | 12% | multpl.com | percentile (since 2000) |
| Margin debt | 12% | FINRA | 50% detrended level + 50% YoY growth |
| Buffett Indicator | 11% | FRED | level + 3y momentum blend (20y window) |
| Equity risk premium (CAPE yield − 10Y) | 11% | multpl + FRED | inverted percentile (20y window) |
| Trend deviation (S&P vs 30y log trend) | 10% | Stooq | detrended percentile |
| Trailing P/E | 9% | multpl.com | level + 3y momentum blend (30y window) |
| Top-10 concentration | 8% | Slickcharts | percentile (20y window) |

## Methodology (v2)

- **Percentile rank, rolling window.** Each value is ranked against the last
  20–30 years of its own history *as known at that point in time* (no
  lookahead). A rolling window — rather than "everything since 1950" — lets the
  score adapt to structural regime shifts; v1's expanding window read "bubble
  territory" continuously from 1986 to 2000, which was useless.
- **Level + momentum blends.** Slow valuation metrics score 60% on their level
  percentile and 40% on their 3-year rate-of-change percentile. Bubbles are
  expensive *and accelerating*: 1993 was expensive but calm, 1999 was both.
- **Weights tuned to history.** Weights were fit against ten anchor episodes
  (1982, 1987, 1993, 1995, 1999–2000, 2004, 2007, 2009, 2013, 2021), blended
  50/50 with structural priors and capped at 5–18% so no metric dominates and
  the fit can't overreach the ~4 true bubbles in the sample.
- **Composite** = Σ(wᵢ·scoreᵢ)/Σ(wᵢ over available metrics). A metric is
  dropped (weights renormalized) if its source hasn't updated within 2× its
  normal cadence. Headline number = 3-month rolling mean. The unweighted median
  is published alongside as a robustness check.
- **Bands:** 0–20 depressed · 20–40 below average · 40–60 normal ·
  60–80 elevated · 80–100 bubble territory.

Backtest anchors (point-in-time): Aug 1982 → 18 · Aug 1987 → **77** (warns
before Black Monday) · Jun 1993 → 69 · Mar 2000 → **95** (all-time high) ·
Jun 2004 → 48 · Oct 2007 → 58 · Mar 2009 → 21 · Jun 2013 → 49 · Dec 2021 → 84.

## Known data caveats

- **Margin debt before 2025** and **top-10 concentration history** use embedded
  estimates from published references (marked in `compute.py`). The FINRA
  fetcher replaces margin history from their full Excel file on first
  successful run; top-10 builds real daily history going forward via
  `data/top10_history.csv`.
- S&P monthly prices from the multpl fallback are monthly *averages*
  (Shiller-style), not closes; Stooq closes take over once fetched.
- Forward P/E was deliberately excluded (no reliable free feed); trailing P/E
  + CAPE cover the valuation block.

## Deploy (GitHub Pages, free)

1. Push this repo to GitHub.
2. Settings → Pages → Source: *Deploy from branch* → branch `main`, folder `/docs`.
3. Settings → Actions → General → Workflow permissions: *Read and write*.
4. The included workflow (`.github/workflows/update.yml`) refreshes data daily
   at 13:30 UTC and commits `docs/data.json`. Run it once manually
   (Actions → Daily data refresh → Run workflow) to go live with fresh data.

Local run: `pip install -r requirements.txt && python fetch_data.py && python compute.py`,
then serve `docs/` (e.g. `python -m http.server -d docs`).

## Disclaimer

Not investment advice. Valuation composites are poor short-term timers — the
market stayed "overvalued" from 1996 to 2000. Read the score as "how stretched
are conditions versus history," not "sell now."
