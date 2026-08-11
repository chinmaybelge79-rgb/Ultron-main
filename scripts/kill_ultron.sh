#!/usr/bin/env bash
# scripts/kill_ultron.sh — instant disable, no confirmation, no delay.
# Touches the kill-switch sentinel and, if the launchd service is installed,
# unloads it so Ultron stays disabled across reboots.
set -euo pipefail

cd "$(dirname "$0")/.."

# Create data/ if missing and plant the sentinel.
mkdir -p data
touch data/DISABLED

# Unload the launchd service if it exists.
PLIST="$HOME/Library/LaunchAgents/com.ultron.agent.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    echo "Ultron service unloaded."
else
    echo "No launchd service found; sentinel only."
fi

echo "Ultron disabled. Run scripts/enable_ultron.sh to resume."
