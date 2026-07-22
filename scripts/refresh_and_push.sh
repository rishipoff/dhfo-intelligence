#!/usr/bin/env bash
#
# refresh_and_push.sh — regenerate the static dashboard snapshot and push it,
# but only when the underlying data actually changed.
#
# Interim refresh engine = this Mac (scheduled via a launchd agent every 10 min);
# the Mac mini takes over later. NOT run in CI: a datacenter IP gets blocked by
# Yahoo, so this must run on a residential machine.
#
# "Changed" ignores the volatile generated_at / refreshed_at timestamps — those
# move every run, so committing on them would spam the history and blow through
# GitHub Pages' ~10 builds/hour limit. We only commit when prices (hence yields /
# signals) actually moved.
#
# Never exits non-zero on a transient error, so the scheduler keeps ticking.

set -uo pipefail
export GIT_TERMINAL_PROMPT=0   # never hang waiting for credentials under launchd

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT" || exit 0

LOG="$ROOT/scripts/refresh.log"
PY="$ROOT/.venv/bin/python"
DATA="docs/data.json"

ts()  { TZ="Asia/Kolkata" date "+%d-%b-%Y %H:%M:%S IST"; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "=== refresh start ==="

if [ ! -x "$PY" ]; then
  log "venv python not found at $PY — skipping"
  exit 0
fi

# Keep the currently-committed snapshot so we can compare / revert timestamp-only churn.
PREV="$(mktemp)"
cp "$DATA" "$PREV" 2>/dev/null || : > "$PREV"

# 1) Regenerate the snapshot.
if ! "$PY" scripts/build_static.py >> "$LOG" 2>&1; then
  log "build_static.py failed (transient?) — keeping previous $DATA"
  rm -f "$PREV"; exit 0
fi

# 2) Validate the new file (parses + has trusts) before trusting it.
if ! "$PY" - "$DATA" <<'PYEOF' >> "$LOG" 2>&1
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d.get("trusts"), list) and d["trusts"], "no trusts in snapshot"
PYEOF
then
  log "new $DATA invalid — reverting"
  git checkout -- "$DATA" >> "$LOG" 2>&1 || :
  rm -f "$PREV"; exit 0
fi

# 3) Did anything change beyond the timestamps? exit 0 = same, 1 = changed.
if "$PY" - "$PREV" "$DATA" <<'PYEOF' 2>> "$LOG"
import json, sys
def norm(p):
    try: d = json.load(open(p))
    except Exception: return None
    d.pop("generated_at", None); d.pop("refreshed_at", None)
    return json.dumps(d, sort_keys=True)
sys.exit(0 if norm(sys.argv[1]) == norm(sys.argv[2]) else 1)
PYEOF
then
  log "no meaningful change (prices unchanged) — reverting timestamp churn, nothing to push"
  git checkout -- "$DATA" >> "$LOG" 2>&1 || :
  rm -f "$PREV"
  log "=== refresh end (no change) ==="
  exit 0
fi
rm -f "$PREV"

# 4) Data changed → commit just this file and push.
git add "$DATA" >> "$LOG" 2>&1
if git commit -m "data refresh $(ts)" >> "$LOG" 2>&1; then
  if git push origin HEAD >> "$LOG" 2>&1; then
    log "committed and pushed"
  else
    log "push failed (transient network/auth?) — commit stands, will retry next run"
  fi
else
  log "nothing to commit (unexpected)"
fi

log "=== refresh end ==="
exit 0
