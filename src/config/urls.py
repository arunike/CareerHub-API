from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from .cron_views import DailyMaintenanceCronView, GoogleSheetSyncCronView
from .public_redirect_views import redirect_public_booking
from .security_views import SecurityDashboardView

urlpatterns = [
    path("book/<path:path>", redirect_public_booking, name="public-booking-redirect"),
    path(
        "api/security/dashboard/",
        SecurityDashboardView.as_view(),
        name="security-dashboard",
    ),
    path(
        "api/internal/cron/daily-maintenance/",
        DailyMaintenanceCronView.as_view(),
        name="daily-maintenance-cron",
    ),
    path(
        "api/internal/cron/google-sheet-syncs/",
        GoogleSheetSyncCronView.as_view(),
        name="google-sheet-sync-cron",
    ),
    path("api/auth/", include("config.auth_urls")),
    path('api/', include('availability.urls')),
    path('api/career/', include('career.urls')),
]

if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path(settings.ADMIN_URL, admin.site.urls))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    from django.urls import re_path
    from django.views.static import serve
    import re
    urlpatterns += [
        re_path(
            rf"^{re.escape(settings.MEDIA_URL.lstrip('/'))}(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
