import io
import json
import zipfile
from datetime import datetime

import pandas as pd
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from career.models import Application
from career.serializers import ApplicationExportSerializer

from ..models import ConflictAlert, CustomHoliday, Event, EventCategory, UserSettings
from ..serializers import (
    ConflictAlertSerializer,
    CustomHolidaySerializer,
    EventCategorySerializer,
    EventSerializer,
    UserSettingsSerializer,
)


class ImportViewSet(viewsets.ViewSet):
    def create(self, request):
        from ..utils import parse_import_file

        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded'}, status=400)

        filename = file_obj.name.lower()
        file_type = 'json' if filename.endswith('.json') else 'ics' if filename.endswith('.ics') else None
        if not file_type:
            return Response({'error': 'Unsupported file type. Use .json or .ics'}, status=400)

        items = parse_import_file(file_obj, file_type)
        created_count = 0
        for item in items:
            try:
                if item['classification'] == 'holiday':
                    CustomHoliday.objects.create(
                        date=item['date'],
                        description=item['summary'],
                        is_recurring=True,
                    )
                else:
                    Event.objects.create(
                        name=item['summary'],
                        date=item['date'],
                        start_time=item['start_time'],
                        end_time=item['end_time'],
                        timezone='PT',
                    )
                created_count += 1
            except Exception as exc:
                print(f'Skipping item {item}: {exc}')
        return Response({'message': f'Successfully imported {created_count} items'})


class EventCategoryViewSet(viewsets.ModelViewSet):
    queryset = EventCategory.objects.all()
    serializer_class = EventCategorySerializer


class UserSettingsViewSet(viewsets.ModelViewSet):
    queryset = UserSettings.objects.all()
    serializer_class = UserSettingsSerializer

    @action(detail=False, methods=['get', 'put'])
    def current(self, request):
        settings, _ = UserSettings.objects.get_or_create(id=1)
        if request.method == 'GET':
            return Response(self.get_serializer(settings).data)

        serializer = self.get_serializer(settings, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def export_all(self, request):
        fmt = request.query_params.get('fmt', 'json')
        data_map = {
            'events': (Event.objects.all(), EventSerializer),
            'holidays': (CustomHoliday.objects.all(), CustomHolidaySerializer),
            'applications': (Application.objects.all(), ApplicationExportSerializer),
            'user_settings': (UserSettings.objects.all(), UserSettingsSerializer),
            'categories': (EventCategory.objects.all(), EventCategorySerializer),
        }

        if fmt in {'xlsx', 'excel'}:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                for name, (queryset, serializer_cls) in data_map.items():
                    data = serializer_cls(queryset, many=True).data
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    df.to_excel(writer, sheet_name=name[:31], index=False)
            response = HttpResponse(
                buffer.getvalue(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = (
                f'attachment; filename="availability_manager_export_{datetime.now().strftime("%Y%m%d")}.xlsx"'
            )
            return response

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for name, (queryset, serializer_cls) in data_map.items():
                data = serializer_cls(queryset, many=True).data
                if fmt == 'csv':
                    df = pd.DataFrame(data) if data else pd.DataFrame()
                    csv_buffer = io.StringIO()
                    df.to_csv(csv_buffer, index=False)
                    zip_file.writestr(f'{name}.csv', csv_buffer.getvalue())
                else:
                    zip_file.writestr(f'{name}.json', json.dumps(data, indent=2, default=str))

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="availability_manager_backup_{timestamp}.zip"'
        return response


class ConflictAlertViewSet(viewsets.ModelViewSet):
    queryset = ConflictAlert.objects.all()
    serializer_class = ConflictAlertSerializer

    @action(detail=False, methods=['get'])
    def unresolved(self, request):
        conflicts = ConflictAlert.objects.filter(resolved=False)
        serializer = self.get_serializer(conflicts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        conflict = self.get_object()
        conflict.resolved = True
        conflict.save()
        return Response({'message': 'Conflict resolved'})
