#!/usr/bin/env python3
"""Stock Bubble Index — scoring engine (v2).
Reads data/*.csv, writes docs/data.json for the static site.

Method (see README):
- Rolling-window percentile rank (20y/30y), point-in-time — the market is
  compared against the last generation, not against 1955. This fixes the
  v1 failure where an expanding window read "bubble" continuously 1986-2000.
- Slow valuation metrics (CAPE, P/E, household allocation, Buffett) blend
  the LEVEL percentile (60%) with the 3-year RATE-OF-CHANGE percentile (40%):
  bubbles are expensive AND accelerating; 1993 was expensive but calm.
- Margin debt = 50% detrended level + 50% 12-mo growth. ERP inverted.
  Trend = deviation from rolling 30y log-trend.
- Weights tuned to historical episodes (1982, 1987, 1993, 1995, 1999-2000,
  2004, 2007, 2009, 2013, 2021), blended 50/50 with structural priors and
  capped to avoid overfitting to ~4 bubbles.
- Composite renormalized over non-stale metrics; headline = 3-mo smoothing.
"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "docs", "data.json")

WEIGHTS = {"cape": .14, "household": .13, "buffett": .11, "erp": .11, "ps": .12,
           "pe": .09, "margin": .12, "top10": .08, "trend": .10}
CADENCE = {"cape": 1, "pe": 1, "erp": 1, "ps": 3, "household": 3, "buffett": 3,
           "margin": 1, "top10": 1, "trend": 1}  # months; stale if > 2x

def load(name):
    df = pd.read_csv(os.path.join(DATA, name), parse_dates=["date"])
    df["date"] = df["date"].values.astype("datetime64[M]")
    return df.sort_values("date").groupby("date")["value"].last()

def roll_pct(s, min_obs=120, invert=False, win=360):
    v = s.values
    out = np.full(len(s), np.nan)
    for i in range(len(s)):
        if i + 1 < min_obs:
            continue
        h = v[max(0, i - win + 1): i + 1]
        out[i] = 100.0 * ((h >= v[i]).mean() if invert else (h <= v[i]).mean())
    return pd.Series(out, index=s.index)

def roll_detr(s, min_fit=120, win=360):
    ls = np.log(s.values)
    t = np.arange(len(s), dtype=float)
    r = np.full(len(s), np.nan)
    for i in range(len(s)):
        if i + 1 < min_fit:
            continue
        j = max(0, i - win + 1)
        b, a = np.polyfit(t[j:i + 1], ls[j:i + 1], 1)
        r[i] = ls[i] - (a + b * t[i])
    return roll_pct(pd.Series(r, index=s.index).dropna(), min_obs=1, win=win)

# ---------------- embedded historical backfills (pre-feed eras) ----------------
MD_EST = {
 "1970-12":3.8,"1971-12":5.3,"1972-12":7.9,"1973-12":5.0,"1974-12":3.8,"1975-12":4.5,
 "1976-12":8.2,"1977-12":9.9,"1978-12":11.0,"1979-12":11.6,"1980-12":14.5,"1981-12":14.4,
 "1982-12":13.3,"1983-12":23.0,"1984-12":22.5,"1985-12":28.7,"1986-12":36.8,"1987-12":31.2,
 "1988-12":32.7,"1989-12":34.9,"1990-12":28.3,"1991-12":36.7,"1992-12":44.0,"1993-12":60.7,
 "1994-12":57.5,"1995-12":77.2,"1996-12":90.3,"1997-12":126.8,"1998-12":141.0,"1999-12":228.5,
 "2000-03":278.5,"2000-12":198.8,"2001-12":150.0,"2002-12":134.2,"2003-12":172.8,"2004-12":199.5,
 "2005-12":221.7,"2006-12":275.4,"2007-07":381.4,"2007-12":322.8,"2008-12":186.6,"2009-12":231.0,
 "2010-12":276.6,"2011-12":267.9,"2012-12":330.1,"2013-12":444.9,"2014-12":456.8,"2015-12":447.4,
 "2016-12":473.2,"2017-12":642.8,"2018-05":668.9,"2018-12":554.3,"2019-12":579.2,"2020-12":778.0,
 "2021-10":935.9,"2021-12":910.0,"2022-12":654.0,"2023-12":700.9,"2024-12":899.2}
T10_EST = {"1970":31,"1972":33,"1975":28,"1980":25,"1985":20,"1990":19,"1993":17,"1995":18,
 "1998":22,"2000":25.5,"2002":23,"2005":20,"2007":19,"2009":19.5,"2011":19,"2013":17.5,
 "2015":18,"2016":19,"2017":20,"2018":21,"2019":22.5,"2020":28.5,"2021":29.5,"2022":26,
 "2023":30.5,"2024":34.5,"2025":36.0}

def main():
    cape, pe, ps = load("cape.csv"), load("pe.csv"), load("ps.csv")
    gs10, gdp = load("gs10.csv"), load("gdp.csv")
    eq_all, hh, spx = load("equities_all.csv"), load("household_equity_pct.csv"), load("spx_monthly.csv")

    md_real = load("margin_debt.csv")  # $M
    md_est = pd.Series({pd.Period(k).to_timestamp(): v * 1000 for k, v in MD_EST.items()})
    md = pd.concat([md_est[md_est.index < md_real.index.min()], md_real]).sort_index()
    md.index = md.index.values.astype("datetime64[M]")

    t10 = pd.Series({pd.Timestamp(f"{y}-12-01"): v for y, v in T10_EST.items()})
    t10_path = os.path.join(DATA, "top10_history.csv")
    if os.path.exists(t10_path):
        real = load("top10_history.csv")
        t10 = pd.concat([t10[t10.index < real.index.min()], real]).sort_index()

    end = max(cape.index.max(), spx.index.max())
    grid = pd.date_range("1950-01-01", end, freq="MS")
    og = lambda s, limit=None: s.reindex(grid).ffill(limit=limit)

    cape_m, pe_m, gs10_m = og(cape), og(pe), og(gs10, 2)
    ps_m, hh_m, gdp_m, spx_m = og(ps, 4), og(hh, 4), og(gdp, 4), og(spx)
    md_m = og(md, 14)
    t10_m = t10.reindex(grid).interpolate(limit_area="inside")

    buffett = (og(eq_all, 4) / 1000.0) / gdp_m * 100
    erp = (1.0 / cape_m * 100.0) - gs10_m
    md_gdp = (md_m / 1000.0) / gdp_m * 100
    md_yoy = md_m.pct_change(12) * 100

    def lvl_chg(s, win, alpha=0.6, chg_m=36):
        """60% level percentile + 40% 3-year change percentile."""
        lvl = roll_pct(s.dropna(), win=win)
        chg = roll_pct(s.dropna().pct_change(chg_m).dropna(), win=win)
        return (alpha * lvl.reindex(grid) + (1 - alpha) * chg.reindex(grid))

    scores, raws = {}, {}
    scores["cape"] = lvl_chg(cape_m, 360);        raws["cape"] = cape_m
    scores["pe"] = lvl_chg(pe_m, 360);            raws["pe"] = pe_m
    scores["household"] = lvl_chg(hh_m, 360);     raws["household"] = hh_m
    scores["buffett"] = lvl_chg(buffett, 240);    raws["buffett"] = buffett
    scores["erp"] = roll_pct(erp.dropna(), invert=True, win=240); raws["erp"] = erp
    scores["ps"] = roll_pct(ps_m.dropna(), min_obs=20);           raws["ps"] = ps_m
    scores["trend"] = roll_detr(spx_m.dropna(), win=360);         raws["trend"] = spx_m
    scores["margin"] = (0.5 * roll_detr(md_gdp.dropna(), win=360).reindex(grid)
                        + 0.5 * roll_pct(md_yoy.dropna(), min_obs=60, win=360).reindex(grid))
    raws["margin"] = md_gdp
    scores["top10"] = roll_pct(t10_m.dropna(), min_obs=60, win=240); raws["top10"] = t10_m

    # staleness rule
    now = pd.Timestamp.today().to_period("M").to_timestamp()
    stale = {}
    S = pd.DataFrame({k: v.reindex(grid) for k, v in scores.items()})
    for k in WEIGHTS:
        last_obs = S[k].dropna().index.max()
        months_old = (now.year - last_obs.year) * 12 + now.month - last_obs.month
        stale[k] = bool(months_old > 2 * CADENCE[k])
        if stale[k]:
            S.loc[S.index > last_obs - pd.DateOffset(months=1), k] = np.nan

    W = pd.DataFrame({k: (~S[k].isna()) * w for k, w in WEIGHTS.items()})
    composite = (S.fillna(0) * W).sum(axis=1) / W.sum(axis=1)
    headline = composite.rolling(3, min_periods=1).mean()
    median9 = S.median(axis=1)

    bt = pd.DataFrame({"composite": composite, "headline": headline, "median": median9})
    bt = bt[bt.index >= "1975-01-01"]

    fmt = lambda d: d.strftime("%Y-%m")
    out = {"generated": pd.Timestamp.today().strftime("%Y-%m-%d"),
           "weights": WEIGHTS, "stale": stale,
           "current": {"headline": round(bt.headline.iloc[-1], 1),
                       "composite": round(bt.composite.iloc[-1], 1),
                       "median": round(bt["median"].iloc[-1], 1)},
           "series": {"composite": [[fmt(d), None if np.isnan(v) else round(v, 1)]
                                    for d, v in zip(bt.index, bt.headline)]}}
    for k in WEIGHTS:
        sc, rv = S[k].reindex(bt.index), raws[k].reindex(bt.index)
        out["series"][k] = {
            "score": [[fmt(d), None if np.isnan(v) else round(v, 1)] for d, v in zip(bt.index, sc)],
            "raw": [[fmt(d), None if np.isnan(v) else round(float(v), 2)] for d, v in zip(bt.index, rv)]}

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"Bubble Index: {out['current']['headline']} | wrote {OUT} ({os.path.getsize(OUT)//1024} KB)")
    for d in ["1982-08","1987-08","1993-06","2000-03","2007-10","2009-03","2013-06","2021-12"]:
        print(f"  {d}: {bt.headline.loc[d+'-01']:.1f}")
    if any(stale.values()):
        print("STALE (excluded):", [k for k, v in stale.items() if v], file=sys.stderr)

if __name__ == "__main__":
    main()
