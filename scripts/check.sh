#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
ruff check .
python -m unittest discover -s tests
python manage.py check
