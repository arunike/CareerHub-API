import json
import re

import pandas as pd

from availability.ai_provider import (
    AIProviderConfigurationError,
    AIProviderRequestError,
    relay_ai_provider_chat_completion,
)
from ..models import Application, Company


VISA_SPONSORSHIP_IMPORT_ALIASES = {
    'UNKNOWN': '',
    'NOT SPECIFIED': '',
    '': '',
    'SPONSORSHIP AVAILABLE': 'AVAILABLE',
    'SPONSORSHIP': 'AVAILABLE',
    'YES': 'AVAILABLE',
    'H1B': 'AVAILABLE',
    'H-1B': 'AVAILABLE',
    'TRANSFER': 'TRANSFER_ONLY',
    'TRANSFER ONLY': 'TRANSFER_ONLY',
    'H1B TRANSFER': 'TRANSFER_ONLY',
    'H-1B TRANSFER': 'TRANSFER_ONLY',
    'NO': 'NOT_AVAILABLE',
    'NONE': 'NOT_AVAILABLE',
    'NO SPONSORSHIP': 'NOT_AVAILABLE',
    'NOT NEEDED': 'NOT_NEEDED',
    'CITIZEN': 'NOT_NEEDED',
    'GC': 'NOT_NEEDED',
    'GREEN CARD': 'NOT_NEEDED',
}
DAY_ONE_GC_IMPORT_ALIASES = {
    'UNKNOWN': '',
    'NOT SPECIFIED': '',
    '': '',
    'YES': 'YES',
    'Y': 'YES',
    'TRUE': 'YES',
    'DAY 1 GC': 'YES',
    'NO': 'NO',
    'N': 'NO',
    'FALSE': 'NO',
    'N/A': 'NOT_APPLICABLE',
    'NA': 'NOT_APPLICABLE',
    'NOT APPLICABLE': 'NOT_APPLICABLE',
}

APPLICATION_IMPORT_FIELDS = [
    {'key': 'external_id', 'label': 'External ID', 'required': False},
    {'key': 'company_name', 'label': 'Company', 'required': True},
    {'key': 'role_title', 'label': 'Role', 'required': True},
    {'key': 'status', 'label': 'Status', 'required': False},
    {'key': 'job_link', 'label': 'Job Link', 'required': False},
    {'key': 'salary_range', 'label': 'Salary', 'required': False},
    {'key': 'location', 'label': 'Location', 'required': False},
    {'key': 'office_location', 'label': 'Office Location', 'required': False},
    {'key': 'date_applied', 'label': 'Date Applied', 'required': False},
    {'key': 'notes', 'label': 'Notes', 'required': False},
    {'key': 'visa_sponsorship', 'label': 'Visa Sponsorship', 'required': False},
    {'key': 'day_one_gc', 'label': 'Day 1 GC', 'required': False},
    {'key': 'growth_score', 'label': 'Growth Score', 'required': False},
    {'key': 'work_life_score', 'label': 'Work Life Score', 'required': False},
    {'key': 'brand_score', 'label': 'Brand Score', 'required': False},
    {'key': 'team_score', 'label': 'Team Score', 'required': False},
]

