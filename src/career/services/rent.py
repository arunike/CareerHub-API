import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.utils import timezone

from .reference_data import STATE_COL_BASE

HUD_FMR_BASE_URL = 'https://www.huduser.gov/hudapi/public/fmr'


def parse_city_state(raw_city: str):
    if not raw_city:
        return '', ''
    normalized = raw_city.replace(', United States', '').strip()
    parts = [p.strip() for p in normalized.split(',') if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1].upper()
    return normalized, ''


def fallback_rent_payload(city_query: str, state_abbr: str, reason: str):
    state_col = STATE_COL_BASE.get(state_abbr, 100)
    monthly_rent = int(round(900 + state_col * 12))
    if 'remote' in city_query.lower():
        monthly_rent = 2200
    return {
        'provider': 'Fallback Estimate',
        'city': city_query,
        'state': state_abbr or '',
        'matched_area': f"{state_abbr or 'US'} fallback",
        'monthly_rent_estimate': monthly_rent,
        'fmr_year': None,
        'last_updated': timezone.now().isoformat(),
        'manual_override_allowed': True,
        'is_fallback': True,
        'warning': reason,
    }


def fetch_hud_rent_estimate(city_query: str):
    city_name, state_abbr = parse_city_state(city_query)
    token = os.getenv('HUD_FMR_API_TOKEN', '').strip()
    if not token:
        return fallback_rent_payload(city_query, state_abbr, 'HUD_FMR_API_TOKEN is not configured')
    if not state_abbr:
        return fallback_rent_payload(city_query, state_abbr, 'State code not provided in city string')

    try:
        request = Request(f'{HUD_FMR_BASE_URL}/statedata/{quote(state_abbr)}')
        request.add_header('Authorization', f'Bearer {token}')
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        return fallback_rent_payload(city_query, state_abbr, f'HUD API error: {exc.code}')
    except URLError:
        return fallback_rent_payload(city_query, state_abbr, 'HUD API network error')
    except Exception as exc:
        return fallback_rent_payload(city_query, state_abbr, f'HUD API parse error: {exc}')

    data = payload.get('data') or {}
    rows = (data.get('metroareas') or []) + (data.get('counties') or [])
    city_l = city_name.lower()

    def row_name(row):
        return str(row.get('metro_name') or row.get('county_name') or row.get('name') or '').strip()

    ranked = sorted(
        rows,
        key=lambda row: (
            0 if city_l and city_l in row_name(row).lower() else 1,
            len(row_name(row)),
        ),
    )
    best = ranked[0] if ranked else {}
    rent_value = (
        best.get('Two-Bedroom')
        or best.get('twobedroom')
        or best.get('2-Bedroom')
        or best.get('onebedroom')
        or best.get('One-Bedroom')
    )

    try:
        monthly_rent = int(str(rent_value).replace(',', ''))
    except Exception:
        return fallback_rent_payload(city_query, state_abbr, 'HUD payload missing rent value')

    return {
        'provider': 'HUD FMR API',
        'city': city_query,
        'state': state_abbr,
        'matched_area': row_name(best) or f'{state_abbr} statewide',
        'monthly_rent_estimate': monthly_rent,
        'fmr_year': data.get('year'),
        'last_updated': timezone.now().isoformat(),
        'manual_override_allowed': True,
        'is_fallback': False,
    }
