"""NSE public-quote feed.

Fetches the last-traded price for each ticker from NSE's public quote API using
the trust's NSE symbol (the ``ticker`` field from dpu.json, e.g. ``INDIGRID``,
``EMBASSY``). NSE gates its API behind a cookie handshake and rate-limits
aggressively, so this module:

  * primes a ``requests.Session`` with browser-like headers and a homepage visit
    to acquire cookies, refreshing them on 401/403;
  * looks each symbol up across the equity / ETF / trust quote endpoints;
  * returns ``None`` for anything it cannot resolve (BSE-only names such as the
    numeric ``543925``, delisted symbols, rate-limits) rather than raising.

Results are cached for ``CACHE_TTL`` seconds so a burst of dashboard requests
hits NSE at most once per minute.
"""

from __future__ import annotations

import threading
import time

import requests

CACHE_TTL = 60  # seconds

_BASE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_BASE}/get-quotes/equity",
    "Connection": "keep-alive",
}

# Quote endpoints tried in order. NSE serves REIT/InvIT units through the same
# quote-equity path as ordinary equities; the extra paths are cheap fallbacks.
_QUOTE_PATHS = [
    "/api/quote-equity?symbol={sym}",
    "/api/quote-equity?symbol={sym}&section=trade_info",
]

_lock = threading.Lock()
_cache: dict[str, tuple[float, float | None]] = {}  # symbol -> (ts, price)
_session: requests.Session | None = None


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        # Homepage visit seeds the anti-bot cookies the API requires.
        s.get(_BASE, timeout=8)
        s.get(f"{_BASE}/market-data/live-market-indices", timeout=8)
    except requests.RequestException:
        pass
    return s


def _get_session(refresh: bool = False) -> requests.Session:
    global _session
    if _session is None or refresh:
        _session = _new_session()
    return _session


def _extract_price(payload: dict) -> float | None:
    """Pull a last-traded price out of an NSE quote payload."""
    if not isinstance(payload, dict):
        return None
    price_info = payload.get("priceInfo") or {}
    for value in (price_info.get("lastPrice"), price_info.get("close"), price_info.get("open")):
        if value in (None, "", "-"):
            continue
        try:
            price = float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


def _fetch_one(sym: str) -> float | None:
    """Best-effort single-symbol fetch. Returns None on any failure."""
    for attempt in range(2):
        session = _get_session(refresh=attempt > 0)
        for path in _QUOTE_PATHS:
            url = _BASE + path.format(sym=sym)
            try:
                resp = session.get(url, timeout=8)
            except requests.RequestException:
                continue
            if resp.status_code in (401, 403):
                break  # cookies stale — refresh session on next attempt
            if resp.status_code == 429:
                time.sleep(0.5)
                break
            if resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except ValueError:
                continue
            price = _extract_price(data)
            if price is not None:
                return price
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
        sym = (t or "").strip().upper()
        # Purely numeric codes are BSE scrip codes — NSE cannot serve them.
        price = None if not sym or sym.isdigit() else _fetch_one(sym)
        with _lock:
            _cache[t] = (time.time(), price)
        out[t] = price
        # Gentle spacing so we don't trip NSE's rate limiter.
        time.sleep(0.25)

    return out
