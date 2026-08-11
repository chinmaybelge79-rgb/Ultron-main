#!/usr/bin/env bash
# scripts/enable_ultron.sh — clear the kill switch and reload the service.
set -euo pipefail

cd "$(dirname "$0")/.."

# Remove the kill-switch sentinel.
if [ -f data/DISABLED ]; then
    rm data/DISABLED
    echo "Kill switch released."
else
    echo "No kill switch sentinel present."
fi

# Reload the launchd service if installed.
PLIST="$HOME/Library/LaunchAgents/com.ultron.agent.plist"
if [ -f "$PLIST" ]; then
    launchctl load "$PLIST" 2>/dev/null || true
    echo "Ultron service reloaded."
else
    echo "Ultron is enabled. Install the service with scripts/bootstrap.sh when ready."
fi
