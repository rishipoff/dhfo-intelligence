"""Manual price feed.

Layer 3 (last resort) of the price chain. Reads a hand-maintained snapshot from
data/prices.json for names no live feed can quote (illiquid trusts, no Yahoo
symbol). get_prices returns {ticker: price | None}; data_as_of() returns the
snapshot date so callers can tag manual prices as "manual <date>".
"""

from __future__ import annotations

import json
from pathlib import Path

_PRICES_FILE = Path(__file__).resolve().parent.parent / "data" / "prices.json"


def _load() -> dict:
    try:
        with open(_PRICES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def data_as_of() -> str | None:
    """Date of the manual snapshot, e.g. '14-Jul-2026' (None if unavailable)."""
    return _load().get("as_of")


def get_prices(tickers: list[str]) -> dict[str, float | None]:
    """Return {ticker: manual_price | None} from data/prices.json."""
    prices = _load().get("prices", {})
    out: dict[str, float | None] = {}
    for t in tickers:
        val = prices.get(t)
        try:
            out[t] = float(val) if val is not None else None
        except (TypeError, ValueError):
            out[t] = None
    return out
