SHELL := /bin/bash
.ONESHELL:

VENV := .venv
PYTHON ?= python3
PY := $(VENV)/bin/python

.PHONY: venv
venv:
	@if [ ! -x "$(PY)" ]; then \
		rm -rf $(VENV); \
		$(PYTHON) -m venv $(VENV); \
	fi
	@$(PY) -m pip install -U pip

.PHONY: install
install: venv
	@$(PY) -m pip install -r requirements.txt
	@$(PY) -m pip install -r requirements-dev.txt

.PHONY: run
run: venv
	@echo "Running local_runner for md_generator..."
	@$(PY) local_runner.py

.PHONY: test
test: venv
	@$(PY) -m pytest -q

.PHONY: lint
lint: venv
	@$(VENV)/bin/ruff check .
