# Thin wrapper Makefile for ocr_trigger (path-robust)
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: install install-dev compile compile-dev test run

install:
	$(MAKE) -f $(ROOT)/Makefile install FUNCTION=ocr_trigger

install-dev:
	$(MAKE) -f $(ROOT)/Makefile install-dev FUNCTION=ocr_trigger

compile:
	$(MAKE) -f $(ROOT)/Makefile compile FUNCTION=ocr_trigger

compile-dev:
	$(MAKE) -f $(ROOT)/Makefile compile-dev FUNCTION=ocr_trigger

test:
	$(MAKE) -f $(ROOT)/Makefile test FUNCTION=ocr_trigger

run:
	$(MAKE) -f $(ROOT)/Makefile run FUNCTION=ocr_trigger
