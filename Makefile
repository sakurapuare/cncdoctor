PYTHON ?= python3
VENV ?= .venv
VPY = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
RUFF = $(VENV)/bin/ruff
PRE_COMMIT = $(VENV)/bin/pre-commit

.PHONY: setup lint format test check run rebuild-db doctor hooks

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements/dev.txt

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

test:
	$(VPY) -m unittest discover -s tests

check:
	$(RUFF) check .
	$(VPY) manage.py check
	$(VPY) -m unittest discover -s tests

run:
	$(VPY) manage.py runserver 0.0.0.0:8000

rebuild-db:
	$(VPY) manage.py rebuild_case_db

doctor:
	$(VPY) manage.py system_doctor

hooks:
	$(PRE_COMMIT) install
