from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("api/auth/", include("config.auth_urls")),
    path('api/', include('availability.urls')),
    path('api/career/', include('career.urls')),
]

if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path(settings.ADMIN_URL, admin.site.urls))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