APPLICATION_IMPORT_ALIASES = {
    'external_id': ['external id', 'id', 'row id', 'sheet id', '编号', 'id externe'],
    'company_name': ['company', 'company name', 'employer', 'organization', '公司', '会社', '会社名', '企業', 'empresa', 'compañía', 'entreprise'],
    'role_title': ['role', 'role title', 'title', 'position', 'job title', '职位', '岗位', '職種', '役職', 'puesto', 'cargo', 'poste'],
    'status': ['status', 'stage', 'application status', '状态', '狀態', 'ステータス', 'estado', 'statut'],
    'job_link': ['link', 'job link', 'url', 'posting', 'posting url', '申请链接', '链接', '求人url', '応募リンク', 'enlace', 'lien'],
    'salary_range': ['salary', 'salary range', 'compensation', 'pay', '薪资', '薪水', '給与', '年収', 'salario', 'salaire'],
    'location': ['location', 'home location', 'city', '地点', '位置', '所在地', '勤務地', 'ubicación', 'localisation'],
    'office_location': ['office location', 'office', 'work location', '办公地点', '办公室', 'オフィス', '勤務地', 'oficina', 'bureau'],
    'date_applied': ['date applied', 'applied date', 'application date', 'applied on', '申请日期', '応募日', 'fecha solicitud', 'date candidature'],
    'notes': ['notes', 'note', 'comments', 'comment', '备注', 'メモ', 'notas', 'notes'],
    'visa_sponsorship': ['visa sponsorship', 'visa', 'sponsorship', '签证', 'ビザ', 'visado', 'visa parrainage'],
    'day_one_gc': ['day 1 gc', 'day one gc', 'green card', 'gc', '绿卡', 'グリーンカード'],
    'growth_score': ['growth score', 'growth', '成长', '成長', 'crecimiento'],
    'work_life_score': ['wlb score', 'work life score', 'work life balance', '工作生活平衡', 'ワークライフバランス'],
    'brand_score': ['brand score', 'brand', '品牌', 'ブランド'],
    'team_score': ['team score', 'manager team score', 'team', '团队', 'チーム'],
}


def row_value(row, *names, default=None):
    for name in names:
        if name in row and pd.notna(row.get(name)):
            return row.get(name)
    return default


def normalize_import_choice(value, valid_values, aliases, default=''):
    if value is None or pd.isna(value):
        return default
    normalized = str(value).strip().upper().replace('-', '_').replace(' ', '_')
    if normalized in valid_values:
        return normalized
    label = str(value).strip().upper()
    return aliases.get(label, default)


def normalize_import_score(value):
    if value is None or pd.isna(value):
        return None
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 5 else None


def build_import_mapping(headers):
    normalized_headers = [{'raw': header, 'normalized': _normalize_header(header)} for header in headers]
    mapping = {}
    for field in APPLICATION_IMPORT_FIELDS:
        aliases = [field['key'], field['label'], *APPLICATION_IMPORT_ALIASES.get(field['key'], [])]
        normalized_aliases = {_normalize_header(alias) for alias in aliases}
        match = next(
            (
                header
                for header in normalized_headers
                if header['normalized'] in normalized_aliases
            ),
            None,
        )
        if not match:
            match = next(
                (
                    header
                    for header in normalized_headers
                    if any(alias and (alias in header['normalized'] or header['normalized'] in alias) for alias in normalized_aliases)
                ),
                None,
            )
        if match:
            mapping[field['key']] = match['raw']
    return mapping


def dataframe_to_records(df):
    clean_df = df.where(pd.notna(df), '')
    return [
        {str(key): str(value).strip() if value is not None else '' for key, value in row.items()}
        for row in clean_df.to_dict(orient='records')
    ]


