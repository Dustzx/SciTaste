.PHONY: install install-substrate format lint test check demo clean

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

install:
	$(PIP) install -e '.[dev]'

install-substrate:
	git submodule update --init third_party/autoresearchclaw
	$(PIP) install -e third_party/autoresearchclaw

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

test:
	$(PYTHON) -m pytest

check: lint test

demo:
	$(PYTHON) -m scitaste run demo --output outputs/demo --seed 7

clean:
	find . -type d -name __pycache__ -prune -exec rm -r {} +
	find . -type d -name .pytest_cache -prune -exec rm -r {} +
	find . -type d -name .ruff_cache -prune -exec rm -r {} +
