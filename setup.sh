#!/usr/bin/env bash
# exaone-skill installer (Linux / macOS / Git Bash)
# Usage: ./setup.sh [--skip-key] [--effort low|medium|high|max]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MARKET="exaone-skill-local"
PLUGIN="exaone-skill@$MARKET"
SKIP_KEY=0; EFFORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-key) SKIP_KEY=1 ;;
    --effort) EFFORT="${2:-}"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done

PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info[0]==3 else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && { echo "[ERROR] Python 3 not found"; exit 1; }
echo "[OK] python: $PY"

# Windows paths for claude when running under Git Bash
ROOT_ARG="$ROOT"
command -v cygpath >/dev/null 2>&1 && ROOT_ARG="$(cygpath -w "$ROOT")"

if command -v claude >/dev/null 2>&1; then
  if claude plugin marketplace list 2>&1 | awk -v m="$MARKET" 'index($0,m){f=1} END{exit !f}'; then
    echo "[..] marketplace exists; updating"
    claude plugin marketplace update "$MARKET" || { echo "[ERROR] marketplace update failed"; exit 1; }
  else
    echo "[..] adding marketplace $ROOT_ARG"
    claude plugin marketplace add "$ROOT_ARG" || { echo "[ERROR] marketplace add failed"; exit 1; }
  fi
  echo "[..] installing $PLUGIN"
  if ! claude plugin install "$PLUGIN"; then
    echo "[..] install failed; trying update (already installed?)"
    claude plugin update "$PLUGIN" || { echo "[ERROR] plugin install/update failed"; exit 1; }
  fi
  echo "[OK] plugin installed. Restart Claude Code to load it."
else
  echo "[WARN] 'claude' CLI not on PATH. Install manually inside Claude Code:"
  echo "  /plugin marketplace add $ROOT_ARG"
  echo "  /plugin install $PLUGIN"
fi

SETUP_PY="$ROOT/scripts/setup.py"
if [ -n "$EFFORT" ]; then "$PY" "$SETUP_PY" --set-effort "$EFFORT" || exit 1; fi

if [ "$SKIP_KEY" -eq 0 ]; then
  if "$PY" "$SETUP_PY" --show >/dev/null 2>&1; then
    echo "[OK] API key already registered (\"$PY\" scripts/setup.py --key --prompt to replace)"
  elif [ -t 0 ]; then
    "$PY" "$SETUP_PY" --key --prompt || { echo "[ERROR] key not stored"; exit 1; }
  else
    echo "[WARN] non-interactive shell; register the key later:"
    echo "  $PY \"$SETUP_PY\" --key --prompt"
  fi
fi
"$PY" "$SETUP_PY" --show
exit 0
