from datetime import datetime, timedelta, date
import pytz
from django.utils import timezone as django_timezone
from .models import Event, ConflictAlert

# Standard Timezone Mapping
TZ_MAPPING = {
    'PT': 'America/Los_Angeles',
    'MT': 'America/Denver',
    'CT': 'America/Chicago',
    'ET': 'America/New_York',
    'UTC': 'UTC'
}

def parse_time(time_str):
    if isinstance(time_str, str):
        # Try HH:MM:SS
        try:
            return datetime.strptime(time_str, '%H:%M:%S').time()
        except ValueError:
            pass
            
        # Try HH:MM
        try:
            return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            pass
            
        # Try with AM/PM just in case (e.g. 1:00 PM)
        try:
            return datetime.strptime(time_str, '%I:%M %p').time()
        except ValueError:
            return None
            
    return time_str

def get_event_datetime_range(event_data):
    """
    Convert event data (date, start_time, end_time, timezone) into 
    timezone-aware start and end datetime objects in UTC.
    """
    def get_val(obj, attr):
        if isinstance(obj, dict):
            return obj.get(attr)
        return getattr(obj, attr, None)

    d = get_val(event_data, 'date')
    s_time = get_val(event_data, 'start_time')
    e_time = get_val(event_data, 'end_time')
    tz_code = get_val(event_data, 'timezone') or 'PT'

    # Ensure we have valid objects
    if isinstance(s_time, str): s_time = parse_time(s_time)
    if isinstance(e_time, str): e_time = parse_time(e_time)
    if isinstance(d, str): d = datetime.strptime(d, '%Y-%m-%d').date()
    
    if not (d and s_time and e_time):
        return None, None

    # Get PyTZ timezone object
    tz_name = TZ_MAPPING.get(tz_code, 'America/Los_Angeles')
    local_tz = pytz.timezone(tz_name)

    # Combine to naive datetime
    start_dt_naive = datetime.combine(d, s_time)
    end_dt_naive = datetime.combine(d, e_time)

    # Handle overnight events (end time < start time)
    if end_dt_naive <= start_dt_naive:
        end_dt_naive += timedelta(days=1)

    # Localize
    start_dt_aware = local_tz.localize(start_dt_naive)
    end_dt_aware = local_tz.localize(end_dt_naive)

    # Convert to UTC for comparison
    return start_dt_aware.astimezone(pytz.UTC), end_dt_aware.astimezone(pytz.UTC)

def events_overlap(event1, event2):
    """
    Check if two events overlap, respecting their timezones.
    """
    start1, end1 = get_event_datetime_range(event1)
    start2, end2 = get_event_datetime_range(event2)

    if not (start1 and end1 and start2 and end2):
        return False

    # Check for overlap: (Start1 < End2) and (Start2 < End1)
    return start1 < end2 and start2 < end1

def detect_conflicts_for_event(event):
    # Optimizing: Only fetch events in a relevant date window?
    # Since timezones shift, an event on Day X in PT might overlap with Day X+1 in UTC or Day X-1.
    # We'll broaden the search window slightly (-1 to +1 day) around the event date.
    
    target_date = event.date
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        
    start_window = target_date - timedelta(days=1)
    end_window = target_date + timedelta(days=1)
    
    # Fetch potential candidates
    candidate_events = Event.objects.filter(
        date__range=[start_window, end_window]
    ).exclude(id=event.id)
    
    conflicts = []
    for other_event in candidate_events:
        if events_overlap(event, other_event):
            conflicts.append(other_event)
    
    return conflicts

def check_for_conflicts(data, exclude_id=None):
    """Check if the proposed event data conflicts with existing events."""
    # Similar window logic as above
    d = data.get('date')
    if not d: return []
    
    if isinstance(d, str):
        target_date = datetime.strptime(d, '%Y-%m-%d').date()
    else:
        target_date = d

    start_window = target_date - timedelta(days=1)
    end_window = target_date + timedelta(days=1)

    candidate_events = Event.objects.filter(date__range=[start_window, end_window])
    if exclude_id:
        candidate_events = candidate_events.exclude(id=exclude_id)
        
    conflicts = []
    for other_event in candidate_events:
        if events_overlap(data, other_event):
            conflicts.append(other_event)
            
    return conflicts

def detect_all_conflicts():
    # Clear old unresolved conflicts
    ConflictAlert.objects.filter(resolved=False).delete()
    
    all_events = Event.objects.all().order_by('date', 'start_time')
    conflicts_created = 0
    checked_pairs = set()
    
    for event in all_events:
        # Re-use the optimized single event detector
        conflicts = detect_conflicts_for_event(event)
        
        for conflicting_event in conflicts:
            # Create a unique pair identifier (smaller id first)
            p1, p2 = sorted([event.id, conflicting_event.id])
            pair = (p1, p2)
            
            if pair not in checked_pairs:
                ConflictAlert.objects.create(
                    event1_id=p1,
                    event2_id=p2
                )
                checked_pairs.add(pair)
                conflicts_created += 1
    
    return conflicts_created

def get_upcoming_events(days_ahead=7):
    today = datetime.now().date()
    end_date = today + timedelta(days=days_ahead)
    
    return Event.objects.filter(
        date__gte=today,
        date__lte=end_date
    ).order_by('date', 'start_time')
