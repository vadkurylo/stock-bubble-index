#!/usr/bin/env python3
"""Stock Bubble Index — data fetcher.
Pulls all raw series into data/*.csv (date,value; ISO dates; ascending).
Sources: FRED (no key needed, fredgraph.csv), multpl.com, Stooq, FINRA, Slickcharts.
Each fetcher is independent: a failure logs a warning and leaves the previous
CSV in place (compute.py applies the staleness rule).
"""
import io, os, re, sys, datetime as dt
import pandas as pd
import requests

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; StockBubbleIndex/1.0)"}

def save(name, df):
    df = df.dropna().sort_values("date")
    df.to_csv(os.path.join(DATA, name), index=False)
    print(f"  {name}: {len(df)} rows, {df.date.iloc[0].date()} → {df.date.iloc[-1].date()}, last={df.value.iloc[-1]}")

def fred(series_id, name):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text)).rename(columns=str.lower)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    save(name, df)

def multpl(slug, name, freq="by-month"):
    url = f"https://www.multpl.com/{slug}/table/{freq}"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    df = pd.read_html(io.StringIO(r.text))[0]
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"].astype(str).str.replace(r"[^\d.]", "", regex=True), errors="coerce")
    save(name, df)

def stooq_spx(name):
    url = "https://stooq.com/q/d/l/?s=%5Espx&i=m"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df.rename(columns=str.lower)[["date", "close"]].rename(columns={"close": "value"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[df.date >= "1950-01-01"]
    save(name, df)

def finra_margin(name):
    """Find the margin-statistics Excel file linked from FINRA's page and parse it."""
    page = "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics"
    r = requests.get(page, headers=UA, timeout=30); r.raise_for_status()
    links = re.findall(r'href="([^"]+\.xlsx?)"', r.text)
    if not links:
        raise RuntimeError("no xlsx link found on FINRA page")
    url = links[0]
    if url.startswith("/"):
        url = "https://www.finra.org" + url
    x = requests.get(url, headers=UA, timeout=60); x.raise_for_status()
    xl = pd.read_excel(io.BytesIO(x.content), sheet_name=0)
    # first col = month, debit balances in margin accounts = the margin-debt column
    xl.columns = [str(c).strip().lower() for c in xl.columns]
    datecol = xl.columns[0]
    debit = next(c for c in xl.columns if "debit" in c)
    df = xl[[datecol, debit]].rename(columns={datecol: "date", debit: "value"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # $ millions
    save(name, df)

def slickcharts_top10(name):
    url = "https://www.slickcharts.com/sp500"
    r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    df = pd.read_html(io.StringIO(r.text))[0]
    wcol = next(c for c in df.columns if "weight" in str(c).lower() or "%" in str(c))
    w = pd.to_numeric(df[wcol].astype(str).str.replace("%", ""), errors="coerce")
    top10 = w.nlargest(10).sum()
    # append today's snapshot to a growing history file
    path = os.path.join(DATA, name)
    hist = pd.read_csv(path, parse_dates=["date"]) if os.path.exists(path) else pd.DataFrame(columns=["date", "value"])
    today = pd.Timestamp(dt.date.today())
    hist = hist[hist.date != today]
    hist = pd.concat([hist, pd.DataFrame({"date": [today], "value": [round(top10, 2)]})])
    save(name, hist)

JOBS = [
    ("GDP (FRED)",                lambda: fred("GDP", "gdp.csv")),
    ("10Y Treasury (FRED)",       lambda: fred("GS10", "gs10.csv")),
    ("Corporate equities (FRED)", lambda: fred("BOGZ1LM893064105Q", "equities_all.csv")),
    ("Household alloc (FRED)",    lambda: fred("BOGZ1FL153064486Q", "household_equity_pct.csv")),
    ("CAPE (multpl)",             lambda: multpl("shiller-pe", "cape.csv")),
    ("Trailing P/E (multpl)",     lambda: multpl("s-p-500-pe-ratio", "pe.csv")),
    ("P/S (multpl)",              lambda: multpl("s-p-500-price-to-sales", "ps.csv", "by-quarter")),
    ("S&P 500 monthly (Stooq)",   lambda: stooq_spx("spx_monthly.csv")),
    ("Margin debt (FINRA)",       lambda: finra_margin("margin_debt.csv")),
    ("Top-10 weight (Slickcharts)", lambda: slickcharts_top10("top10_history.csv")),
]

if __name__ == "__main__":
    failures = 0
    for label, job in JOBS:
        print(label)
        try:
            job()
        except Exception as e:
            failures += 1
            print(f"  WARNING: {e} — keeping previous file if any", file=sys.stderr)
    sys.exit(0 if failures < len(JOBS) else 1)
