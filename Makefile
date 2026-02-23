SHELL := /bin/bash
.ONESHELL:

# repo root（このMakefileがある場所）
ROOT_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
FUNCTION ?= ocr_trigger

FUNCTION_DIR := $(ROOT_DIR)/functions/$(FUNCTION)

.PHONY: help
help:
	@echo "Targets:"
	@echo "  make install FUNCTION=ocr_trigger|md_generator"
	@echo "  make run     FUNCTION=ocr_trigger|md_generator"
	@echo "  make test    FUNCTION=ocr_trigger|md_generator"
	@echo "  make lint    FUNCTION=ocr_trigger|md_generator"

.PHONY: guard-function
guard-function:
	@if [ ! -d "$(FUNCTION_DIR)" ]; then \
	  echo "ERROR: function dir not found: functions/$(FUNCTION)"; \
	  echo "Hint: set FUNCTION=... (available: ocr_trigger md_generator)"; \
	  exit 1; \
	fi

.PHONY: install
install: guard-function
	@echo "Installing deps for $(FUNCTION)..."
	@cd "$(FUNCTION_DIR)" && make install

.PHONY: run
run: guard-function
	@cd "$(FUNCTION_DIR)" && make run

.PHONY: test
test: guard-function
	@cd "$(FUNCTION_DIR)" && make test

.PHONY: lint
lint: guard-function
	@cd "$(FUNCTION_DIR)" && make lint
