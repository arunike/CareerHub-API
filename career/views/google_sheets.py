from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import GoogleSheetSyncConfig
from ..serializers import GoogleSheetSyncConfigSerializer
from ..services.google_sheets import apply_import_review, build_import_review, parse_google_sheet_url, preview_sheet, sync_google_sheet


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

    @action(detail=True, methods=['post'], url_path='import-review')
    def import_review(self, request, pk=None):
        config = self.get_object()
        review = build_import_review(config, force=bool(request.data.get('force', False)))
        return Response({'ok': True, 'review': review}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='apply-import-review')
    def apply_review(self, request, pk=None):
        config = self.get_object()
        approved_item_ids = request.data.get('approved_item_ids') or []
        if not isinstance(approved_item_ids, list):
            return Response(
                {'approved_item_ids': ['Expected a list of review item IDs.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        duplicate_resolutions = request.data.get('duplicate_resolutions') or {}
        if not isinstance(duplicate_resolutions, dict):
            return Response(
                {'duplicate_resolutions': ['Expected an object keyed by review item ID.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = apply_import_review(
            config,
            approved_item_ids=approved_item_ids,
            duplicate_resolutions=duplicate_resolutions,
            force=bool(request.data.get('force', False)),
        )
        return Response({'ok': True, 'result': result}, status=status.HTTP_200_OK)
