import ast
import json
import os
from base64 import b64decode
from binascii import Error as BinasciiError

import pandas as pd
from django.core.files.base import ContentFile
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView
from rest_framework.response import Response
from availability.utils import export_data

from ..models import Application, Company, Experience, Offer
from ..serializers import ExperienceExportSerializer, ExperienceSerializer
from ..llm_matcher import generate_jd_match_evaluation


def _empty_value(value):
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and value.strip().lower() in {'', 'null', 'none', 'nan'}:
        return True
    return False


def _parse_bool(value, default=False):
    if _empty_value(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {'true', '1', 'yes', 'y'}:
        return True
    if normalized in {'false', '0', 'no', 'n'}:
        return False
    return default


def _parse_structured_value(value, default):
    if _empty_value(value):
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return json.loads(stripped)
        except Exception:
            try:
                return ast.literal_eval(stripped)
            except Exception:
                return default
    return default


def _parse_date_value(value):
    if _empty_value(value):
        return None
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    parsed = pd.to_datetime(value, errors='coerce')
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _clean_record(record):
    cleaned = {}
    for key, value in record.items():
        cleaned[key] = None if _empty_value(value) else value
    return cleaned


def _build_application_payload(raw_application, fallback_company, fallback_title):
    if raw_application is None:
        raw_application = {}
    application_payload = _clean_record(raw_application)
    company_name = (
        application_payload.get('company')
        or fallback_company
        or 'Imported Company'
    )
    role_title = application_payload.get('role_title') or fallback_title or 'Imported Role'
    payload = {
        'company_name': company_name,
        'role_title': role_title,
        'status': application_payload.get('status') or 'OFFER',
        'job_link': application_payload.get('job_link'),
        'rto_policy': application_payload.get('rto_policy') or 'UNKNOWN',
        'rto_days_per_week': application_payload.get('rto_days_per_week') or 0,
        'commute_cost_value': application_payload.get('commute_cost_value') or 0,
        'commute_cost_frequency': application_payload.get('commute_cost_frequency') or 'MONTHLY',
        'free_food_perk_value': application_payload.get('free_food_perk_value') or 0,
        'free_food_perk_frequency': application_payload.get('free_food_perk_frequency') or 'YEARLY',
        'tax_base_rate': application_payload.get('tax_base_rate'),
        'tax_bonus_rate': application_payload.get('tax_bonus_rate'),
        'tax_equity_rate': application_payload.get('tax_equity_rate'),
        'monthly_rent_override': application_payload.get('monthly_rent_override'),
        'salary_range': application_payload.get('salary_range') or '',
        'location': application_payload.get('location') or '',
        'office_location': application_payload.get('office_location') or '',
        'employment_type': application_payload.get('employment_type') or 'full_time',
        'notes': application_payload.get('notes') or '',
        'current_round': application_payload.get('current_round') or 0,
        'is_locked': _parse_bool(application_payload.get('is_locked'), default=False),
        'date_applied': _parse_date_value(application_payload.get('date_applied')),
    }
    return payload


def _build_offer_payload(raw_offer):
    if raw_offer is None:
        raw_offer = {}
    offer_payload = _clean_record(raw_offer)
    payload = {
        'base_salary': offer_payload.get('base_salary') or 0,
        'bonus': offer_payload.get('bonus') or 0,
        'equity': offer_payload.get('equity') or 0,
        'equity_total_grant': offer_payload.get('equity_total_grant'),
        'equity_vesting_percent': offer_payload.get('equity_vesting_percent') or 25,
        'sign_on': offer_payload.get('sign_on') or 0,
        'benefits_value': offer_payload.get('benefits_value') or 0,
        'benefit_items': _parse_structured_value(offer_payload.get('benefit_items'), []),
        'pto_days': 15 if _empty_value(offer_payload.get('pto_days')) else offer_payload.get('pto_days'),
        'is_unlimited_pto': _parse_bool(offer_payload.get('is_unlimited_pto'), default=False),
        'holiday_days': 11 if _empty_value(offer_payload.get('holiday_days')) else offer_payload.get('holiday_days'),
        'is_current': _parse_bool(offer_payload.get('is_current'), default=False),
        'raise_history': _parse_structured_value(offer_payload.get('raise_history'), []),
    }
    return payload


def _build_experience_payload(record):
    cleaned = _clean_record(record)
    payload = {
        'title': cleaned.get('title') or 'Untitled Role',
        'company': cleaned.get('company') or 'Imported Company',
        'location': cleaned.get('location') or '',
        'start_date': _parse_date_value(cleaned.get('start_date')),
        'end_date': _parse_date_value(cleaned.get('end_date')),
        'is_current': _parse_bool(cleaned.get('is_current'), default=False),
        'description': cleaned.get('description') or '',
        'skills': _parse_structured_value(cleaned.get('skills'), []),
        'employment_type': cleaned.get('employment_type') or 'full_time',
        'is_promotion': _parse_bool(cleaned.get('is_promotion'), default=False),
        'is_return_offer': _parse_bool(cleaned.get('is_return_offer'), default=False),
        'is_locked': _parse_bool(cleaned.get('is_locked'), default=False),
        'is_pinned': _parse_bool(cleaned.get('is_pinned'), default=False),
        'hourly_rate': cleaned.get('hourly_rate'),
        'hours_per_day': cleaned.get('hours_per_day'),
        'working_days_per_week': cleaned.get('working_days_per_week'),
        'total_hours_worked': cleaned.get('total_hours_worked'),
        'overtime_hours': cleaned.get('overtime_hours'),
        'overtime_rate': cleaned.get('overtime_rate'),
        'overtime_multiplier': cleaned.get('overtime_multiplier'),
        'total_earnings_override': cleaned.get('total_earnings_override'),
        'base_salary': cleaned.get('base_salary'),
        'bonus': cleaned.get('bonus'),
        'equity': cleaned.get('equity'),
        'team_history': _parse_structured_value(cleaned.get('team_history'), []),
        'schedule_phases': _parse_structured_value(cleaned.get('schedule_phases'), []),
    }
    return payload


def _decode_logo_content(record):
    logo_base64 = record.get('logo_base64')
    if _empty_value(logo_base64):
        return None, None

    payload = str(logo_base64).strip()
    if ',' in payload and payload.lower().startswith('data:'):
        payload = payload.split(',', 1)[1]

    try:
        decoded = b64decode(payload)
    except (BinasciiError, ValueError):
        raise ValueError('Invalid logo data in import file.')

    filename = record.get('logo_filename') or 'experience-logo'
    filename = os.path.basename(str(filename)) or 'experience-logo'
    return ContentFile(decoded, name=filename), filename


def _create_offer_from_snapshot(record, offer_map, user):
    offer_data = _parse_structured_value(record.get('offer_data'), None)
    if not offer_data:
        return None

    offer_reference_id = record.get('offer_reference_id')
    if not _empty_value(offer_reference_id):
        reference_key = str(offer_reference_id)
        if reference_key in offer_map:
            return offer_map[reference_key]
    else:
        reference_key = None

    application_snapshot = _parse_structured_value(record.get('offer_application_data'), None)
    application_payload = _build_application_payload(
        application_snapshot,
        fallback_company=record.get('company'),
        fallback_title=record.get('title'),
    )
    company, _ = Company.objects.get_or_create(user=user, name=application_payload.pop('company_name'))
    application = Application.objects.create(user=user, company=company, **application_payload)

    offer_payload = _build_offer_payload(offer_data)
    offer = Offer.objects.create(application=application, **offer_payload)

    if reference_key is not None:
        offer_map[reference_key] = offer
    return offer


class ExperienceViewSet(viewsets.ModelViewSet):
    queryset = Experience.objects.all().order_by('-start_date', '-created_at')
    serializer_class = ExperienceSerializer

    def get_queryset(self):
        return Experience.objects.filter(user=self.request.user).order_by('-start_date', '-created_at')

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        locked = instance.is_locked or False
        allowed_locked_fields = {'is_locked', 'is_pinned', 'team_history'}
        if locked and not set(request.data.keys()).issubset(allowed_locked_fields):
            return Response({'error': 'This experience is locked and cannot be edited.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked or False:
            return Response({'error': 'This experience is locked and cannot be deleted.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'], url_path='delete_all')
    def delete_all(self, request):
        self.get_queryset().filter(is_locked__in=[False, None]).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), ExperienceExportSerializer, fmt, 'experiences')

    @action(detail=True, methods=['post'], url_path='upload-logo', parser_classes=[MultiPartParser])
    def upload_logo(self, request, pk=None):
        instance = self.get_object()
        if 'logo' not in request.FILES:
            return Response({'error': 'No logo file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        
        if instance.logo:
            instance.logo.delete(save=False)
        instance.logo = request.FILES['logo']
        instance.save(update_fields=['logo'])
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['delete'], url_path='remove-logo')
    def remove_logo(self, request, pk=None):
        instance = self.get_object()
        if instance.logo:
            instance.logo.delete(save=False)
            instance.logo = None
            instance.save(update_fields=['logo'])
        return Response(self.get_serializer(instance).data)

class MatchJDView(APIView):
    def post(self, request, *args, **kwargs):
        text = request.data.get('text', '')
        if not text:
            return Response({'error': 'No job description provided.'}, status=400)
            
        try:
            evaluation = generate_jd_match_evaluation(text, request.user)
            return Response(evaluation)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)


class ImportExperiencesView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            records = self._load_records(file_obj)
            if not isinstance(records, list) or not records:
                return Response({'error': 'No experiences found in import file'}, status=status.HTTP_400_BAD_REQUEST)

            created_count = 0
            offer_map = {}

            with transaction.atomic():
                for raw_record in records:
                    record = _clean_record(raw_record if isinstance(raw_record, dict) else {})
                    experience_payload = _build_experience_payload(record)
                    offer = _create_offer_from_snapshot(record, offer_map, request.user)
                    if offer:
                        experience_payload['offer'] = offer.id

                    serializer = ExperienceSerializer(data=experience_payload, context={'request': request})
                    serializer.is_valid(raise_exception=True)
                    experience = serializer.save()

                    logo_content, _ = _decode_logo_content(record)
                    if logo_content is not None:
                        experience.logo.save(logo_content.name, logo_content, save=True)

                    created_count += 1

            return Response({'message': f'Successfully imported {created_count} experiences'})
        except Exception as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def _load_records(self, file_obj):
        file_name = file_obj.name.lower()
        if file_name.endswith('.json'):
            payload = json.loads(file_obj.read().decode('utf-8'))
            if isinstance(payload, dict):
                return payload.get('experiences') or payload.get('items') or []
            return payload
        if file_name.endswith('.csv'):
            df = pd.read_csv(file_obj)
            return df.where(pd.notna(df), None).to_dict(orient='records')
        if file_name.endswith('.xlsx'):
            df = pd.read_excel(file_obj)
            return df.where(pd.notna(df), None).to_dict(orient='records')
        raise ValueError('Unsupported file format')
