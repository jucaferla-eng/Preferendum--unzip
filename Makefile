# Preferendum — tareas de desarrollo.
# Todo corre en un entorno aislado; nada toca producción.

VENV := .venv-test
PY   := $(VENV)/bin/python

.PHONY: help setup test test-python test-js audit dr-drill vote-drill clean

help:
	@echo "make setup        instala el entorno de pruebas fijado (.venv-test)"
	@echo "make test         ejecuta TODA la suite (Python + JS)"
	@echo "make test-python  solo las suites Python"
	@echo "make test-js      solo las suites JS"
	@echo "make audit        inventario de rutas, pruebas y señales de trabajo pendiente"
	@echo "make vote-drill   ensayo de concurrencia del voto contra PostgreSQL real"
	@echo "                  (doble voto simultáneo, reintentos, fallos transaccionales)"
	@echo "make dr-drill     ensayo de recuperación ante desastre (respaldo + restauración"
	@echo "                  real contra PostgreSQL, con verificación de integridad)"
	@echo "                  volumen: PREFY_DR_VOTES=50000 make dr-drill"
	@echo "make clean        elimina el entorno de pruebas"

setup:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r requirements-dev.txt
	$(VENV)/bin/pip install -q "pydantic==1.10.13"
	@echo "entorno listo en $(VENV)"

test:
	@tools/run_all_tests.sh

test-python:
	@tools/run_all_tests.sh --python

test-js:
	@tools/run_all_tests.sh --js

audit:
	@PYTHONNOUSERSITE=1 python3 tools/audit_inventory.py

# No toca ninguna base existente: crea su propia instancia temporal de
# PostgreSQL, la destruye a propósito y comprueba que los datos vuelven.
dr-drill:
	@tools/verify_backup_restore.sh

# La concurrencia del voto NO se puede probar en SQLite (serializa las
# escrituras con un candado de fichero), así que esta suite va aparte de
# `make test` y levanta su propio PostgreSQL temporal.
vote-drill:
	@tools/verify_vote_concurrency.sh

clean:
	rm -rf $(VENV)
