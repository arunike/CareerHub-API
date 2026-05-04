"""
WSGI config for availability_project project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import sys
from pathlib import Path

src_path = Path(__file__).resolve().parents[1]
src = str(src_path)
if src not in sys.path:
    sys.path.insert(0, src)

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
app = application
