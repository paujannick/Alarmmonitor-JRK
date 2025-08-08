#!/bin/bash
set -e
if [ ! -d "venv" ]; then
  echo "Virtual environment not found. Run scripts/install.sh first."
  exit 1
fi
source venv/bin/activate
uvicorn app.main:app --host=0.0.0.0 --port=8080
