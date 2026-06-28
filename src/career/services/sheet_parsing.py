import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC', 'PR'
}

US_STATE_NAME_TO_ABBR = {
    'alabama': 'AL',
    'alaska': 'AK',
    'arizona': 'AZ',
    'arkansas': 'AR',
    'california': 'CA',
    'colorado': 'CO',
    'connecticut': 'CT',
    'delaware': 'DE',
    'florida': 'FL',
    'georgia': 'GA',
    'hawaii': 'HI',
    'idaho': 'ID',
    'illinois': 'IL',
    'indiana': 'IN',
    'iowa': 'IA',
    'kansas': 'KS',
    'kentucky': 'KY',
    'louisiana': 'LA',
    'maine': 'ME',
    'maryland': 'MD',
    'massachusetts': 'MA',
    'michigan': 'MI',
    'minnesota': 'MN',
    'mississippi': 'MS',
    'missouri': 'MO',
    'montana': 'MT',
    'nebraska': 'NE',
    'nevada': 'NV',
    'new hampshire': 'NH',
    'new jersey': 'NJ',
    'new mexico': 'NM',
    'new york': 'NY',
    'north carolina': 'NC',
    'north dakota': 'ND',
    'ohio': 'OH',
    'oklahoma': 'OK',
    'oregon': 'OR',
    'pennsylvania': 'PA',
    'rhode island': 'RI',
    'south carolina': 'SC',
    'south dakota': 'SD',
    'tennessee': 'TN',
    'texas': 'TX',
    'utah': 'UT',
    'vermont': 'VT',
    'virginia': 'VA',
    'washington': 'WA',
    'west virginia': 'WV',
    'wisconsin': 'WI',
    'wyoming': 'WY',
    'district of columbia': 'DC',
    'puerto rico': 'PR',
}


def row_to_dict(headers, row):
    return {
        header: clean_cell(row[index]) if index < len(row) else ''
        for index, header in enumerate(headers)
        if header
    }


def dedupe_headers(headers):
    seen = {}
    result = []
    for header in headers:
        if not header:
            result.append('')
            continue
        count = seen.get(header, 0)
        seen[header] = count + 1
        result.append(header if count == 0 else f'{header} {count + 1}')
    return result


def clean_cell(value):
    if value is None:
        return ''
    return str(value).strip()


def clean_choice(value, default=''):
    value = clean_cell(value)
    return value.upper().replace('-', '_').replace(' ', '_') if value else default


def timezone_value(value):
    value = clean_choice(value, default='PT')
    return value if value in {'PT', 'ET', 'CT', 'MT'} else 'PT'


def location_type_value(value):
    value = clean_choice(value, default='virtual').lower()
    aliases = {
        'in_person': 'in_person',
        'in-person': 'in_person',
        'in person': 'in_person',
        'onsite': 'in_person',
        'virtual': 'virtual',
        'remote': 'virtual',
        'hybrid': 'hybrid',
    }
    return aliases.get(value, 'virtual')


def normalize_location_string(value):
    val = (value or '').strip()
    if not val:
        return ''

    if val.lower() == 'remote':
        return 'Remote'

    value_without_country = re.sub(r',\s*United States\s*$', '', val, flags=re.IGNORECASE).strip()
    match = re.match(r'^([^,]+),\s*([A-Za-z][A-Za-z\s]+)$', value_without_country)
    if match:
        state_value = match.group(2).strip()
        state = state_value.upper() if len(state_value) == 2 else US_STATE_NAME_TO_ABBR.get(state_value.lower(), '')
        if state in US_STATES:
            city = match.group(1).strip()
            city = ' '.join(word.capitalize() for word in city.split())
            return f"{city}, {state}, United States"
    return val


def location_lookup_values(value):
    canonical = normalize_location_string(value)
    values = [canonical]
    legacy = re.sub(r',\s*United States\s*$', '', canonical, flags=re.IGNORECASE).strip()
    if legacy and legacy != canonical:
        values.append(legacy)
    return values


def parse_date(value):
    value = clean_cell(value)
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    try:
        from django.utils.dateparse import parse_date as django_parse_date

        parsed = django_parse_date(value)
        if parsed:
            return parsed
    except Exception:
        pass
    try:
        serial = Decimal(value)
    except (InvalidOperation, ValueError):
        serial = None
    if serial is not None:
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=int(serial))).date()
    raise ValidationError(f'Could not parse date "{value}".')
