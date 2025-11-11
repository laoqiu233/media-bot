"""Entry point for running app as a module with python -m app."""

import asyncio

from app.bot.integrated_bot import run_integrated_bot
from app.init_flow import ensure_telegram_token

if __name__ == "__main__":
    # Ensure bot token available; will run QR+form init if missing
    asyncio.run(ensure_telegram_token())
    run_integrated_bot()
