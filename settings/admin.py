from __future__ import annotations

from settings.app import APP_SETTINGS

ADMIN_API_ENABLED = APP_SETTINGS.admin_api_enabled
ADMIN_API_BASE_PATH = APP_SETTINGS.admin_api_base_path
ADMIN_API_TOKEN = APP_SETTINGS.admin_api_token
ADMIN_API_DISABLE_AUTH_FOR_TESTING = APP_SETTINGS.admin_api_disable_auth_for_testing

__all__ = [
    "ADMIN_API_BASE_PATH",
    "ADMIN_API_DISABLE_AUTH_FOR_TESTING",
    "ADMIN_API_ENABLED",
    "ADMIN_API_TOKEN",
]
