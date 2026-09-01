VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: setup pipeline test demo dev clean

setup:
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	@echo "listo. siguiente: make pipeline"

pipeline:
	$(PY) pipeline/ingesta.py
	$(PY) pipeline/features.py
	$(PY) analytics/entrenar.py
	@echo "artefactos en pipeline/artifacts/"

test:
	$(VENV)/bin/pytest -q analytics/tests pipeline/tests

demo:
	$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

dev:
	$(VENV)/bin/uvicorn app.main:app --reload --port 8000

clean:
	rm -rf $(VENV) __pycache__ .pytest_cache
