"""
ASGI config for availability_project project.

This deployment shape is HTTP-only. Real-time conflict alerts now use the
standard REST endpoints instead of a WebSocket channel layer so the same app can
run on local Django, Docker, and Vercel's Python runtime without special ASGI
infrastructure.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()
