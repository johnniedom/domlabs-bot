#!/usr/bin/env bash
# Install domlabs-bot via pipx with clean output (no pipx emojis).
#
# Usage:
#   ./setup.sh              # install only
#   ./setup.sh --init       # install, then run `domlabs-bot init`
#
# Source path defaults to the directory this script lives in, so running it
# from a fresh git clone just works.

set -euo pipefail

DO_INIT=0
SRC_PATH="$(cd "$(dirname "$0")" && pwd)"

for arg in "$@"; do
  case "$arg" in
    --init|-i) DO_INIT=1 ;;
    --path=*)  SRC_PATH="${arg#--path=}" ;;
    -h|--help)
      grep -E "^# " "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

bar() { printf '%*s\n' 60 '' | tr ' ' '─'; }
banner() { echo; bar; echo "  $1"; bar; echo; }
step() { echo "  $1"; }

# --- 1. Ensure pipx is available --------------------------------------

if ! command -v pipx >/dev/null 2>&1; then
  banner "pipx not found — installing it first"
  step "python3 -m pip install --user pipx"
  python3 -m pip install --user pipx >/dev/null
  step "python3 -m pipx ensurepath"
  python3 -m pipx ensurepath >/dev/null
  echo
  echo "  pipx is installed. If 'domlabs-bot' doesn't resolve after this"
  echo "  script finishes, open a new shell and try again."
  echo
  PIPX="python3 -m pipx"
else
  PIPX="pipx"
fi

# --- 2. Install via pipx, filter pipx's emoji line out ----------------

banner "Installing domlabs-bot from ${SRC_PATH}"

# Stream pipx's combined stdout/stderr through a filter that drops the
# `done! ✨ 🌟 ✨` celebration line. The emojis live on that single line, so
# killing it removes them all.
set +e
$PIPX install -e "$SRC_PATH" --force 2>&1 | \
  awk '/^[[:space:]]*done!/ { next } { print "  " $0 }'
exit_code=${PIPESTATUS[0]}
set -e

if [ "$exit_code" -ne 0 ]; then
  echo
  echo "  Install failed (exit code ${exit_code})."
  exit "$exit_code"
fi

# --- 3. Clean completion banner ---------------------------------------

banner "domlabs-bot installed."

if [ "$DO_INIT" -eq 1 ]; then
  exec domlabs-bot init
else
  echo "  Next:  domlabs-bot init"
  echo "         (or ./setup.sh --init to chain straight into setup)"
  echo
fi
