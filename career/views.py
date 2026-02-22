from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Company, Application, Offer, Document, Task
from .serializers import CompanySerializer, ApplicationSerializer, ApplicationExportSerializer, OfferSerializer, DocumentSerializer, DocumentExportSerializer, TaskSerializer
from availability.utils import export_data
from datetime import datetime, timedelta
from django.db.models import Q, Max
from django.db import transaction
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.views import APIView
from django.utils.dateparse import parse_date
import pandas as pd
import os
import json
from urllib.parse import quote
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from django.utils import timezone
from availability.models import Event

MARITAL_STATUS_OPTIONS = [
    {"code": "SINGLE", "label": "Single"},
    {"code": "MARRIED_FILING_JOINTLY", "label": "Married Filing Jointly"},
    {"code": "MARRIED_FILING_SEPARATELY", "label": "Married Filing Separately"},
    {"code": "HEAD_OF_HOUSEHOLD", "label": "Head of Household"},
]

CITY_COST_OF_LIVING = {
    "San Francisco, CA": 168,
    "San Jose, CA": 156,
    "Seattle, WA": 132,
    "New York, NY": 154,
    "Austin, TX": 111,
    "Chicago, IL": 117,
    "Boston, MA": 148,
    "Los Angeles, CA": 149,
    "Atlanta, GA": 104,
    "Denver, CO": 121,
    "Remote / National Average": 100,
}

STATE_COL_BASE = {
    "AL": 89, "AK": 128, "AZ": 104, "AR": 88, "CA": 134, "CO": 112, "CT": 115, "DE": 103, "FL": 102, "GA": 97,
    "HI": 186, "ID": 101, "IL": 101, "IN": 90, "IA": 89, "KS": 90, "KY": 91, "LA": 92, "ME": 108, "MD": 112,
    "MA": 123, "MI": 92, "MN": 98, "MS": 86, "MO": 90, "MT": 101, "NE": 92, "NV": 105, "NH": 111, "NJ": 118,
    "NM": 94, "NY": 123, "NC": 95, "ND": 95, "OH": 91, "OK": 89, "OR": 113, "PA": 99, "RI": 109, "SC": 94,
    "SD": 94, "TN": 91, "TX": 97, "UT": 104, "VT": 110, "VA": 105, "WA": 114, "WV": 89, "WI": 95, "WY": 97, "DC": 152,
}

STATE_TAX_RATE = {
    "AK": 0, "FL": 0, "NV": 0, "SD": 0, "TN": 0, "TX": 0, "WA": 0, "WY": 0, "NH": 0, "AL": 4.5, "AZ": 2.5,
    "AR": 4.4, "CA": 8.5, "CO": 4.4, "CT": 5.0, "DE": 5.0, "GA": 5.2, "HI": 7.0, "ID": 5.8, "IL": 4.95,
    "IN": 3.15, "IA": 4.5, "KS": 5.2, "KY": 4.0, "LA": 3.5, "ME": 6.0, "MD": 5.0, "MA": 5.0, "MI": 4.25,
    "MN": 6.2, "MS": 4.7, "MO": 4.9, "MT": 5.5, "NE": 5.8, "NJ": 6.0, "NM": 4.7, "NY": 6.8, "NC": 4.5,
    "ND": 2.5, "OH": 3.5, "OK": 4.8, "OR": 7.8, "PA": 3.07, "RI": 5.0, "SC": 5.4, "UT": 4.85, "VT": 6.0,
    "VA": 4.8, "WV": 4.5, "WI": 5.1, "DC": 7.0,
}

STATE_NAME_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA",
    "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI",
    "Wyoming": "WY", "District of Columbia": "DC",
}

HUD_FMR_BASE_URL = "https://www.huduser.gov/hudapi/public/fmr"


def _parse_city_state(raw_city: str):
    if not raw_city:
        return "", ""
    normalized = raw_city.replace(", United States", "").strip()
    parts = [p.strip() for p in normalized.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1].upper()
    return normalized, ""


def _fallback_rent_payload(city_query: str, state_abbr: str, reason: str):
    state_col = STATE_COL_BASE.get(state_abbr, 100)
    # Lightweight fallback heuristic when HUD cannot be queried.
    monthly_rent = int(round(900 + state_col * 12))
    if "remote" in city_query.lower():
        monthly_rent = 2200

    return {
        "provider": "Fallback Estimate",
        "city": city_query,
        "state": state_abbr or "",
        "matched_area": f"{state_abbr or 'US'} fallback",
        "monthly_rent_estimate": monthly_rent,
        "fmr_year": None,
        "last_updated": timezone.now().isoformat(),
        "manual_override_allowed": True,
        "is_fallback": True,
        "warning": reason,
    }


