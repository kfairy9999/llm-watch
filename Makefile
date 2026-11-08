PY ?= python3

.PHONY: install test test-py test-ui seed serve dev-ui build demo-static

install:
	$(PY) -m pip install -e ".[dev]"
	cd dashboard && npm install

test: test-py test-ui

test-py:
	$(PY) -m pytest

test-ui:
	cd dashboard && npm test

seed:
	$(PY) -m llmwatch seed --force

serve:
	$(PY) -m llmwatch serve --host 0.0.0.0 --port 8491

dev-ui:
	cd dashboard && npm run dev -- --host 0.0.0.0 --port 8492

build:
	cd dashboard && npm run build

demo-static:
	cd dashboard && npm run build:demo
