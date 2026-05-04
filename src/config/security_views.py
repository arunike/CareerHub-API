import os

from django.conf import settings
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from career.models import GoogleSheetSyncConfig
from career.services.google_oauth import google_oauth_status


class SecurityDashboardView(APIView):
    def get(self, request):
        google_status = google_oauth_status(request.user)
        syncs = GoogleSheetSyncConfig.objects.filter(user=request.user)
        enabled_syncs = syncs.filter(enabled=True)
        error_syncs = syncs.filter(last_status=GoogleSheetSyncConfig.STATUS_ERROR)
        latest_synced_at = (
            syncs.exclude(last_synced_at__isnull=True)
            .order_by('-last_synced_at')
            .values_list('last_synced_at', flat=True)
            .first()
        )

        return Response({
            'environment': {
                'mode': settings.ENVIRONMENT,
                'debug': settings.DEBUG,
                'admin_enabled': settings.ENABLE_ADMIN,
                'public_signup_enabled': settings.ALLOW_PUBLIC_SIGNUP,
                'allowed_hosts_count': len(settings.ALLOWED_HOSTS),
                'cors_origins_count': len(settings.CORS_ALLOWED_ORIGINS),
                'csrf_trusted_origins_count': len(settings.CSRF_TRUSTED_ORIGINS),
                'secure_ssl_redirect': settings.SECURE_SSL_REDIRECT,
                'session_cookie_secure': settings.SESSION_COOKIE_SECURE,
                'csrf_cookie_secure': settings.CSRF_COOKIE_SECURE,
                'hsts_seconds': settings.SECURE_HSTS_SECONDS,
            },
            'auth': {
                'login_rate': settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].get('login', ''),
                'signup_rate': settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].get('signup', ''),
                'token_refresh_rate': settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].get('token_refresh', ''),
                'jwt_access_minutes': int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds() // 60),
                'jwt_refresh_days': settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].days,
                'refresh_rotation_enabled': settings.SIMPLE_JWT['ROTATE_REFRESH_TOKENS'],
                'refresh_blacklist_enabled': settings.SIMPLE_JWT['BLACKLIST_AFTER_ROTATION'],
            },
            'google': {
                'oauth_configured': google_status['configured'],
                'oauth_connected': google_status['connected'],
                'connected_email': google_status['email'],
                'can_list_spreadsheets': google_status.get('can_list_spreadsheets', False),
                'total_syncs': syncs.count(),
                'enabled_syncs': enabled_syncs.count(),
                'error_syncs': error_syncs.count(),
                'latest_synced_at': latest_synced_at,
                'latest_error': error_syncs.order_by('-updated_at').values_list('last_error', flat=True).first() or '',
            },
            'waf': {
                'vercel_project': bool(os.environ.get('VERCEL') or os.environ.get('VERCEL_URL')),
                'edge_scanner_denies_deployed': True,
                'firewall_actions_file': 'vercel-firewall-actions.json',
                'bot_protection_configured': _env_bool("VERCEL_FIREWALL_BOT_PROTECTION_CONFIGURED", True),
                'ai_bots_blocked': _env_bool("VERCEL_FIREWALL_AI_BOTS_BLOCKED", True),
            },
            'checked_at': timezone.now(),
        })


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}