def fetch_hud_rent_estimate(city_query: str):
    city_name, state_abbr = _parse_city_state(city_query)
    token = os.getenv("HUD_FMR_API_TOKEN", "").strip()
    if not token:
        return _fallback_rent_payload(city_query, state_abbr, "HUD_FMR_API_TOKEN is not configured")
    if not state_abbr:
        return _fallback_rent_payload(city_query, state_abbr, "State code not provided in city string")

    try:
        request = Request(f"{HUD_FMR_BASE_URL}/statedata/{quote(state_abbr)}")
        request.add_header("Authorization", f"Bearer {token}")
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return _fallback_rent_payload(city_query, state_abbr, f"HUD API error: {exc.code}")
    except URLError:
        return _fallback_rent_payload(city_query, state_abbr, "HUD API network error")
    except Exception as exc:
        return _fallback_rent_payload(city_query, state_abbr, f"HUD API parse error: {exc}")

    data = payload.get("data") or {}
    county_rows = data.get("counties") or []
    metro_rows = data.get("metroareas") or []
    all_rows = metro_rows + county_rows

    city_l = city_name.lower()

    def _row_name(row):
        return (
            str(row.get("metro_name") or row.get("county_name") or row.get("name") or "").strip()
        )

    ranked = sorted(
        all_rows,
        key=lambda row: (
            0 if city_l and city_l in _row_name(row).lower() else 1,
            len(_row_name(row)),
        ),
    )
    best = ranked[0] if ranked else {}
    rent_value = (
        best.get("Two-Bedroom")
        or best.get("twobedroom")
        or best.get("2-Bedroom")
        or best.get("onebedroom")
        or best.get("One-Bedroom")
    )

    try:
        monthly_rent = int(str(rent_value).replace(",", ""))
    except Exception:
        return _fallback_rent_payload(city_query, state_abbr, "HUD payload missing rent value")

    return {
        "provider": "HUD FMR API",
        "city": city_query,
        "state": state_abbr,
        "matched_area": _row_name(best) or f"{state_abbr} statewide",
        "monthly_rent_estimate": monthly_rent,
        "fmr_year": data.get("year"),
        "last_updated": timezone.now().isoformat(),
        "manual_override_allowed": True,
        "is_fallback": False,
    }

class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    def get_queryset(self):
        qs = Document.objects.all().order_by('-updated_at')
        include_versions = self.request.query_params.get('include_versions')
        if include_versions in ('1', 'true', 'True'):
            return qs
        return qs.filter(is_current=True)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This document is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(is_current=True, version_number=1, root_document=None)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = Document.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} documents. Locked documents were preserved."},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), DocumentExportSerializer, fmt, 'documents')

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id)).order_by('-version_number')
        serializer = self.get_serializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def add_version(self, request, pk=None):
        doc = self.get_object()
        root = doc.root_document or doc
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            current_versions = Document.objects.filter(Q(id=root.id) | Q(root_document_id=root.id))
            max_version = current_versions.aggregate(max_v=Max('version_number'))['max_v'] or 1
            current_versions.update(is_current=False)

            new_doc = Document.objects.create(
                title=request.data.get('title', doc.title),
                file=file_obj,
                document_type=request.data.get('document_type', doc.document_type),
                application_id=request.data.get('application') if request.data.get('application') not in (None, '', 'null') else doc.application_id,
                root_document=root,
                version_number=max_version + 1,
                is_current=True,
                is_locked=False,
            )

        serializer = self.get_serializer(new_doc)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer

    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.status == 'OFFER' and not hasattr(instance, 'offer'):
            Offer.objects.create(
                application=instance,
                base_salary=0,
                bonus=0,
                equity=0,
                sign_on=0,
                benefits_value=0,
                pto_days=15,
                is_current=False
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "This application is locked and cannot be deleted. Unlock it first."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        # Only delete unlocked applications
        count, _ = Application.objects.filter(is_locked=False).delete()
        return Response(
            {"message": f"Deleted {count} applications. Locked applications were preserved."},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), ApplicationExportSerializer, fmt, 'applications')

class ReferenceDataView(APIView):
    def get(self, request, *args, **kwargs):
        return Response({
            "marital_status_options": MARITAL_STATUS_OPTIONS,
            "city_cost_of_living": CITY_COST_OF_LIVING,
            "state_col_base": STATE_COL_BASE,
            "state_tax_rate": STATE_TAX_RATE,
            "state_name_to_abbr": STATE_NAME_TO_ABBR,
        })


class RentEstimateView(APIView):
    def get(self, request, *args, **kwargs):
        city = (request.query_params.get("city") or "").strip()
        if not city:
            return Response({"error": "city query param is required"}, status=status.HTTP_400_BAD_REQUEST)
        result = fetch_hud_rent_estimate(city)
        return Response(result, status=status.HTTP_200_OK)


def _is_interview_event(event: Event) -> bool:
    category_name = (event.category.name if event.category else "").lower()
    event_name = (event.name or "").lower()
    keywords = ("interview", "onsite", "screen", "recruiter", "recruiting", "oa", "assessment")
    return any(word in category_name for word in keywords) or any(word in event_name for word in keywords)


