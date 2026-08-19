"""ASGI config for availability_project project."""

import os
import sys
from pathlib import Path

src_path = Path(__file__).resolve().parents[1]
src = str(src_path)
if src not in sys.path:
    sys.path.insert(0, src)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()
