"""Entry point for running app as a module with python -m app."""

from app.main import main
from app.bot import run_bot

if __name__ == "__main__":
    run_bot()
    main()

