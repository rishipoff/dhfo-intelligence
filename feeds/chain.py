"""Chained price feed (the default).

For each ticker, tries the layers in order and stops at the first that yields a
price:

    1. yahoo   -> live-delayed quote (yfinance)         as_of = today
    2. nse     -> NSE public quote (best-effort)        as_of = today
    3. manual  -> data/prices.json hand snapshot        as_of = prices.json date

Unlike the single-source feeds, this one returns a *detailed* mapping so the API
and dashboard can show provenance:

    {ticker: {"price": float | None, "source": "yahoo"|"nse"|"manual"|None,
              "as_of": str | None}}

Each layer is called once for the whole batch (so their 60s caches apply), and
the merged result is itself cached for 60 seconds.
"""

from __future__ import annotations

import datetime
import threading
import time

from . import manual, nse, yahoo

CACHE_TTL = 60  # seconds
SANITY_TOLERANCE = 0.15  # reject a live price >15% away from the manual reference

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}  # ticker -> (ts, {price,source,as_of,...})


def _today() -> str:
    return datetime.date.today().strftime("%d-%b-%Y")


def _passes_sanity(price: float | None, reference: float | None) -> bool:
    """True if price is within SANITY_TOLERANCE of the reference.

    No reference for a ticker => nothing to check against => pass. This guards
    against a feed returning a dividend-adjusted / stale value far from the true
    traded price, which would inflate the yield and could flip the cheap/rich
    signal.
    """
    if price is None:
        return False
    if reference is None or reference <= 0:
        return True
    return abs(price / reference - 1.0) <= SANITY_TOLERANCE


def _safe(feed, tickers: list[str]) -> dict[str, float | None]:
    """Call a layer's get_prices, never propagating an error."""
    try:
        return feed.get_prices(tickers)
    except NotImplementedError:
        return {t: None for t in tickers}
    except Exception:
        return {t: None for t in tickers}


def get_prices(tickers: list[str]) -> dict[str, dict]:
    now = time.time()
    result: dict[str, dict] = {}
    pending: list[str] = []

    with _lock:
        for t in tickers:
            hit = _cache.get(t)
            if hit and now - hit[0] < CACHE_TTL:
                result[t] = hit[1]
            else:
                pending.append(t)

    if not pending:
        return result

    today = _today()
    manual_as_of = manual.data_as_of()
    references = manual.get_prices(pending)  # {ticker: reference price | None}

    yahoo_px = _safe(yahoo, pending)
    # A yahoo price that fails the sanity gate is treated as unavailable, so NSE
    # is asked for it too (alongside the names yahoo simply didn't cover).
    def yahoo_ok(t):
        return _passes_sanity(yahoo_px.get(t), references.get(t))

    nse_needed = [t for t in pending if not yahoo_ok(t)]
    nse_px = _safe(nse, nse_needed) if nse_needed else {}
    manual_px = references  # manual feed == the reference snapshot

    for t in pending:
        ref = references.get(t)
        rejected = False  # a live price was dropped by the sanity gate

        yp = yahoo_px.get(t)
        np = nse_px.get(t)

        if yp is not None and _passes_sanity(yp, ref):
            entry = {"price": yp, "source": "yahoo", "as_of": today}
        elif np is not None and _passes_sanity(np, ref):
            if yp is not None:  # yahoo had a value but it was rejected
                rejected = True
            entry = {"price": np, "source": "nse", "as_of": today}
        elif manual_px.get(t) is not None:
            if yp is not None or np is not None:  # a live price existed but was rejected
                rejected = True
            entry = {"price": manual_px[t], "source": "manual", "as_of": manual_as_of}
        else:
            entry = {"price": None, "source": None, "as_of": None}

        entry["reference"] = ref
        entry["sanity_rejected"] = rejected

        with _lock:
            _cache[t] = (time.time(), entry)
        result[t] = entry

    return result
