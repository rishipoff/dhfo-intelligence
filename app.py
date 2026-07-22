"""DHFO Intelligence — FastAPI backend.

Market analysis only. Reads data/dpu.json and data/medians.json, fetches live
prices from the configured feed, and serves a dashboard of Indian REITs and
InvITs. There are deliberately NO holdings, positions, cost, or P&L anywhere.
"""

from __future__ import annotations

import datetime
import importlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

FEED_NAME = os.getenv("FEED", "chain").strip().lower()

app = FastAPI(title="DHFO Intelligence", version="1.0.0")


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def _load_json(name: str) -> dict:
    with open(DATA_DIR / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_dpu() -> dict:
    return _load_json("dpu.json")


def load_medians() -> dict:
    return _load_json("medians.json")


def _median_index(medians: dict) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for bucket in ("invits", "reits"):
        for row in medians.get(bucket, []):
            idx[row["ticker"]] = row
    return idx


def all_trusts(dpu: dict) -> list[dict]:
    return list(dpu.get("invits", [])) + list(dpu.get("reits", []))


# --------------------------------------------------------------------------- #
# Feed selection
# --------------------------------------------------------------------------- #
def get_feed():
    """Import the feed module named by the FEED env var (default: chain)."""
    try:
        return importlib.import_module(f"feeds.{FEED_NAME}")
    except ModuleNotFoundError:
        return importlib.import_module("feeds.chain")


def _today() -> str:
    return datetime.date.today().strftime("%d-%b-%Y")


def fetch_prices(tickers: list[str]) -> dict[str, dict]:
    """Return {ticker: {"price", "source", "as_of"}} regardless of feed shape.

    The chain feed already returns this detailed form. Single-source feeds return
    plain floats, which we wrap here — tagging the source with the feed name and
    the as_of with today (or the manual snapshot date for FEED=manual).
    """
    feed = get_feed()
    try:
        raw = feed.get_prices(tickers)
    except NotImplementedError:
        # A stub feed (e.g. breeze) — degrade gracefully rather than crash.
        raw = {t: None for t in tickers}
    except Exception:  # never let a feed failure take down the API
        raw = {t: None for t in tickers}

    today = _today()
    manual_as_of = None
    if FEED_NAME == "manual":
        try:
            manual_as_of = importlib.import_module("feeds.manual").data_as_of()
        except Exception:
            manual_as_of = None

    out: dict[str, dict] = {}
    for t in tickers:
        v = raw.get(t)
        if isinstance(v, dict):  # chain feed — already detailed
            out[t] = {
                "price": v.get("price"),
                "source": v.get("source"),
                "as_of": v.get("as_of"),
                "reference": v.get("reference"),
                "sanity_rejected": bool(v.get("sanity_rejected")),
            }
        elif v is None:
            out[t] = {"price": None, "source": None, "as_of": None,
                      "reference": None, "sanity_rejected": False}
        else:
            out[t] = {
                "price": float(v),
                "source": FEED_NAME,
                "as_of": manual_as_of if FEED_NAME == "manual" else today,
                "reference": None,
                "sanity_rejected": False,
            }
    return out


# --------------------------------------------------------------------------- #
# Post-tax computation (from keep_factors — no hardcoded tax math)
# --------------------------------------------------------------------------- #
def quarter_post_tax(quarter: dict, keep_factors: dict[str, float]) -> float:
    """post_tax = sum(component * keep_factor[component]) for one quarter."""
    total = 0.0
    for comp, value in (quarter.get("components") or {}).items():
        factor = keep_factors.get(comp, 1.0)
        total += (value or 0.0) * factor
    return total


def post_tax_fy(trust: dict, keep_factors: dict[str, float]) -> float | None:
    """Full-year post-tax DPU: sum of per-quarter post-tax over tracked quarters."""
    if not trust.get("quarters_tracked"):
        return None
    quarters = trust.get("quarters") or []
    if not quarters:
        return None
    return sum(quarter_post_tax(q, keep_factors) for q in quarters)


# --------------------------------------------------------------------------- #
# Partial-year annualization
# --------------------------------------------------------------------------- #
def annualization_factor(trust: dict) -> float:
    """Scale a partial-FY DPU (fewer than 4 tracked quarters/distributions) up to
    a full-year figure. A trust with 3 quarters -> x4/3, 2 distributions -> x4/2.
    Full years (4 quarters) and untracked trusts (whose reported dpu_fy is already
    full-year) return 1.0 (no scaling)."""
    if not trust.get("quarters_tracked"):
        return 1.0
    n = len(trust.get("quarters") or [])
    if 0 < n < 4:
        return 4.0 / n
    return 1.0


# --------------------------------------------------------------------------- #
# Median reliability (for headline KPIs)
# --------------------------------------------------------------------------- #
def median_reliable(trust: dict, med: dict) -> bool:
    """A median is headline-worthy only if it has a real 3yr value, is built from
    >= 3 fiscal years of history, and the trust's DPU is not flagged UNVERIFIED."""
    if med.get("median_3yr_yield") is None:
        return False
    if len(med.get("yields_by_fy") or {}) < 3:
        return False
    if "UNVERIFIED" in (trust.get("flags") or "").upper():
        return False
    return True


def now_ist() -> str:
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    return datetime.datetime.now(ist).strftime("%d-%b-%Y %H:%M IST")


# --------------------------------------------------------------------------- #
# Signal (cheap / rich / fair)
# --------------------------------------------------------------------------- #
def classify(current: float | None, median: float | None) -> str | None:
    """cheap if current > median, rich if below, fair if equal; None if unknown."""
    if current is None or median is None:
        return None
    if current > median:
        return "cheap"
    if current < median:
        return "rich"
    return "fair"


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/prices")
def api_prices():
    dpu = load_dpu()
    tickers = [t["ticker"] for t in all_trusts(dpu)]
    # {ticker: {price, source, as_of}}
    return JSONResponse(fetch_prices(tickers))


@app.get("/api/data")
def api_data():
    dpu = load_dpu()
    medians = load_medians()
    keep_factors = dpu.get("keep_factors", {})
    med_idx = _median_index(medians)

    tickers = [t["ticker"] for t in all_trusts(dpu)]
    prices = fetch_prices(tickers)

    rows = []
    for trust in all_trusts(dpu):
        ticker = trust["ticker"]
        pinfo = prices.get(ticker) or {}
        price = pinfo.get("price")

        dpu_fy_raw = trust.get("dpu_fy")
        pt_fy_raw = post_tax_fy(trust, keep_factors)

        # Annualize partial-year DPU up to a full-year basis for the yields/charts.
        factor = annualization_factor(trust)
        n_quarters = len(trust.get("quarters") or []) if trust.get("quarters_tracked") else 0
        annualized = factor != 1.0
        dpu_fy = dpu_fy_raw * factor if dpu_fy_raw is not None else None
        pt_fy = pt_fy_raw * factor if pt_fy_raw is not None else None

        pre_tax_yield = (dpu_fy / price) if (dpu_fy and price) else None
        post_tax_yield = (pt_fy / price) if (pt_fy and price) else None

        med = med_idx.get(ticker, {})
        median_3yr = med.get("median_3yr_yield")
        median_5yr = med.get("median_5yr_yield")

        rows.append(
            {
                "ticker": ticker,
                "exchange_ticker": trust.get("exchange_ticker"),
                "name": trust.get("name"),
                "class": trust.get("class"),
                # dpu_fy is the (possibly annualized) full-year figure used for yields;
                # dpu_fy_reported keeps the raw as-filed number for reference.
                "dpu_fy": round(dpu_fy, 4) if dpu_fy is not None else None,
                "dpu_fy_reported": dpu_fy_raw,
                "post_tax_dpu_fy": round(pt_fy, 4) if pt_fy is not None else None,
                "annualized": annualized,
                "n_quarters": n_quarters,
                "annualization_factor": round(factor, 4),
                "tax_status": trust.get("tax_status"),
                "quarters_tracked": bool(trust.get("quarters_tracked")),
                "price": price,
                "price_source": pinfo.get("source"),
                "price_as_of": pinfo.get("as_of"),
                "price_reference": pinfo.get("reference"),
                "price_sanity_rejected": bool(pinfo.get("sanity_rejected")),
                "pre_tax_yield": pre_tax_yield,
                "post_tax_yield": post_tax_yield,
                "median_3yr_yield": median_3yr,
                "median_5yr_yield": median_5yr,
                "median_reliable": median_reliable(trust, med),
                # Signal compares the *current* (pre-tax) yield to the medians,
                # matching how the medians themselves are defined (DPU_FY / price).
                "signal_3yr": classify(pre_tax_yield, median_3yr),
                "signal_5yr": classify(pre_tax_yield, median_5yr),
                "flags": trust.get("flags"),
            }
        )

    return JSONResponse(
        {
            "snapshot_as_of": dpu.get("as_of"),
            "refreshed_at": now_ist(),
            "currency": dpu.get("currency", "INR"),
            "feed": FEED_NAME,
            "gsec_benchmark": dpu.get("gsec_benchmark"),
            "tax_rates_applied": dpu.get("tax_rates_applied"),
            "trusts": rows,
        }
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "dashboard.html")
