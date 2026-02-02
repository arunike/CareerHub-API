from datetime import datetime, timedelta, date, time
import pandas as pd
from django.http import HttpResponse, JsonResponse
import json
import io
import holidays
from .models import UserSettings, AvailabilityOverride, CustomHoliday, Event
from .recurrence import generate_recurring_instances

def get_next_two_weeks_weekdays(start_date=None):
    """Returns a list of dates for weekdays in the next 14 days."""
    if start_date is None:
        today = datetime.now().date()
    elif isinstance(start_date, datetime):
        today = start_date.date()
    else:
        today = start_date
        
    dates = []
    for i in range(14):
        d = today + timedelta(days=i)
        if d.weekday() < 5:  # Mon-Fri
            dates.append(d)
    return dates

def get_federal_holidays(year=None):
    """Returns a dictionary of federal holidays for the given year."""
    if year is None:
        year = datetime.now().year
    
    us_holidays = holidays.US(years=year)
    return dict(us_holidays)

def parse_time_str(t_str):
    """Parses HH:MM:SS or HH:MM or HH:MM AM/PM into a time object."""
    if not t_str: return None
    if isinstance(t_str, time): return t_str
    
    formats = ['%H:%M:%S', '%H:%M', '%I:%M %p']
    for fmt in formats:
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            continue
    return None

def subtract_intervals(base_start, base_end, intervals):
    """
    Subtracts a list of (start, end) intervals from a base [base_start, base_end] interval.
    Returns a list of available (start, end) tuples.
    All inputs must be datetime objects (or comparable).
    """
    available = [(base_start, base_end)]
    
    for remove_start, remove_end in sorted(intervals):
        new_available = []
        for avail_start, avail_end in available:
            # Case 1: Remove interval is completely outside (no overlap)
            if remove_end <= avail_start or remove_start >= avail_end:
                new_available.append((avail_start, avail_end))
            
            # Case 2: Remove interval overlaps partially or fully
            else:
                # Left side remaining
                if remove_start > avail_start:
                    new_available.append((avail_start, remove_start))
                
                # Right side remaining
                if remove_end < avail_end:
                    new_available.append((remove_end, avail_end))
        
        available = new_available
        if not available:
            break
            
    return available

