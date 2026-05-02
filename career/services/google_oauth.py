import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from availability.ai_provider import decrypt_ai_provider_secret, encrypt_ai_provider_secret
from career.models import GoogleOAuthCredential, GoogleOAuthState


GOOGLE_SHEETS_READONLY_SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
GOOGLE_DRIVE_METADATA_READONLY_SCOPE = 'https://www.googleapis.com/auth/drive.metadata.readonly'
GOOGLE_USERINFO_EMAIL_SCOPE = 'https://www.googleapis.com/auth/userinfo.email'
GOOGLE_OAUTH_SCOPES = [
    GOOGLE_SHEETS_READONLY_SCOPE,
    GOOGLE_DRIVE_METADATA_READONLY_SCOPE,
    GOOGLE_USERINFO_EMAIL_SCOPE,
]
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_TOKEN_INFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'
STATE_TTL = timedelta(minutes=15)


def google_oauth_configured():
    return bool(_client_id() and _client_secret())


def google_oauth_status(user):
    credential = GoogleOAuthCredential.objects.filter(user=user).first()
    scopes = credential.scopes if credential else []
    return {
        'configured': google_oauth_configured(),
        'connected': bool(credential and credential.refresh_token_encrypted),
        'email': credential.google_email if credential else '',
        'scopes': scopes,
        'can_list_spreadsheets': GOOGLE_DRIVE_METADATA_READONLY_SCOPE in scopes,
    }


def build_google_oauth_authorization_url(user, redirect_uri, redirect_url=''):
    if not google_oauth_configured():
        raise ValidationError('Google OAuth is not configured.')
    _delete_expired_states()
    state = secrets.token_urlsafe(32)
    GoogleOAuthState.objects.create(user=user, state=state, redirect_url=redirect_url or '')
    query = urlencode(
        {
            'client_id': _client_id(),
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(GOOGLE_OAUTH_SCOPES),
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'consent',
            'state': state,
        }
    )
    return f'{GOOGLE_AUTH_URL}?{query}'


def complete_google_oauth_callback(state, code, redirect_uri):
    _delete_expired_states()
    state_record = GoogleOAuthState.objects.select_related('user').filter(state=state).first()
    if not state_record:
        raise ValidationError('Google OAuth session expired. Please connect again.')
    try:
        token_data = _exchange_code_for_tokens(code, redirect_uri)
        refresh_token = token_data.get('refresh_token') or ''
        if not refresh_token:
            raise ValidationError('Google did not return a refresh token. Please reconnect and grant offline access.')
        access_token = token_data.get('access_token') or ''
        google_email = _fetch_google_email(access_token) if access_token else ''
        scopes = (token_data.get('scope') or ' '.join(GOOGLE_OAUTH_SCOPES)).split()
        GoogleOAuthCredential.objects.update_or_create(
            user=state_record.user,
            defaults={
                'google_email': google_email,
                'scopes': scopes,
                'refresh_token_encrypted': encrypt_ai_provider_secret(refresh_token),
                'token_uri': GOOGLE_TOKEN_URL,
            },
        )
        return state_record
    finally:
        state_record.delete()


def disconnect_google_oauth(user):
    GoogleOAuthCredential.objects.filter(user=user).delete()


def get_google_oauth_credentials(user):
    credential = GoogleOAuthCredential.objects.filter(user=user).first()
    if not credential or not credential.refresh_token_encrypted:
        return None
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise ValidationError('Install google-auth to use Google OAuth.') from exc

    refresh_token = decrypt_ai_provider_secret(credential.refresh_token_encrypted)
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=credential.token_uri or GOOGLE_TOKEN_URL,
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=credential.scopes or GOOGLE_OAUTH_SCOPES,
    )


def list_google_spreadsheets(user, page_size=50):
    credentials = get_google_oauth_credentials(user)
    if not credentials:
        raise ValidationError('Connect Google first.')
    if GOOGLE_DRIVE_METADATA_READONLY_SCOPE not in getattr(credentials, 'scopes', []):
        raise ValidationError('Reconnect Google to allow spreadsheet selection.')
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ValidationError('Install google-api-python-client to list Google Sheets.') from exc

    service = build('drive', 'v3', credentials=credentials, cache_discovery=False)
    response = service.files().list(
        q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
        fields='files(id,name,webViewLink,modifiedTime)',
        orderBy='modifiedTime desc',
        pageSize=max(1, min(int(page_size or 50), 100)),
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    return [
        {
            'id': item.get('id', ''),
            'name': item.get('name', ''),
            'url': item.get('webViewLink') or f"https://docs.google.com/spreadsheets/d/{item.get('id', '')}/edit",
            'modified_time': item.get('modifiedTime', ''),
        }
        for item in response.get('files', [])
    ]


def list_google_spreadsheet_tabs(user, spreadsheet_id):
    credentials = get_google_oauth_credentials(user)
    if not credentials:
        raise ValidationError('Connect Google first.')
    spreadsheet_id = (spreadsheet_id or '').strip()
    if not spreadsheet_id:
        raise ValidationError('Spreadsheet ID is required.')
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ValidationError('Install google-api-python-client to list worksheet tabs.') from exc

    service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields='sheets(properties(sheetId,title,index))',
    ).execute()
    return [
        {
            'id': sheet.get('properties', {}).get('sheetId'),
            'title': sheet.get('properties', {}).get('title', ''),
            'index': sheet.get('properties', {}).get('index', 0),
        }
        for sheet in response.get('sheets', [])
        if sheet.get('properties', {}).get('title')
    ]


def _exchange_code_for_tokens(code, redirect_uri):
    body = urlencode(
        {
            'code': code,
            'client_id': _client_id(),
            'client_secret': _client_secret(),
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
    ).encode('utf-8')
    request = Request(
        GOOGLE_TOKEN_URL,
        data=body,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode('utf-8'))


def _fetch_google_email(access_token):
    request = Request(GOOGLE_TOKEN_INFO_URL, headers={'Authorization': f'Bearer {access_token}'})
    with urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode('utf-8'))
    return data.get('email', '')


def _delete_expired_states():
    GoogleOAuthState.objects.filter(created_at__lt=timezone.now() - STATE_TTL).delete()


def _client_id():
    return getattr(settings, 'GOOGLE_OAUTH_CLIENT_ID', '').strip()


def _client_secret():
    return getattr(settings, 'GOOGLE_OAUTH_CLIENT_SECRET', '').strip()
