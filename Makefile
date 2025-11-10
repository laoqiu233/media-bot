.PHONY: help install shell run test lint format clean

help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies"
	@echo "  make shell      - Enter virtual environment"
	@echo "  make run        - Run the application"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run linting"
	@echo "  make format     - Format code"
	@echo "  make clean      - Clean cache files"

install:
	poetry install

shell:
	poetry shell

run:
	poetry run python -m app

test:
	poetry run pytest

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

