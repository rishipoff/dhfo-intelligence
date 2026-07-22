# DHFO Intelligence

A small local dashboard for **Indian REITs and InvITs**. It reads two data files
(`data/dpu.json` distribution history and `data/medians.json` historical median
yields), fetches live prices from a public feed, and computes pre- and post-tax
yields plus a cheap / rich / fair relative-value signal.

> **Market analysis only — no holdings, positions, cost, or P&L anywhere.**

## What it shows

- **KPI row** — trusts tracked, median post-tax yield, cheapest and richest names vs their 3-yr median.
- **Ranked post-tax yield** bar chart (Chart.js), coloured by the cheap/rich signal.
- **Relative-value view** — current yield vs 3-yr and 5-yr median per trust.
- **Two sortable tables** (InvITs, REITs) with price, DPU, pre-/post-tax yield and the cheap/rich tag.

Post-tax DPU is computed from each quarter's component split × the `keep_factors`
already in `dpu.json` — no tax math is hardcoded in the app.

## Layout

```
app.py                # FastAPI app
feeds/base.py         # get_prices(tickers) contract
feeds/chain.py        # DEFAULT feed — yahoo -> nse -> manual, per ticker, source-tagged
feeds/yahoo.py        # Yahoo Finance (yfinance), live-delayed; confirmed symbol map
feeds/nse.py          # NSE public quote API, browser-like headers, 60s cache
feeds/manual.py       # last-resort snapshot from data/prices.json
feeds/breeze.py       # ICICI Breeze stub (NotImplementedError)
data/dpu.json         # distribution / tax-component data
data/medians.json     # 3yr / 5yr median yields
data/prices.json      # hand-maintained manual price snapshot (fallback)
static/dashboard.html # frontend (plain HTML/JS + Chart.js via CDN)
```

## Run

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open <http://localhost:8000>.

Config is read from `.env` via python-dotenv. The only setting is the feed:

```
FEED=chain    # default: yahoo -> nse -> manual, per ticker, with source tagging.
              # also selectable individually: yahoo | nse | manual | breeze(stub)
```

### API

| Endpoint      | Returns                                                              |
|---------------|---------------------------------------------------------------------|
| `GET /`       | the dashboard                                                       |
| `GET /api/prices` | `{ticker: {price, source, as_of}}` from the selected feed       |
| `GET /api/data`   | per-trust name, class, DPU, tax status, pre/post-tax yield, signal, and `price_source` / `price_as_of` |

## Notes on prices — the fallback chain

The default `chain` feed resolves each ticker independently:

1. **yahoo** (`live-delayed`) — Yahoo Finance via `yfinance`. Covers 14/18 names;
   the large REITs/InvITs resolve under `.NS`, several BSE-listed InvITs only
   under `.BO` (see the confirmed map in `feeds/yahoo.py`).
2. **nse** (`live`) — NSE public quote API. Best-effort: NSE's Akamai bot-wall
   frequently blocks scripted clients, so this returns `null` when blocked.
3. **manual** (`manual <date>`) — hand-maintained snapshot in `data/prices.json`,
   for the four names no live feed covers (NHIT, VERTIS, ROADSTAR, RIIT).

Each price is tagged with the source that supplied it and an `as_of` date (today
for yahoo/nse, the `prices.json` date for manual). Every layer caches for 60s and
degrades to `null` rather than crashing, so a `null` price simply shows as `—`.

**Raw last-traded price.** The Yahoo feed reads the daily close from
`history(period="5d", auto_adjust=False)`, *not* `fast_info.last_price`. For
high-distribution `.NS` names Yahoo's `fast_info` / `regularMarketPrice` return a
wrong (low) value — e.g. INDIGRID.NS 140.06 vs a true 178.56 — which would inflate
the yield and can flip the cheap/rich signal. The daily close matches our
references for both `.NS` and `.BO` venues.

**Sanity gate.** `feeds/chain.py` rejects any live (yahoo/nse) price more than 15%
away from that trust's reference in `data/prices.json` and falls through to the
next layer. Rejected rows are flagged (`sanity_rejected` in the API, `⚠ adj?` in
the UI). References are derived independently as `dpu_fy / current_yield` from the
workbook snapshot, so they don't depend on live Yahoo.

Update `data/prices.json` by hand as fresh quotes for the uncovered names appear.

## Share via Cloudflare tunnel

To expose your local dashboard over a temporary public URL (no account needed):

```bash
# in a second terminal, with the app already running on :8000
cloudflared tunnel --url http://localhost:8000
```

`cloudflared` prints a `https://<random>.trycloudflare.com` URL that proxies to
your local server. Install it with `brew install cloudflared` if needed. Stop the
tunnel with Ctrl-C when done. Remember: this publishes the dashboard — it still
contains market analysis only, no holdings or PII.
