#!/usr/bin/env bash
# tools/run_local_smoke.sh — Phase 7 local smoke harness.
#
# Runs a small set of in-process scenarios that exercise the real
# production decision seams (decide_swipe, decide_second_swipe,
# PlayerCoordinator handoff, paths cache-reset). No MPD, no PulseAudio,
# no network, no RPi round-trip required. Designed to finish in
# single-digit seconds so it can run on every change.
#
# Exits 0 on full pass, non-zero on the first failure with a clear
# diff on stderr. stdout is reserved (currently unused) so the script
# is pipe-safe.
#
# Usage:
#   tools/run_local_smoke.sh

set -euo pipefail

SOURCE=${BASH_SOURCE[0]}
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT" || { echo "Could not change directory" >&2; exit 1; }

# venv activation is best-effort: if .venv exists, use it; otherwise
# rely on the ambient python (smoke harness imports the real source
# tree, not installed packages, so plain python3 is acceptable).
if [[ -f .venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate || {
        echo "WARN: .venv exists but activation failed; using system python" >&2
    }
fi

exec python3 tools/run_local_smoke.py "$@"
