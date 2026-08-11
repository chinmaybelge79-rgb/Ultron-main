#!/usr/bin/env bash
# scripts/bootstrap.sh — first-run bootstrap, run once by hand before the
# daemon ever starts unattended. Idempotent: safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "[1/6] Checking Ollama..."
command -v ollama >/dev/null || {
    echo "Install Ollama first: https://ollama.com"; exit 1
}

# Honor models configured in .env (ULTRON_OLLAMA_MODEL / _CODE_MODEL);
# fall back to the roadmap defaults when unset.
general_model="$(grep -E '^ULTRON_OLLAMA_MODEL=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
code_model="$(grep -E '^ULTRON_OLLAMA_CODE_MODEL=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)"
: "${general_model:=llama3.1:8b}"
: "${code_model:=qwen2.5-coder:7b}"

ollama list | grep -qF "$general_model" || ollama pull "$general_model"
ollama list | grep -qF "$code_model" || ollama pull "$code_model"

echo "[2/6] Creating venv + installing..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .

echo "[3/6] Migrating secrets to Keychain (if any exist in .env)..."
./scripts/migrate_secrets_to_keychain.sh --dry-run

echo "[4/6] Requesting macOS permissions (Microphone, Accessibility)..."
.venv/bin/python -m ultron.diagnostics --request-permissions || true

echo "[5/6] Running full test suite before going live..."
.venv/bin/python -m pytest -q

echo "[6/6] Installing launchd service..."
mkdir -p logs
sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    packaging/com.ultron.agent.plist > "$HOME/Library/LaunchAgents/com.ultron.agent.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.ultron.agent.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.ultron.agent.plist"

echo "Ultron is now running headlessly. Check: launchctl list | grep ultron"
echo "Disable any time with: scripts/kill_ultron.sh"
