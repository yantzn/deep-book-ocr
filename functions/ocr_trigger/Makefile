# Makefile for ocr_trigger function

.PHONY: help install sync test lint format clean

# Variables
PYTHON = python3
VENV_DIR = .venv
PIP = $(VENV_DIR)/bin/pip
PYTEST = $(VENV_DIR)/bin/pytest
PIP_COMPILE = $(VENV_DIR)/bin/pip-compile
RUFF = $(VENV_DIR)/bin/ruff

help:
	@echo "Makefile for ocr_trigger function"
	@echo ""
	@echo "Usage:"
	@echo "  make install    - Create a virtual environment and install dependencies"
	@echo "  make sync       - Sync dependencies from requirements.txt"
	@echo "  make compile    - Compile requirements.in to requirements.txt"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Lint the code"
	@echo "  make format     - Format the code"
	@echo "  make clean      - Remove virtual environment and temporary files"
	@echo ""

install: $(VENV_DIR)/bin/activate

$(VENV_DIR)/bin/activate: requirements.txt
	test -d $(VVENV_DIR) || $(PYTHON) -m venv $(VENV_DIR)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "Virtual environment created and dependencies installed."

sync:
	$(PIP) install -r requirements.txt
	@echo "Dependencies synced."

compile:
	@echo "Compiling requirements.in to requirements.txt..."
	$(PIP_COMPILE) requirements.in -o requirements.txt --upgrade
	@echo "Done."

test:
	@echo "Running tests..."
	$(PYTEST) tests/
	@echo "Done."

lint:
	@echo "Linting code..."
	$(RUFF) check src/ tests/
	@echo "Done."

format:
	@echo "Formatting code..."
	$(RUFF) format src/ tests/
	@echo "Done."

clean:
	@echo "Cleaning up..."
	rm -rf $(VENV_DIR)
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	@echo "Done."

