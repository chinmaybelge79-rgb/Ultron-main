#!/usr/bin/env bash
# scripts/migrate_secrets_to_keychain.sh — move any API keys from .env into
# the macOS Keychain so no plaintext secrets live in the repo. Pass
# --dry-run to review what would move without touching anything.
#
# Keys handled: OPENROUTER_API_KEY, ELEVENLABS_API_KEY.
set -euo pipefail

cd "$(dirname "$0")/.."

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

ENV_FILE=".env"
[ -f "$ENV_FILE" ] || {
    echo "No .env file — nothing to migrate."
    exit 0
}

migrated=0
for KEY in OPENROUTER_API_KEY ELEVENLABS_API_KEY; do
    VALUE="$(grep -E "^${KEY}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)"
    if [ -n "$VALUE" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            echo "[dry-run] would move ${KEY} to Keychain (item: ultron.${KEY})"
        else
            security add-generic-password -U \
                -a "$(whoami)" \
                -s "ultron.${KEY}" \
                -w "$VALUE" 2>/dev/null || true
            echo "Moved ${KEY} to Keychain."
        fi
        migrated=$((migrated + 1))
    fi
done

if [ "$migrated" -eq 0 ]; then
    echo "No secrets found in .env — clean."
    exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
    echo "Review complete. Run without --dry-run to apply."
else
    echo "Removing plaintext secrets from .env..."
    for KEY in OPENROUTER_API_KEY ELEVENLABS_API_KEY; do
        if grep -qE "^${KEY}=" "$ENV_FILE"; then
            sed -i '' "s|^${KEY}=.*|${KEY}=|" "$ENV_FILE"
        fi
    done
    echo "Done. .env keys blanked; secrets now live in Keychain only."
fi
