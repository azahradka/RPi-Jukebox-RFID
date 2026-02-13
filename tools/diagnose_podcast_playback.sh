#!/bin/bash
# Diagnostic script for podcast playback issues

echo "=== Podcast Player Diagnostic ==="
echo ""

echo "1. Checking jukebox service status..."
systemctl --user is-active jukebox-daemon
echo ""

echo "2. Checking MPD status..."
systemctl --user is-active mpd
echo ""

echo "3. Checking if podcast player module is loaded..."
./tools/run_rpc_tool.sh -c player_podcast.ctrl.get_player_type_and_version 2>&1
echo ""

echo "4. Checking card configuration..."
if [ -f "shared/settings/cards.yaml" ]; then
    echo "cards.yaml exists"
    grep -A 5 "podcast" shared/settings/cards.yaml | head -20
else
    echo "ERROR: cards.yaml not found!"
fi
echo ""

echo "5. Testing feed fetch..."
./tools/run_rpc_tool.sh -c player_podcast.ctrl.get_podcast_info "http://feeds.serialpodcast.org/serialpodcast" 2>&1 | head -20
echo ""

echo "6. Recent errors in logs..."
tail -30 shared/logs/errors.log
echo ""

echo "7. Recent podcast activity..."
grep -i "podcast\|RPC CALL: play" shared/logs/app.log | tail -30
echo ""
