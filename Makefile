SHELL := /bin/bash
PYTHON ?= python3

# Always resolve paths from repo root (where this Makefile exists)
ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

FUNCTION ?= ocr_trigger
FUNCTIONS := ocr_trigger md_generator

FUNC_DIR := $(ROOT_DIR)/functions/$(FUNCTION)
VENV_DIR := $(FUNC_DIR)/.venv
PY := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip

RUFF ?= ruff

.PHONY: help
help:
	@echo "Usage:"
	@echo "  make install FUNCTION=ocr_trigger"
	@echo "  make test FUNCTION=md_generator"
	@echo "  make lint"
	@echo ""
	@echo "ROOT_DIR=$(ROOT_DIR)"
	@echo "FUNCTIONS=$(FUNCTIONS)"

.PHONY: guard-function
guard-function:
	@if [ ! -d "$(FUNC_DIR)" ]; then \
	  echo "ERROR: function dir not found: $(FUNC_DIR)"; \
	  echo "Hint: set FUNCTION=... (available: $(FUNCTIONS))"; \
	  exit 1; \
	fi

.PHONY: venv
venv: guard-function
	@test -d "$(VENV_DIR)" || $(PYTHON) -m venv "$(VENV_DIR)"
	@$(PIP) install -U pip >/dev/null

.PHONY: install
install: guard-function venv
	@echo "Installing runtime deps for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PIP)" install -r requirements.txt

.PHONY: install-dev
install-dev: guard-function venv
	@echo "Installing dev deps for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PIP)" install -r requirements-dev.txt

.PHONY: compile
compile: guard-function venv
	@echo "Compiling requirements for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PIP)" install -U pip pip-tools
	@cd "$(FUNC_DIR)" && "$(VENV_DIR)/bin/pip-compile" requirements.in -o requirements.txt

.PHONY: compile-dev
compile-dev: guard-function venv
	@echo "Compiling dev requirements for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PIP)" install -U pip pip-tools
	@cd "$(FUNC_DIR)" && "$(VENV_DIR)/bin/pip-compile" requirements-dev.in -o requirements-dev.txt

.PHONY: test
test: guard-function install-dev
	@echo "Running tests for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PY)" -m pytest -q

.PHONY: run
run: guard-function install
	@echo "Running local_runner for $(FUNCTION)..."
	@cd "$(FUNC_DIR)" && "$(PY)" local_runner.py

.PHONY: lint
lint:
	@cd "$(ROOT_DIR)" && $(RUFF) check .

.PHONY: format
format:
	@cd "$(ROOT_DIR)" && $(RUFF) format .

.PHONY: install-all
install-all:
	@set -e; \
	for f in $(FUNCTIONS); do \
	  echo "==> install $$f"; \
	  $(MAKE) -f "$(ROOT_DIR)/Makefile" install FUNCTION=$$f; \
	done

.PHONY: test-all
test-all:
	@set -e; \
	for f in $(FUNCTIONS); do \
	  echo "==> test $$f"; \
	  $(MAKE) -f "$(ROOT_DIR)/Makefile" test FUNCTION=$$f; \
	done
