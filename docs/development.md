# Development

## Environment

Recommended Python versions:

- 3.9
- 3.11

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
```

## Commands

```bash
make setup
make lint
make test
make check
make run
make rebuild-db
make doctor
```

## Pre-commit

```bash
pre-commit install
pre-commit run --all-files
```

## Test strategy

- Unit tests live under `tests/`
- Django system validation runs through `manage.py check`
- CI runs lint plus tests on multiple Python versions

## Repository conventions

- Keep transport concerns in `api_views.py`
- Keep business logic in `core/services.py`
- Keep persistence logic in `core/repositories.py`
- Prefer environment variables over hardcoded runtime values
