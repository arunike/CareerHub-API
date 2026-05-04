import os
import sys
from pathlib import Path

src_path = Path(__file__).resolve().parents[1] / "src"
src = str(src_path)
if src not in sys.path:
    sys.path.insert(0, src)

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = get_wsgi_application()
application = app
