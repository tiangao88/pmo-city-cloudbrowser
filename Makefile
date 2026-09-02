.PHONY: check test unit contract security install-check spec-check sensitive-check image-workflow-check

PYTHON ?= uv run python

check: spec-check sensitive-check install-check image-workflow-check test

test:
	$(PYTHON) -m pytest -q tests

unit:
	$(PYTHON) -m pytest -q tests/unit

contract:
	$(PYTHON) -m pytest -q tests/contract

security:
	$(PYTHON) -m pytest -q tests/security

install-check:
	$(PYTHON) tools/validate-release-manifest.py
	$(PYTHON) tools/validate-installation.py
	$(PYTHON) tools/validate-image-inputs.py

spec-check:
	$(PYTHON) tools/validate-specs.py

sensitive-check:
	$(PYTHON) tools/check-sensitive-files.py

image-workflow-check:
	$(PYTHON) tools/validate-image-workflow.py
