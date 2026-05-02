from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import GoogleSheetSyncConfig
from ..serializers import GoogleSheetSyncConfigSerializer
from ..services.google_sheets import parse_google_sheet_url, preview_sheet, sync_google_sheet


class GoogleSheetSyncConfigViewSet(viewsets.ModelViewSet):
    serializer_class = GoogleSheetSyncConfigSerializer

    def get_queryset(self):
        return GoogleSheetSyncConfig.objects.filter(user=self.request.user)

    @action(detail=False, methods=['post'], url_path='preview')
    def preview_draft(self, request):
        spreadsheet_id, gid = parse_google_sheet_url(request.data.get('sheet_url', ''))
        if not spreadsheet_id:
            return Response(
                {'sheet_url': ['Enter a valid Google Sheets link.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            header_row = int(request.data.get('header_row') or 1)
        except (TypeError, ValueError):
            header_row = 1
        target_type = request.data.get('target_type') or GoogleSheetSyncConfig.TARGET_APPLICATIONS
        if target_type not in {GoogleSheetSyncConfig.TARGET_APPLICATIONS, GoogleSheetSyncConfig.TARGET_EVENTS}:
            target_type = GoogleSheetSyncConfig.TARGET_APPLICATIONS

        config = GoogleSheetSyncConfig(
            user=request.user,
            name=request.data.get('name') or 'Preview',
            sheet_url=request.data.get('sheet_url', ''),
            spreadsheet_id=spreadsheet_id,
            gid=gid,
            worksheet_name=request.data.get('worksheet_name', ''),
            target_type=target_type,
            header_row=max(header_row, 1),
            column_mapping=request.data.get('column_mapping') or {},
            enabled=bool(request.data.get('enabled', True)),
        )
        preview = preview_sheet(config)
        return Response({'ok': True, 'preview': preview}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='test')
    def test_connection(self, request, pk=None):
        config = self.get_object()
        preview = preview_sheet(config)
        return Response({'ok': True, 'preview': preview}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='sync-now')
    def sync_now(self, request, pk=None):
        config = self.get_object()
        result = sync_google_sheet(config)
        return Response({'ok': True, 'result': result}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='resync')
    def resync(self, request, pk=None):
        config = self.get_object()
        result = sync_google_sheet(config, force=True)
        return Response({'ok': True, 'result': result}, status=status.HTTP_200_OK)
