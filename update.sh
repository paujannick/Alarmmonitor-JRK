#!/bin/bash
set -e

git pull --ff-only

if [ -d "venv" ]; then
  source venv/bin/activate
  pip install --upgrade -r requirements.txt
else
  echo "Virtual environment not found. Run ./install.sh first."
fi
