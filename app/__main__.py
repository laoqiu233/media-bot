"""Entry point for running app as a module with python -m app."""

from app.bot.integrated_bot import run_integrated_bot
import asyncio
import os
from app.init_flow import ensure_telegram_token

if __name__ == "__main__":
    # Ensure bot token available; will run QR+form init if missing
    asyncio.run(ensure_telegram_token())
    run_integrated_bot()
