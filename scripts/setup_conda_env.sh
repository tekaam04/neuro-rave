#!/usr/bin/env bash
# Run from any directory: bash scripts/setup_conda_env.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found in PATH."
  echo "Install Miniconda for macOS: https://docs.conda.io/en/latest/miniconda.html"
  echo "Then open a new terminal and run this script again."
  exit 1
fi

conda create -n neuro-rave python=3.11 -y
conda run -n neuro-rave pip install --upgrade pip
conda run -n neuro-rave pip install -r requirements.txt

echo ""
echo "Done. Use this environment with:"
echo "  conda activate neuro-rave"
echo "  cd \"$ROOT\""
echo "  EEG_SIM=1 python main.py"
