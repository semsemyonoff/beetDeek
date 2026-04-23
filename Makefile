# Docker image name and tag
BEETDECK_IMAGE ?= semsemyonoff/beetdeck
BEETDECK_TAG ?= latest
# Target platforms for multi-arch build
BEETDECK_PLATFORMS ?= linux/amd64,linux/arm64

export BEETDECK_IMAGE BEETDECK_TAG BEETDECK_PLATFORMS

PYTHON ?= .venv/bin/python
PYTEST ?= .venv/bin/pytest
RUFF   ?= .venv/bin/ruff

.PHONY: build test lint fmt coverage

# Build multi-arch image and push to registry
build:
	./build.sh

# Run test suite
test:
	$(PYTEST)

# Run linter
lint:
	$(RUFF) check .

# Format code
fmt:
	$(RUFF) format .

# Run tests with coverage report
coverage:
	$(PYTEST) --cov=src --cov-report=term-missing
