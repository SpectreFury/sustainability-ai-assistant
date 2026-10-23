from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\x00", "")


def sanitize_json(value):
    """Remove PostgreSQL-incompatible NULs and normalize JSONB values."""
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {
            sanitize_text(str(key)) or "": sanitize_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_json(item) for item in value]
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_text(str(value))
