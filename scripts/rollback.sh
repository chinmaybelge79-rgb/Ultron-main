#!/usr/bin/env bash
# scripts/rollback.sh — stop the daemon, reset to a known-good git commit,
# restart. Because Day 6 commits before every self-edit, rollback is never
# more than "pick a known-good SHA".
set -euo pipefail

cd "$(dirname "$0")/.."
PLIST="$HOME/Library/LaunchAgents/com.ultron.agent.plist"

launchctl unload "$PLIST" 2>/dev/null || true

git log --oneline -20
read -r -p "Rollback to commit: " sha
git reset --hard "$sha"

launchctl load "$PLIST"
echo "Rolled back to $sha and restarted."
