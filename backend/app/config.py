"""App-wide settings, read from environment variables.

Locally they come from backend/.env; on Railway they're set in the dashboard.
"""
import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

# The brief says to treat September 28, 2026 as "today" for anything time-based.
TODAY = date(2026, 9, 28)

# Basic password protection for the UI. An empty password refuses every login,
# so forgetting to set it fails closed instead of leaving the app open.
APP_USERNAME = os.environ.get("APP_USERNAME", "growth")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# Shared secret the mobile app uses to sign webhook requests (HMAC-SHA256).
# Empty = every webhook request is rejected (again: fail closed).
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# The Claude model the assistant uses. ANTHROPIC_API_KEY is read by the SDK.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
