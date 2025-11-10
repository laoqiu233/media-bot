"""Authorization system for the Telegram bot."""

import logging
from functools import wraps
from typing import List, Optional

from telegram import Update

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages user authorization based on Telegram usernames."""

    def __init__(self, authorized_users: List[str]):
        """Initialize auth manager.

        Args:
            authorized_users: List of authorized Telegram usernames (without @)
        """
        # Normalize usernames (lowercase, remove @ if present)
        self.authorized_users = {
            username.lower().lstrip("@") for username in authorized_users
        }
        logger.info(f"Authorization enabled for {len(self.authorized_users)} users")

    def is_authorized(self, update: Update) -> bool:
        """Check if the user is authorized.

        Args:
            update: Telegram update object

        Returns:
            True if user is authorized, False otherwise
        """
        if not update.effective_user:
            return False

        username = update.effective_user.username
        if not username:
            # User doesn't have a username set
            logger.warning(
                f"User {update.effective_user.id} ({update.effective_user.first_name}) "
                f"attempted access without username"
            )
            return False

        is_auth = username.lower() in self.authorized_users

        if not is_auth:
            logger.warning(
                f"Unauthorized access attempt by @{username} "
                f"(ID: {update.effective_user.id})"
            )

        return is_auth

    def authorization_required(self, handler):
        """Decorator to require authorization for handlers.

        Silently ignores unauthorized users (no response).

        Args:
            handler: The handler function to wrap

        Returns:
            Wrapped handler function
        """

        @wraps(handler)
        async def wrapper(update: Update, context, *args, **kwargs):
            if not self.is_authorized(update):
                # Silently ignore unauthorized users
                return None

            return await handler(update, context, *args, **kwargs)

        return wrapper


# Global auth manager instance (initialized in integrated_bot.py)
_auth_manager: Optional[AuthManager] = None


def init_auth(authorized_users: List[str]) -> AuthManager:
    """Initialize the global auth manager.

    Args:
        authorized_users: List of authorized usernames

    Returns:
        AuthManager instance
    """
    global _auth_manager
    _auth_manager = AuthManager(authorized_users)
    return _auth_manager


def get_auth_manager() -> Optional[AuthManager]:
    """Get the global auth manager instance.

    Returns:
        AuthManager instance or None if not initialized
    """
    return _auth_manager


def is_authorized(update: Update) -> bool:
    """Check if user is authorized using global auth manager.

    Args:
        update: Telegram update

    Returns:
        True if authorized (or no auth configured), False otherwise
    """
    if _auth_manager is None:
        # No auth configured, allow all
        return True

    return _auth_manager.is_authorized(update)