def calculate_availability_for_dates(dates, timezone_str='America/Los_Angeles'):
    """
    Calculates availability strings for a list of dates based on UserSettings, Overrides, Holidays, and Events.
    """
    availability = {}
    if not dates: return availability

    # Normalize dates to list of datetime.date
    date_list = [d.date() if isinstance(d, datetime) else d for d in dates]
    start_date = min(date_list)
    end_date = max(date_list)

    # 1. Get UserSettings
    settings = UserSettings.objects.first()
    
    # Default Defaults
    work_start_time = time(9, 0)
    work_end_time = time(17, 0)
    work_days = [0, 1, 2, 3, 4] # Mon-Fri
    
    if settings:
        if settings.work_start_time: work_start_time = settings.work_start_time
        if settings.work_end_time: work_end_time = settings.work_end_time
        if settings.work_days: work_days = settings.work_days

    # 2. Pre-fetch Data
    
    # Overrides
    overrides = {
        o.date: o.availability_text 
        for o in AvailabilityOverride.objects.filter(date__range=[start_date, end_date])
    }
    
    # Custom Holidays
    custom_holidays = set(
        CustomHoliday.objects.filter(date__range=[start_date, end_date]).values_list('date', flat=True)
    )
    
    # Federal Holidays
    # Get years involved
    years = set(d.year for d in date_list)
    fed_holidays = {}
    for year in years:
        fed_holidays.update(holidays.US(years=year))
        
    # Events (Regular)
    # Note: timezone handling is simplified here. Ideally convert everything to UTC?
    # For now, assuming events are stored/compared in 'local' time relative to the user's primary timezone request.
    # Fetch events that overlap with the date range
    events = Event.objects.filter(
        date__range=[start_date, end_date],
        parent_event__isnull=True # Only parents or single events
    )
    
    # Recurring Instances
    # We need to generate instances for the range
    recurring_parents = Event.objects.filter(is_recurring=True, parent_event__isnull=True)
    generated_instances = []
    for p in recurring_parents:
        generated_instances.extend(generate_recurring_instances(p, start_date, end_date))

    # Organize events by date
    events_by_date = {d: [] for d in date_list}
    
    def add_to_map(evt_date, s_time, e_time):
        if evt_date in events_by_date:
            events_by_date[evt_date].append((s_time, e_time))

    for e in events:
        s = parse_time_str(e.start_time)
        e_t = parse_time_str(e.end_time)
        if s and e_t and not e.is_recurring: # Skip recurring parents, they are covered by instances? No, `events` query includes non-recurring.
             add_to_map(e.date, s, e_t)
             
    for inst in generated_instances:
        # dict format
        s = parse_time_str(inst['start_time'])
        e_t = parse_time_str(inst['end_time'])
        if s and e_t:
            add_to_map(inst['date'], s, e_t)

    # 3. Calculation Loop
    for d in date_list:
        date_str = d.strftime('%Y-%m-%d')
        
        # Priority 1: Override
        if d in overrides:
            text = overrides[d]
            
        # Priority 2: Holiday
        elif d in fed_holidays or d in custom_holidays:
            text = "Unavailable"
            
        # Priority 3: Non-Work Day
        elif d.weekday() not in work_days:
            text = "Unavailable"
            
        # Priority 4: Calculate Slots
        else:
            # Base availability: User's work hours
            # Combine with date to make datetime objects for subtraction logic
            base_start = datetime.combine(d, work_start_time)
            base_end = datetime.combine(d, work_end_time)
            
            day_conflicts = []
            if d in events_by_date:
                for s, e in events_by_date[d]:
                    c_start = datetime.combine(d, s)
                    c_end = datetime.combine(d, e)
                    day_conflicts.append((c_start, c_end))
            
            available_slots = subtract_intervals(base_start, base_end, day_conflicts)
            
            if not available_slots:
                text = "Unavailable"
            else:
                # Format slots
                parts = []
                for s_dt, e_dt in available_slots:
                    # Check if slot is significant (e.g. > 15 mins)
                    if (e_dt - s_dt).total_seconds() >= 900: 
                        parts.append(f"{s_dt.strftime('%-I:%M %p')} - {e_dt.strftime('%-I:%M %p')}")
                
                text = ", ".join(parts) if parts else "Unavailable"

        # Only include if there is actual availability
        if text != "Unavailable":
            availability[date_str] = {
                'date': date_str,
                'day_name': d.strftime('%A'),
                'readable_date': d.strftime('%b %d'),
                'availability': text
            }
        
    return availability

def export_data(queryset, serializer_class, export_format='csv', filename='export'):
    """
    Exports queryset data to CSV, Excel, or JSON.
    """
    serializer = serializer_class(queryset, many=True)
    data = serializer.data
    
    # If data is empty, handle gracefully or return empty file
    if not data:
        df = pd.DataFrame()
    else:
        # Convert to DataFrame
        # Flatten nested data if necessary, or just rely on serializer structure
        # For simplicity, we assume serializer data is flat enough or we handle objects
        df = pd.DataFrame(data)

    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        df.to_csv(path_or_buf=response, index=False)
        return response

    elif export_format == 'xlsx' or export_format == 'excel':
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        # Write to buffer
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Sheet1')
            response.write(buffer.getvalue())
        return response

    elif export_format == 'json':
        response = HttpResponse(content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{filename}.json"'
        # Use json.dump with ensure_ascii=False for proper encoding
        response.write(json.dumps(data, indent=2, default=str)) 
        return response

    else:
        return JsonResponse({'error': 'Invalid format. Supported: csv, xlsx, json'}, status=400)