def infer_import_mapping_with_ai(user_settings, headers, sample_rows, baseline_mapping):
    if not _has_ai_provider_config(user_settings):
        return baseline_mapping, 'not_configured', 'AI provider is not configured. Used built-in header matching.'
    try:
        response = relay_ai_provider_chat_completion(
            user_settings=user_settings,
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Map spreadsheet columns to CareerHub application import fields. '
                        'Headers may be synonyms or different languages. Return only JSON. '
                        'Use canonical field keys as object keys and original header names as values. '
                        'Only map a field when the header is clearly represented.'
                    ),
                },
                {
                    'role': 'user',
                    'content': json.dumps(
                        {
                            'canonical_fields': APPLICATION_IMPORT_FIELDS,
                            'headers': headers,
                            'sample_rows': sample_rows[:5],
                            'baseline_mapping': baseline_mapping,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.1,
        )
        content = response['choices'][0]['message']['content']
        normalized = (content or '').strip()
        if normalized.startswith('```'):
            normalized = re.sub(r'^```(?:json)?\s*', '', normalized, flags=re.IGNORECASE)
            normalized = re.sub(r'\s*```$', '', normalized)
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise ValueError('AI provider returned a non-object mapping.')
        valid_headers = set(headers)
        valid_fields = {field['key'] for field in APPLICATION_IMPORT_FIELDS}
        ai_mapping = {
            str(field): str(header)
            for field, header in parsed.items()
            if field in valid_fields and header in valid_headers
        }
        return {**baseline_mapping, **ai_mapping}, 'success', 'AI suggested the column mapping.'
    except (AIProviderConfigurationError, AIProviderRequestError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return baseline_mapping, 'failed', f'AI mapping failed. Used built-in header matching. {str(exc)[:160]}'


def row_to_application_payload(row, mapping):
    payload = {}
    for field, header in (mapping or {}).items():
        if not header:
            continue
        value = row.get(header, '')
        if value is None:
            value = ''
        if field in {'visa_sponsorship', 'day_one_gc', 'growth_score', 'work_life_score', 'brand_score', 'team_score'}:
            continue
        payload[field] = str(value).strip()
    return payload


def apply_extra_import_fields(application, row, mapping):
    updates = []
    visa_sponsorship = normalize_import_choice(
        row.get(mapping.get('visa_sponsorship')),
        {choice[0] for choice in Application.VISA_SPONSORSHIP_CHOICES},
        VISA_SPONSORSHIP_IMPORT_ALIASES,
    )
    day_one_gc = normalize_import_choice(
        row.get(mapping.get('day_one_gc')),
        {choice[0] for choice in Application.DAY_ONE_GC_CHOICES},
        DAY_ONE_GC_IMPORT_ALIASES,
    )
    score_fields = {
        'growth_score': normalize_import_score(row.get(mapping.get('growth_score'))),
        'work_life_score': normalize_import_score(row.get(mapping.get('work_life_score'))),
        'brand_score': normalize_import_score(row.get(mapping.get('brand_score'))),
        'team_score': normalize_import_score(row.get(mapping.get('team_score'))),
    }
    for field, value in {'visa_sponsorship': visa_sponsorship, 'day_one_gc': day_one_gc, **score_fields}.items():
        if field in mapping and getattr(application, field) != value:
            setattr(application, field, value)
            updates.append(field)
    if updates:
        application.save(update_fields=[*updates, 'updated_at'])


def preview_import_rows(user, rows, mapping):
    items = []
    for index, row in enumerate(rows, start=2):
        payload = row_to_application_payload(row, mapping)
        company_name = payload.get('company_name') or ''
        role_title = payload.get('role_title') or ''
        action = 'error'
        detail = ''
        local_object_id = None
        if not company_name or not role_title:
            detail = 'Company and role are required.'
        else:
            company = Company.objects.filter(user=user, name=company_name).first()
            application = Application.objects.filter(user=user, company=company, role_title=role_title).order_by('id').first() if company else None
            if application:
                local_object_id = application.id
                action = 'update'
                detail = 'Matches an existing application by company and role.'
            else:
                action = 'create'
                detail = 'New application.'
        items.append({
            'row': index,
            'action': action,
            'detail': detail,
            'company_name': company_name,
            'role_title': role_title,
            'status': payload.get('status') or 'APPLIED',
            'local_object_id': local_object_id,
            'raw': row,
        })
    return items


def _normalize_header(value):
    return re.sub(r'\s+', ' ', re.sub(r'[_-]+', ' ', str(value or '').strip().lower())).strip()


def _has_ai_provider_config(user_settings):
    return bool(
        getattr(user_settings, 'ai_provider_endpoint', '')
        and getattr(user_settings, 'ai_provider_model', '')
        and user_settings.has_ai_provider_api_key()
    )
