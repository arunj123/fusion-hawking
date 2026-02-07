#!/bin/bash
set -e

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found."
    exit 1
fi

# Create Venv
if [ ! -d ".venv_linux" ]; then
    echo "Creating Python Virtual Environment..."
    python3 -m venv .venv_linux
fi

# Activate
source .venv_linux/bin/activate

# Install Deps
if ! pip show pytest &> /dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Run Fusion
echo "Starting Fusion Automation..."
export PYTHONPATH=$(pwd)
python3 -m tools.fusion.main "$@"
