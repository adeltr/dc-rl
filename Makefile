PYTHON ?= python3.11
VENV := .venv
PY := $(VENV)/bin/python
VENDOR_DIR := vendor/sustaindc
VENDOR_URL := https://github.com/HewlettPackard/dc-rl
VENDOR_COMMIT := a92b475

.PHONY: setup vendor test bench bridge api

setup: vendor $(VENV)/.installed

$(VENV)/.installed: requirements-twin.txt
	uv venv -q $(VENV) --python 3.11 || $(PYTHON) -m venv $(VENV)
	uv pip install -q --python $(PY) -r requirements-twin.txt || $(PY) -m pip install -q -r requirements-twin.txt
	touch $@

vendor:
	@test -d $(VENDOR_DIR)/.git || git clone -q $(VENDOR_URL) $(VENDOR_DIR)
	git -C $(VENDOR_DIR) checkout -q $(VENDOR_COMMIT)

test: setup
	$(PY) -m pytest -q

bench: setup
	$(PY) scripts/bench_engine.py

bridge: setup
	$(PY) -m bridge.build model/Data-Center-Development-Model-v1.7.xlsm build/twin_model.xlsm

api: setup
	$(VENV)/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
