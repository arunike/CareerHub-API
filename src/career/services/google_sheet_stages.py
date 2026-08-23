import math
import re

from availability.models import UserSettings
from career.models import Application

from .sheet_parsing import clean_cell as _clean_cell
from .google_sheet_constants import (
    CUSTOM_STAGE_TONES,
    DEFAULT_APPLICATION_STAGES,
    REMOVED_FROM_SHEET_STAGE,
    REMOVED_FROM_SHEET_STATUS,
    ROUND_TONES,
    STATUS_ALIASES,
)


def _normalize_application_status(value, user, ensure_stage=True, stage_events=None):
    cleaned = _clean_status_text(value)
    if not cleaned:
        return 'APPLIED'

    round_match = re.search(r'\b(\d+)(?:st|nd|rd|th)?\s+round\b', cleaned)
    if round_match:
        round_number = int(round_match.group(1))
        key = f'ROUND_{round_number}'
        if ensure_stage:
            _ensure_application_stage(user, key, _round_label(round_number), f'R{round_number}', _round_tone(round_number), stage_events=stage_events)
        return key

    alias_key = STATUS_ALIASES.get(cleaned)
    if alias_key:
        if ensure_stage:
            _ensure_known_stage(user, alias_key, stage_events=stage_events)
        return alias_key

    key = re.sub(r'[^A-Z0-9]+', '_', cleaned.upper()).strip('_') or 'APPLIED'
    label = _title_status(cleaned)
    if ensure_stage:
        _ensure_application_stage(user, key, label, _short_label(label), _custom_stage_tone(user), stage_events=stage_events)
    return key


def _clean_status_text(value):
    text = _clean_cell(value)
    text = re.sub(r'\s*\([^)]*\)', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip().lower()


def _ensure_known_stage(user, key, stage_events=None):
    known = {stage['key']: stage for stage in DEFAULT_APPLICATION_STAGES}
    stage = known.get(key)
    if stage:
        _ensure_application_stage(user, stage['key'], stage['label'], stage['shortLabel'], stage['tone'], stage_events=stage_events)


def _ensure_application_stage(user, key, label, short_label, tone, stage_events=None):
    if not user:
        return
    settings_profile, _ = UserSettings.objects.get_or_create(user=user)
    stages = settings_profile.application_stages or [stage.copy() for stage in DEFAULT_APPLICATION_STAGES]
    if any(stage.get('key') == key for stage in stages):
        if not settings_profile.application_stages:
            settings_profile.application_stages = stages
            settings_profile.save(update_fields=['application_stages', 'updated_at'])
        return
    stages.append({'key': key, 'label': label, 'shortLabel': short_label, 'tone': tone})
    settings_profile.application_stages = stages
    settings_profile.save(update_fields=['application_stages', 'updated_at'])
    if stage_events is not None:
        stage_events.append({'key': key, 'label': label, 'shortLabel': short_label, 'tone': tone})


def _round_label(round_number):
    if 10 <= round_number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(round_number % 10, 'th')
    return f'{round_number}{suffix} Round'


def _round_tone(round_number):
    normalized_round = max(round_number, 1)
    if normalized_round <= len(ROUND_TONES):
        return ROUND_TONES[normalized_round - 1]
    return _generated_round_tone(normalized_round)


def _generated_round_tone(round_number):
    sequence_index = round_number - len(ROUND_TONES)
    hue_phase = (sequence_index * 0.618033988749895) % 1
    lightness_phase = (sequence_index * 0.414213562373095) % 1
    hue = 255 + (hue_phase * 70)
    lightness = 0.64 - (lightness_phase * 0.1)
    return _oklch_to_hex(lightness, 0.13, hue)


def _oklch_to_hex(lightness, chroma, hue_degrees):
    hue_radians = math.radians(hue_degrees)
    a = chroma * math.cos(hue_radians)
    b = chroma * math.sin(hue_radians)

    l_root = lightness + (0.3963377774 * a) + (0.2158037573 * b)
    m_root = lightness - (0.1055613458 * a) - (0.0638541728 * b)
    s_root = lightness - (0.0894841775 * a) - (1.291485548 * b)
    l_value, m_value, s_value = l_root**3, m_root**3, s_root**3

    linear_rgb = (
        (4.0767416621 * l_value) - (3.3077115913 * m_value) + (0.2309699292 * s_value),
        (-1.2684380046 * l_value) + (2.6097574011 * m_value) - (0.3413193965 * s_value),
        (-0.0041960863 * l_value) - (0.7034186147 * m_value) + (1.707614701 * s_value),
    )

    def to_srgb(channel):
        encoded = (
            12.92 * channel
            if channel <= 0.0031308
            else (1.055 * (channel ** (1 / 2.4))) - 0.055
        )
        return round(min(max(encoded, 0), 1) * 255)

    red, green, blue = (to_srgb(channel) for channel in linear_rgb)
    return f'#{red:02X}{green:02X}{blue:02X}'


def _custom_stage_tone(user):
    if not user:
        return CUSTOM_STAGE_TONES[0]
    settings_profile = UserSettings.objects.filter(user=user).first()
    existing_count = len(settings_profile.application_stages or []) if settings_profile else 0
    return CUSTOM_STAGE_TONES[existing_count % len(CUSTOM_STAGE_TONES)]


def _title_status(value):
    return ' '.join(part.capitalize() for part in value.split())


def _short_label(label):
    words = [word for word in re.split(r'\s+', label) if word]
    if not words:
        return label[:6]
    if len(words) == 1:
        return words[0][:8]
    return ''.join(word[0].upper() for word in words[:3])


def _application_stage_label(user, key):
    if not key:
        return 'blank'
    settings_profile = UserSettings.objects.filter(user=user).first()
    stages = (settings_profile.application_stages if settings_profile and settings_profile.application_stages else DEFAULT_APPLICATION_STAGES)
    stage = next((candidate for candidate in stages if candidate.get('key') == key), None)
    return stage.get('label') if stage else _title_status(str(key).replace('_', ' ').lower())
