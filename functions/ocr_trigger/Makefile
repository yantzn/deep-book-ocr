SHELL := /bin/bash
.ONESHELL:

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: venv
venv:
	@test -d $(VENV) || python -m venv $(VENV)
	@$(PIP) install -U pip

.PHONY: install
install: venv
	@$(PIP) install -r requirements.txt
	@$(PIP) install -r requirements-dev.txt

.PHONY: run
run: venv
	@echo "Running local_runner for ocr_trigger..."
	@$(PY) local_runner.py

.PHONY: test
test: venv
	@$(PY) -m pytest -q

.PHONY: lint
lint: venv
	@$(VENV)/bin/ruff check .
