import os
import django
import sys

sys.path.append('/Users/richie/Downloads/VJCode/PythonProjects/Projects/Availability Manager/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'availability_project.settings')
django.setup()

from availability.models import UserSettings

try:
    settings = UserSettings.objects.get(id=1)
    print(f"Work Days: {settings.work_days} type: {type(settings.work_days)}")
    print(f"Work Start: {settings.work_start_time}")
    print(f"Work End: {settings.work_end_time}")
except UserSettings.DoesNotExist:
    print("UserSettings with id=1 does not exist")
