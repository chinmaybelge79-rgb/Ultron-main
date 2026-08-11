# Ultron developer convenience targets.
PYTHON := .venv/bin/python

.PHONY: setup test lint run help

setup:
	./setup.sh

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

run:
	$(PYTHON) -m ultron

help:
	@echo "make setup  — create venv, install deps, install ultron command"
	@echo "make test   — run the pytest suite"
	@echo "make lint   — run ruff"
	@echo "make run    — launch Ultron"
