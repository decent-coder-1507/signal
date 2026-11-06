# Thin wrapper over scripts/dev.py (ADR-003) so the spec's `make up/test/seed/mock` work on Linux/WSL.
PY ?= python3
.PHONY: setup infra up mock migrate seed test lint e2e check backup restore
setup infra up mock migrate test lint e2e check backup:
	$(PY) scripts/dev.py $@
seed:
	$(PY) scripts/dev.py seed --demo
restore:
	$(PY) scripts/dev.py restore $(FILE)
