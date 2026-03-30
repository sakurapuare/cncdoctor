PYTHON ?= python3
VENV ?= .venv
VPY = $(VENV)/bin/python
PIP = $(VENV)/bin/pip

.PHONY: setup test check run rebuild-db doctor

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirement.txt

test:
	$(VPY) -m unittest discover -s tests

check:
	$(VPY) manage.py check

run:
	$(VPY) manage.py runserver 0.0.0.0:8000

rebuild-db:
	$(VPY) manage.py rebuild_case_db

doctor:
	$(VPY) manage.py system_doctor
