from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework.exceptions import ValidationError

DEFAULT_TIMEZONE = 'America/Los_Angeles'

def normalize_timezone(value, default=DEFAULT_TIMEZONE, *, raise_exception=False):
    raw_value = str(value or '').strip()
    if not raw_value:
        return default

    try:
        ZoneInfo(raw_value)
    except ZoneInfoNotFoundError:
        if raise_exception:
            raise ValidationError('Enter a valid IANA timezone, for example Asia/Tokyo.')
        return default

    return raw_value
