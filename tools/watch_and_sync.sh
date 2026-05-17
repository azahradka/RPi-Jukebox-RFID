#!/usr/bin/env bash
# tools/watch_and_sync.sh - auto-rsync src/jukebox/ to the RPi on file change.
#
# Phase 7 (Dev workflow). Shortens the local → RPi inner loop from
# "save → manual rsync → manual restart" to "save → sync (→ restart)".
#
# Usage:
#   tools/watch_and_sync.sh                       # sync on every change
#   tools/watch_and_sync.sh --restart             # also restart jukebox-daemon
#   tools/watch_and_sync.sh --host pi@10.0.0.46   # override ssh target
#   tools/watch_and_sync.sh --key ~/.ssh/foo.pub  # override ssh key
#   tools/watch_and_sync.sh --once                # one-shot rsync, no watch
#
# Defaults (matching CLAUDE.md "Remote Raspberry Pi Test Box"):
#   ssh target: boxadmin@phoniebox.local
#   ssh key:    ~/.ssh/Phoniebox.pub
#   remote path: /home/boxadmin/RPi-Jukebox-RFID/src/jukebox/
#
# Requires: fswatch (macOS: brew install fswatch; Linux: apt install fswatch)
# Falls back to a 2s polling loop if fswatch is missing — slower but works.
#
# All progress logs go to stderr; stdout stays clean for piping.

set -euo pipefail

SOURCE=${BASH_SOURCE[0]}
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC_DIR="$PROJECT_ROOT/src/jukebox/"
SSH_HOST="boxadmin@phoniebox.local"
SSH_KEY="$HOME/.ssh/Phoniebox.pub"
REMOTE_BASE="/home/boxadmin/RPi-Jukebox-RFID/src/jukebox/"
RESTART=0
ONCE=0
DEBOUNCE_MS=500

usage() {
    sed -n '1,/^set -euo/p' "$SOURCE" | sed '$d' | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --restart) RESTART=1; shift ;;
        --once) ONCE=1; shift ;;
        --host) SSH_HOST="$2"; shift 2 ;;
        --key) SSH_KEY="$2"; shift 2 ;;
        --debounce) DEBOUNCE_MS="$2"; shift 2 ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown arg: $1" >&2; usage 1 ;;
    esac
done

log() {
    echo "[watch_and_sync] $*" >&2
}

ssh_cmd() {
    if [[ -f "$SSH_KEY" ]]; then
        ssh -i "$SSH_KEY" -o ConnectTimeout=5 "$SSH_HOST" "$@"
    else
        ssh -o ConnectTimeout=5 "$SSH_HOST" "$@"
    fi
}

rsync_cmd() {
    local ssh_opts=""
    if [[ -f "$SSH_KEY" ]]; then
        ssh_opts="-e ssh\ -i\ $SSH_KEY"
    fi
    # shellcheck disable=SC2086
    rsync -az --delete --exclude '__pycache__' --exclude '*.pyc' \
        ${ssh_opts:+-e "ssh -i $SSH_KEY"} \
        "$SRC_DIR" "$SSH_HOST:$REMOTE_BASE"
}

do_sync() {
    local start
    start=$(date +%s)
    log "syncing $SRC_DIR -> $SSH_HOST:$REMOTE_BASE"
    if rsync_cmd; then
        log "synced in $(($(date +%s) - start))s"
    else
        log "rsync FAILED (continuing)"
        return 1
    fi
    if [[ $RESTART -eq 1 ]]; then
        log "restarting jukebox-daemon on $SSH_HOST"
        if ssh_cmd "systemctl --user restart jukebox-daemon"; then
            log "restart OK"
        else
            log "restart FAILED (continuing)"
        fi
    fi
}

# Initial sync so subsequent runs are incremental
do_sync || true

if [[ $ONCE -eq 1 ]]; then
    exit 0
fi

# Debounce loop: collect change bursts and sync once.
debounce_and_sync() {
    # Drain any further events within DEBOUNCE_MS, then sync.
    local sleep_secs
    sleep_secs=$(awk "BEGIN { print $DEBOUNCE_MS / 1000 }")
    sleep "$sleep_secs"
    do_sync || true
}

if command -v fswatch >/dev/null 2>&1; then
    log "watching $SRC_DIR via fswatch (debounce=${DEBOUNCE_MS}ms, restart=$RESTART)"
    # -o: collapse events into a single line per batch
    # --exclude pycache to avoid noise
    fswatch -o --exclude '__pycache__' --exclude '\.pyc$' "$SRC_DIR" | \
    while read -r _; do
        debounce_and_sync
    done
else
    log "fswatch not found; falling back to 2s polling"
    log "  (brew install fswatch  /  apt install fswatch  for better latency)"
    LAST_HASH=""
    while true; do
        # Hash mtimes of .py files; cheap-enough fallback.
        CUR_HASH=$(find "$SRC_DIR" -name '*.py' -type f -exec stat -f '%m %N' {} \; 2>/dev/null \
                   | sort | shasum | awk '{print $1}')
        if [[ "$CUR_HASH" != "$LAST_HASH" && -n "$LAST_HASH" ]]; then
            do_sync || true
        fi
        LAST_HASH="$CUR_HASH"
        sleep 2
    done
fi
