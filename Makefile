.PHONY: check test unit contract security install-check spec-check sensitive-check image-workflow-check cloudfiles-boundary

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

# Phase 0 RED boundary suite for the public CloudFiles gateway.
# These tests are intentionally failing in Phase 0 and must become green by
# Phase 3 (gateway). See:
#   specs/proposals/v0.2/92-cloudfiles-route-response-matrix.md
#   specs/proposals/v0.2/93-cloudfiles-phase0-red-tests.md
#   specs/proposals/v0.2/94-cloudfiles-threat-model.md
cloudfiles-boundary:
	$(PYTHON) -m pytest -q \
	  tests/contract/test_cloudfiles_v1_gateway_boundary.py \
	  tests/security/test_cloudfiles_v1_gateway_security.py \
	  tests/security/test_cloudfiles_gateway_exposure.py
