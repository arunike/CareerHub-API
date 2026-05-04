from django.conf import settings
from django.http import HttpResponseNotFound
from django.shortcuts import redirect


def redirect_public_booking(request, path):
    frontend_base_url = getattr(settings, "PUBLIC_FRONTEND_BASE_URL", "").rstrip("/")
    if not frontend_base_url:
        return HttpResponseNotFound("Public booking frontend is not configured.")
    suffix = f"/book/{path}"
    if request.META.get("QUERY_STRING"):
        suffix = f"{suffix}?{request.META['QUERY_STRING']}"
    return redirect(f"{frontend_base_url}{suffix}", permanent=False)
