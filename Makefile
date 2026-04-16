PYTHON ?= python3.12
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python

.PHONY: install proof clean

install:
	$(PY) -m pip install -r requirements.txt

proof:
	$(PY) e91_qkd_proof.py --repetitions 3 --shots 2048 --output results/e91_proof_hardware.json

clean:
	rm -rf results/*.json
