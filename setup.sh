#!/usr/bin/env bash
# Ultron setup script — creates the venv, installs dependencies, and
# verifies the install. Idempotent: safe to run repeatedly.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
PYTHON="${VENV}/bin/python"

echo "==> Ultron setup"

if [ ! -d "${VENV}" ]; then
    echo "==> Creating virtual environment..."
    python3 -m venv "${VENV}"
else
    echo "==> Virtual environment already exists."
fi

echo "==> Upgrading pip..."
"${PYTHON}" -m pip install --upgrade pip -q

echo "==> Installing runtime dependencies..."
"${PYTHON}" -m pip install -r requirements.txt -q

echo "==> Installing development dependencies..."
"${PYTHON}" -m pip install -r requirements-dev.txt -q

echo "==> Installing Ultron as a command..."
"${PYTHON}" -m pip install -e . -q

if [ ! -f .env ]; then
    cp .env.example .env
    echo "==> Created .env from .env.example — add your API keys there."
else
    echo "==> .env already present."
fi

echo ""
echo "==> Setup complete."
echo "    Run the assistant:   ${VENV}/bin/ultron"
echo "    Run the tests:       ${VENV}/bin/python -m pytest -q"
echo "    Run the linter:      ${VENV}/bin/python -m ruff check ."
