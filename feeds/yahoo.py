"""Yahoo Finance feed (via yfinance).

Layer 1 of the price chain. Provides *live-delayed* quotes for the trusts that
Yahoo actually covers. The ticker -> Yahoo-symbol map below is empirically
confirmed: the large/liquid names resolve under ``.NS`` (NSE), while several
newer / BSE-listed InvITs only resolve under ``.BO`` (BSE). Four names have no
Yahoo coverage at all (NHIT, VERTIS, ROADSTAR, RIIT) and are intentionally
absent — the chain falls through to NSE / manual for those.

get_prices returns {ticker: price | None}. Any symbol not in the map, or that
yfinance cannot price, returns None. Results are cached for 60 seconds.
"""

from __future__ import annotations

import threading
import time

# Confirmed ticker -> Yahoo symbol map (probed live; see feeds/README notes).
YAHOO_SYMBOLS: dict[str, str] = {
    # NSE-listed, resolve under .NS
    "IRBINVIT": "IRBINVIT.NS",
    "INDIGRID": "INDIGRID.NS",
    "PGINVIT": "PGINVIT.NS",
    "EMBASSY": "EMBASSY.NS",
    "MINDSPACE": "MINDSPACE.NS",
    "BIRET": "BIRET.NS",
    "NXST": "NXST.NS",
    # Only resolve under .BO (BSE) on Yahoo
    "CUBEINVIT": "CUBEINVIT.BO",
    "543925": "MIT.BO",           # Maple Infrastructure Trust
    "INDUSINVIT": "INDUSINVIT.BO",
    "ANANTAM": "ANANTAM.BO",
    "CAPINVIT": "CAPINVIT.BO",
    "CITIUSINVT": "CITIUSINVT.BO",
    "KRT": "KRT.BO",
    # No Yahoo coverage: NHIT, VERTIS, ROADSTAR, RIIT  -> handled downstream
}

CACHE_TTL = 60  # seconds

_lock = threading.Lock()
_cache: dict[str, tuple[float, float | None]] = {}  # ticker -> (ts, price)


def _price_for_symbol(symbol: str) -> float | None:
    """Best-effort single-symbol fetch via yfinance. None on any failure.

    Uses the *raw last-traded close* from history(period="5d",
    auto_adjust=False). This is deliberate: for high-distribution .NS names
    Yahoo's fast_info.last_price / regularMarketPrice return a wrong (low) value
    — e.g. INDIGRID.NS reports 140.06 there vs a true 178.56 in the daily close —
    which would inflate the yield and can FLIP the cheap/rich signal. The daily
    Close matches our references for both .NS and .BO venues, so we use it
    exclusively and do not fall back to fast_info.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="5d", auto_adjust=False)
        if not hist.empty:
            p = float(hist["Close"].iloc[-1])
            if p > 0:
                return p
    except Exception:
        return None
    return None


def get_prices(tickers: list[str]) -> dict[str, float | None]:
    """Return {ticker: last_price | None} for the requested tickers, cached 60s."""
    now = time.time()
    out: dict[str, float | None] = {}
    to_fetch: list[str] = []

    with _lock:
        for t in tickers:
            hit = _cache.get(t)
            if hit and now - hit[0] < CACHE_TTL:
                out[t] = hit[1]
            else:
                to_fetch.append(t)

    for t in to_fetch:
        symbol = YAHOO_SYMBOLS.get(t)
        price = _price_for_symbol(symbol) if symbol else None
        with _lock:
            _cache[t] = (time.time(), price)
        out[t] = price

    return out
