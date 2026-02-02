import json
import os
import re
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from availability.models import Event, CustomHoliday

class Command(BaseCommand):
    help = 'Import legacy data from JSON files'

    def handle(self, *args, **kwargs):
        base_dir = settings.BASE_DIR.parent.parent # Navigate up from backend/settings.py
        # Actually BASE_DIR in settings.py is 'backend'. So parent is 'Availability Manager'. 
        
        # Let's verify the path logic.
        # settings.BASE_DIR is '.../Availability Manager/backend'
        # project root is '.../Availability Manager'
        # so project_root = settings.BASE_DIR.parent
        
        project_root = settings.BASE_DIR.parent
        
        events_path = os.path.join(project_root, 'events.json')
        holidays_path = os.path.join(project_root, 'custom_holidays.json')

        self.import_holidays(holidays_path)
        self.import_events(events_path)

    def import_holidays(self, path):
        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING(f"Holidays file not found at {path}"))
            return

        with open(path, 'r') as f:
            dates = json.load(f)
            
        count = 0
        for date_str in dates:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                _, created = CustomHoliday.objects.get_or_create(
                    date=date_obj,
                    defaults={'description': 'Imported Custom Holiday'}
                )
                if created:
                    count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error importing holiday {date_str}: {e}"))
        
        self.stdout.write(self.style.SUCCESS(f"Imported {count} holidays"))

    def import_events(self, path):
        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING(f"Events file not found at {path}"))
            return

        with open(path, 'r') as f:
            data = json.load(f)

        count = 0
        for date_str, events_list in data.items():
            for event_data in events_list:
                try:
                    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    
                    start_time = self._parse_time(event_data['start_time'])
                    end_time = self._parse_time(event_data['end_time'])
                    
                    Event.objects.get_or_create(
                        name=event_data['name'],
                        date=event_date,
                        start_time=start_time,
                        end_time=end_time,
                        timezone=event_data['timezone']
                    )
                    count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error importing event {event_data.get('name')}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Imported/Verified {count} events"))

    def _parse_time(self, time_str):
        # Logic adapted from original availabilityManager.py
        time_str = time_str.strip().upper()
        
        # Add missing space between time and AM/PM if needed
        time_str = re.sub(r'(\d)([AP]M)', r'\1 \2', time_str)
        
        # Handle cases like "11" -> "11 AM" (default logic from original script might differ but let's be robust)
        # Original: if time_str.replace(" ", "").isdigit(): hour = int(time_str); ...
        
        if time_str.replace(" ", "").isdigit():
            hour = int(time_str)
            time_str = f"{hour} {'PM' if 8 <= hour <= 11 else 'AM'}"
            
        try:
            return datetime.strptime(time_str, "%I:%M %p").time()
        except ValueError:
            try:
                return datetime.strptime(time_str, "%I %p").time()
            except ValueError:
                # Fallback or strict fail?
                # Original script had extensive fallback.
                pass
        
        # Try without space before AM/PM just in case regex didn't catch weird edge cases
        try:
            return datetime.strptime(time_str, "%I:%M%p").time()
        except ValueError:
            pass

        raise ValueError(f"Could not parse time: {time_str}")
