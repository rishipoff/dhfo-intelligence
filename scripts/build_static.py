#!/usr/bin/env python3
"""Build a static snapshot of the DHFO Intelligence dashboard.

Runs the EXACT same pipeline the FastAPI app serves at /api/data today — the
chain price feed (yahoo -> nse -> manual) plus the DPU / median / tax
computation — and writes the resulting JSON to docs/data.json, with an added
IST "generated_at" timestamp.

This does not touch or replace the running app; it just captures a point-in-time
snapshot that docs/index.html can render with no server.

Usage:
    python scripts/build_static.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"

# Import the app so we reuse its pipeline verbatim — single source of truth.
sys.path.insert(0, str(PROJECT_ROOT))
import app  # noqa: E402


def build() -> dict:
    """Call the app's /api/data handler and return its payload as a dict."""
    response = app.api_data()  # JSONResponse
    payload = json.loads(response.body)
    # Stamp when this static snapshot was generated (IST), reusing the app helper.
    payload["generated_at"] = app.now_ist()
    return payload


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    payload = build()
    out = DOCS_DIR / "data.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    trusts = payload.get("trusts", [])
    priced = sum(1 for t in trusts if t.get("price") is not None)
    print(f"Wrote {out.relative_to(PROJECT_ROOT)}")
    print(f"  generated_at : {payload.get('generated_at')}")
    print(f"  feed         : {payload.get('feed')}")
    print(f"  trusts       : {len(trusts)} ({priced} priced)")


if __name__ == "__main__":
    main()
