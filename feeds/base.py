"""Feed base contract.

Every feed exposes a single function:

    get_prices(tickers: list[str]) -> dict[str, float | None]

which returns the latest traded price for each requested ticker, or ``None``
for any symbol whose price could not be resolved (unknown symbol, rate-limit,
network error, or a venue this feed does not cover). Feeds must never raise for
an individual bad symbol — they degrade to ``None`` instead.
"""

from __future__ import annotations

from typing import Protocol


class Feed(Protocol):
    """Structural type a feed module satisfies."""

    def get_prices(self, tickers: list[str]) -> dict[str, float | None]:
        ...


def get_prices(tickers: list[str]) -> dict[str, float | None]:
    """Default no-op implementation. Real feeds override this."""
    return {t: None for t in tickers}
