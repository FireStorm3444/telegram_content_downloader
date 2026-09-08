.PHONY: all install sync run format lint typecheck check clean doctor test

PYTHON ?= python3
VENV ?= .venv
BIN = $(VENV)/bin
UV ?= uv
RUFF ?= ruff
TY ?= ty

all: check

# Rapid onboarding and environment synchronization
install: sync

sync:
	@echo "==> Ensuring virtual environment with $(UV)..."
	@if [ ! -d "$(VENV)" ]; then $(UV) venv --python 3.12 $(VENV); fi
	@echo "==> Installing dependencies in editable mode..."
	@$(UV) pip install --python $(BIN)/python -e ".[dev]"
	@echo "==> Environment ready!"

# Running the CLI application with arbitrary arguments (e.g. make run ARGS="--help")
run:
	@if [ ! -f "$(BIN)/tg-downloader" ]; then $(MAKE) sync; fi
	@$(BIN)/tg-downloader $(ARGS)

# Code formatting via ruff
format:
	@echo "==> Formatting code with ruff..."
	@$(RUFF) format .

# Linting and auto-fixing via ruff
lint:
	@echo "==> Linting and auto-fixing code with ruff..."
	@$(RUFF) check --fix .

# Static type checking via ty
typecheck:
	@echo "==> Static type checking with ty..."
	@$(TY) check

# Composite check target: format check, lint check, type check
check:
	@echo "==> Running format check..."
	@$(RUFF) format --check .
	@echo "==> Running lint check..."
	@$(RUFF) check .
	@echo "==> Running static type checking..."
	@$(TY) check
	@echo "==> All checks passed cleanly!"

# Run test suite
test:
	@if [ ! -f "$(BIN)/pytest" ]; then $(MAKE) sync; fi
	@echo "==> Running pytest test suite..."
	@$(BIN)/pytest -v tests/

# Environment and hardware acceleration diagnostics
doctor:
	@if [ ! -f "$(BIN)/tg-downloader" ]; then $(MAKE) sync; fi
	@$(BIN)/tg-downloader doctor

# Cache and temporary file cleanup
clean:
	@echo "==> Cleaning temporary files, caches, and build artifacts..."
	@rm -rf build/ dist/ *.egg-info .eggs/
	@rm -rf .ruff_cache/ .pytest_cache/
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@find . -type f -name "*.pyo" -delete
	@find . -type f -name "*.part" -delete
	@find . -type f -name "*.part.meta" -delete
	@echo "==> Clean complete."
