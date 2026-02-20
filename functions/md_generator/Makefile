# Thin wrapper Makefile for md_generator (path-robust)
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)

.PHONY: install install-dev compile compile-dev test run

install:
	$(MAKE) -f $(ROOT)/Makefile install FUNCTION=md_generator

install-dev:
	$(MAKE) -f $(ROOT)/Makefile install-dev FUNCTION=md_generator

compile:
	$(MAKE) -f $(ROOT)/Makefile compile FUNCTION=md_generator

compile-dev:
	$(MAKE) -f $(ROOT)/Makefile compile-dev FUNCTION=md_generator

test:
	$(MAKE) -f $(ROOT)/Makefile test FUNCTION=md_generator

run:
	$(MAKE) -f $(ROOT)/Makefile run FUNCTION=md_generator
