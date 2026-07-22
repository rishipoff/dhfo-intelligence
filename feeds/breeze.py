"""ICICI Breeze feed — stub.

Placeholder for a future ICICI Direct Breeze API integration (authenticated,
covers BSE-only names NSE cannot serve). Not implemented yet; app.py falls back
to the NSE feed unless FEED=breeze is explicitly set.
"""

from __future__ import annotations

CACHE_TTL = 60  # seconds


def get_prices(tickers: list[str]) -> dict[str, float | None]:
    raise NotImplementedError(
        "The ICICI Breeze feed is not implemented yet. Set FEED=nse (default)."
    )