class WeeklyReviewView(APIView):
    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        default_end = today
        default_start = today - timedelta(days=6)

        start_date = parse_date(request.query_params.get("start_date") or "") or default_start
        end_date = parse_date(request.query_params.get("end_date") or "") or default_end
        if start_date > end_date:
            return Response({"error": "start_date must be on or before end_date"}, status=status.HTTP_400_BAD_REQUEST)

        applications = Application.objects.filter(
            date_applied__isnull=False,
            date_applied__gte=start_date,
            date_applied__lte=end_date,
        ).select_related("company")
        applications_sent = applications.count()
        application_items = [
            {
                "id": app.id,
                "company": app.company.name,
                "role_title": app.role_title,
                "date_applied": app.date_applied,
                "status": app.status,
            }
            for app in applications.order_by("-date_applied", "-id")[:10]
        ]

        week_events = Event.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        ).select_related("category", "application", "application__company")
        interview_events = [event for event in week_events if _is_interview_event(event)]
        interviews_done = len(interview_events)
        interview_items = [
            {
                "id": event.id,
                "name": event.name,
                "date": event.date,
                "company": event.application.company.name if event.application else None,
                "role_title": event.application.role_title if event.application else None,
            }
            for event in sorted(interview_events, key=lambda e: (e.date, e.start_time), reverse=True)[:10]
        ]

        next_week_end = today + timedelta(days=7)
        next_actions_qs = Task.objects.filter(status__in=["TODO", "IN_PROGRESS"]).order_by("due_date", "priority", "position")
        next_actions_items = []
        for task in next_actions_qs:
            due = task.due_date
            if due and due > next_week_end:
                continue
            next_actions_items.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "priority": task.priority,
                    "due_date": task.due_date,
                    "is_overdue": bool(task.due_date and task.due_date < today),
                }
            )
            if len(next_actions_items) >= 8:
                break

        interviews_word = "interview" if interviews_done == 1 else "interviews"
        applications_word = "application" if applications_sent == 1 else "applications"
        summary_lines = [
            f"Week {start_date} to {end_date}: sent {applications_sent} {applications_word} and completed {interviews_done} {interviews_word}.",
        ]
        if next_actions_items:
            top_action_phrases = []
            for item in next_actions_items[:3]:
                due_suffix = f" (due {item['due_date']})" if item["due_date"] else ""
                top_action_phrases.append(f"{item['title']}{due_suffix}")
            summary_lines.append(
                "Top next actions: " + "; ".join(top_action_phrases) + "."
            )
        else:
            summary_lines.append("No pending action items right now.")

        return Response(
            {
                "start_date": start_date,
                "end_date": end_date,
                "applications_sent": applications_sent,
                "interviews_done": interviews_done,
                "next_actions_count": len(next_actions_items),
                "applications": application_items,
                "interviews": interview_items,
                "next_actions": next_actions_items,
                "summary_text": " ".join(summary_lines),
                "generated_at": timezone.now(),
            },
            status=status.HTTP_200_OK,
        )

class ImportApplicationsView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
            elif file_obj.name.endswith('.xlsx'):
                df = pd.read_excel(file_obj)
            else:
                return Response({"error": "Unsupported file format"}, status=status.HTTP_400_BAD_REQUEST)
            
            created_count = 0
            for _, row in df.iterrows():
                # Basic mapping - adjust based on actual columns
                company_name = row.get('company', row.get('Company', 'Unknown'))
                role_title = row.get('role', row.get('Role', 'Unknown Role'))
                status_val = row.get('status', row.get('Status', 'APPLIED')).upper()
                
                company, _ = Company.objects.get_or_create(name=company_name)
                
                Application.objects.create(
                    company=company,
                    role_title=role_title,
                    status=status_val,
                    # Add other fields as best effort
                    job_link=row.get('link', ''),
                    salary_range=row.get('salary', ''),
                    location=row.get('location', ''),
                    date_applied=pd.to_datetime(row.get('date_applied', datetime.now())).date() if 'date_applied' in row else None
                )
                created_count += 1
                
            return Response({"message": f"Successfully imported {created_count} applications"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class OfferViewSet(viewsets.ModelViewSet):
    queryset = Offer.objects.all()
    serializer_class = OfferSerializer


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by('status', 'position', '-updated_at')
    serializer_class = TaskSerializer

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        updates = request.data.get('updates', [])
        if not isinstance(updates, list):
            return Response({"error": "updates must be a list"}, status=status.HTTP_400_BAD_REQUEST)

        for item in updates:
            task_id = item.get('id')
            if task_id is None:
                continue
            Task.objects.filter(id=task_id).update(
                status=item.get('status', 'TODO'),
                position=item.get('position', 0),
            )
        return Response({"message": "Tasks reordered successfully"}, status=status.HTTP_200_OK)
