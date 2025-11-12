.PHONY: help install install-dev shell run test lint lint-fix format check clean

help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make install-dev  - Install dependencies including dev tools"
	@echo "  make shell        - Enter virtual environment"
	@echo "  make run          - Run the application"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linting checks"
	@echo "  make lint-fix     - Run linting and auto-fix issues"
	@echo "  make format       - Format code"
	@echo "  make check        - Run both linting and formatting checks"
	@echo "  make clean        - Clean cache files"

install:
	poetry install

install-dev:
	poetry install --with dev

shell:
	poetry shell

run:
	./app/scripts/prerun.sh
	poetry run python -m app

test:
	poetry run pytest

lint:
	poetry run ruff check .

lint-fix:
	poetry run ruff check --fix .

format:
	poetry run ruff format .

check: lint
	poetry run ruff format --check .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

