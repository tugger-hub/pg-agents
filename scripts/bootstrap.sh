#!/bin/bash
set -e

echo "--- Setting up Python virtual environment ---"

# Check if python3 is available
if ! command -v python3 &> /dev/null
then
    echo "python3 could not be found. Please install Python 3.11+."
    exit 1
fi

# Create virtual environment in the parent directory
python3 -m venv ../venv

echo "--- Activating virtual environment ---"
source ../venv/bin/activate

echo "--- Installing dependencies from requirements.txt ---"
pip install -r ../requirements.txt

echo "--- Bootstrap complete! ---"
echo "To activate the environment, run: source venv/bin/activate"
