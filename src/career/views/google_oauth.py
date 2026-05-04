from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from ..services.google_oauth import (
    build_google_oauth_authorization_url,
    complete_google_oauth_callback,
    disconnect_google_oauth,
    google_oauth_status,
    list_google_spreadsheet_tabs,
    list_google_spreadsheets,
)


class GoogleOAuthViewSet(ViewSet):
    @action(detail=False, methods=['get'], url_path='status')
    def status(self, request):
        return Response(google_oauth_status(request.user), status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='connect')
    def connect(self, request):
        redirect_uri = request.build_absolute_uri(reverse('google-oauth-callback'))
        authorization_url = build_google_oauth_authorization_url(
            request.user,
            redirect_uri,
            request.data.get('redirect_url', ''),
        )
        return Response({'authorization_url': authorization_url}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='disconnect')
    def disconnect(self, request):
        disconnect_google_oauth(request.user)
        return Response({'ok': True}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='spreadsheets')
    def spreadsheets(self, request):
        spreadsheets = list_google_spreadsheets(request.user)
        return Response({'spreadsheets': spreadsheets}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='spreadsheet-tabs')
    def spreadsheet_tabs(self, request):
        tabs = list_google_spreadsheet_tabs(request.user, request.query_params.get('spreadsheet_id', ''))
        return Response({'tabs': tabs}, status=status.HTTP_200_OK)


class GoogleOAuthCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        state = request.query_params.get('state', '')
        code = request.query_params.get('code', '')
        error = request.query_params.get('error', '')
        redirect_base = settings.GOOGLE_OAUTH_SUCCESS_REDIRECT_URL or '/'
        if error:
            return redirect(f"{redirect_base}?{urlencode({'google': 'error', 'message': error})}")
        try:
            redirect_uri = request.build_absolute_uri(reverse('google-oauth-callback'))
            state_record = complete_google_oauth_callback(state, code, redirect_uri)
            redirect_url = state_record.redirect_url or redirect_base
            separator = '&' if '?' in redirect_url else '?'
            return redirect(f'{redirect_url}{separator}google=connected')
        except Exception as exc:
            return redirect(f"{redirect_base}?{urlencode({'google': 'error', 'message': str(exc)})}")
