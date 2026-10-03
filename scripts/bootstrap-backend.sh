#!/usr/bin/env bash
#
# Create the backend virtual environment and install runtime + dev dependencies.
#
# Usage:
#   ./scripts/bootstrap-backend.sh
#   PYTHON_BIN=/path/to/python3.12 ./scripts/bootstrap-backend.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
VENV_DIR="${BACKEND_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "error: '${PYTHON_BIN}' was not found on PATH." >&2
  echo "       Install CPython 3.12 (for example: brew install python@3.12)" >&2
  echo "       or set PYTHON_BIN to a Python 3.12 executable." >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "==> Creating virtual environment at backend/.venv"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

echo "==> Upgrading pip"
"${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip

echo "==> Installing backend (editable) with dev extras"
"${VENV_DIR}/bin/python" -m pip install --quiet -e "${BACKEND_DIR}[dev]"

echo
echo "Backend environment ready."
echo "  Activate:  source backend/.venv/bin/activate"
echo "  Run API:   cd backend && python -m app"
echo "  Run tests: cd backend && python -m pytest"
