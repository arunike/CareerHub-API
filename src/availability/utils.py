from datetime import datetime, timedelta, date, time, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import pandas as pd
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
import json
import io
import holidays
from .models import UserSettings, AvailabilityOverride, CustomHoliday, Event
from .holiday_recurrence import project_recurring_holiday_dates
from .recurrence import generate_recurring_instances

def get_availability_dates(start_date=None, weeks=2):
    if start_date is None:
        today = datetime.now().date()
    elif isinstance(start_date, datetime):
        today = start_date.date()
    else:
        today = start_date

    try:
        week_count = max(1, int(weeks))
    except (TypeError, ValueError):
        week_count = 2

    return [today + timedelta(days=i) for i in range(week_count * 7)]


def get_next_two_weeks_weekdays(start_date=None):
    return [d for d in get_availability_dates(start_date, weeks=2) if d.weekday() < 5]

def get_custom_us_holidays(year):
    us_hols = dict(holidays.US(years=year))
    
    # Rename Washington's Birthday to Presidents’ Day
    updated_hols = {}
    for d, name in us_hols.items():
        if name == "Washington's Birthday":
            updated_hols[d] = "Presidents’ Day"
        else:
            updated_hols[d] = name
            
    import calendar
    weeks = calendar.monthcalendar(year, 11)
    thursdays = [week[calendar.THURSDAY] for week in weeks if week[calendar.THURSDAY] != 0]
    thanksgiving_day = thursdays[3]
    black_friday_date = date(year, 11, thanksgiving_day) + timedelta(days=1)
    updated_hols[black_friday_date] = "Black Friday"
    
    updated_hols[date(year, 12, 24)] = "Christmas Eve"
    
    updated_hols[date(year, 12, 31)] = "New Year's Eve"
    
    return updated_hols

def get_federal_holidays(year=None):
    if year is None:
        year = datetime.now().year
    return get_custom_us_holidays(year)


def parse_time_str(t_str):
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
    available = [(base_start, base_end)]
    
    for remove_start, remove_end in sorted(intervals):
        new_available = []
        for avail_start, avail_end in available:
            if remove_end <= avail_start or remove_start >= avail_end:
                new_available.append((avail_start, avail_end))
            
            else:
                if remove_start > avail_start:
                    new_available.append((avail_start, remove_start))
                
                if remove_end < avail_end:
                    new_available.append((remove_end, avail_end))
        
        available = new_available
        if not available:
            break
            
    return available


def format_availability_time(dt):
    return dt.strftime('%-I:%M %p')


def next_availability_boundary(dt):
    minute = 30 if dt.minute < 30 else 60
    boundary = dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    return boundary.replace(tzinfo=None)


def filter_expired_availability_text(availability_text, availability_date, timezone_str):
    if not availability_text or availability_text == "Unavailable":
        return availability_text

    try:
        target_tz = ZoneInfo(timezone_str)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        target_tz = ZoneInfo("America/Los_Angeles")

    now = timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, dt_timezone.utc)
    local_now = now.astimezone(target_tz)

    if availability_date < local_now.date():
        return "Unavailable"

    if availability_date > local_now.date():
        return availability_text

    future_parts = []
    parts = [part.strip() for part in str(availability_text).split(',') if part.strip()]
    for part in parts:
        if ' - ' not in part:
            future_parts.append(part)
            continue

        start_str, end_str = [item.strip() for item in part.split(' - ', 1)]
        start_time = parse_time_str(start_str)
        end_time = parse_time_str(end_str)
        if not start_time or not end_time:
            future_parts.append(part)
            continue

        start_dt = datetime.combine(availability_date, start_time)
        end_dt = datetime.combine(availability_date, end_time)
        local_now_naive = local_now.replace(tzinfo=None)

        if end_dt <= local_now_naive:
            continue

        if start_dt <= local_now_naive:
            start_dt = next_availability_boundary(local_now)

        if start_dt < end_dt:
            future_parts.append(f"{format_availability_time(start_dt)} - {format_availability_time(end_dt)}")

    return ", ".join(future_parts) if future_parts else "Unavailable"


def get_work_time_ranges_for_day(settings, weekday, work_start_time, work_end_time):
    if not settings or not settings.work_time_ranges:
        return [(work_start_time, work_end_time)]

    day_ranges = []
    for r in settings.work_time_ranges:
        days = r.get('days')
        if days is not None and weekday not in days:
            continue

        start_time = parse_time_str(r.get('start', ''))
        end_time = parse_time_str(r.get('end', ''))
        if start_time and end_time and start_time < end_time:
            day_ranges.append((start_time, end_time))

    return day_ranges


def format_availability_range(start_dt, end_dt):
    return f"{format_availability_time(start_dt)} - {format_availability_time(end_dt)}"

def calculate_availability_for_dates(dates, timezone_str='America/Los_Angeles', user=None):
    availability = {}
    if not dates: return availability

    date_list = [d.date() if isinstance(d, datetime) else d for d in dates]
    start_date = min(date_list)
    end_date = max(date_list)

    settings = UserSettings.objects.filter(user=user).first() if user else None
    
    work_start_time = time(9, 0)
    work_end_time = time(17, 0)
    work_days = [0, 1, 2, 3, 4] # Mon-Fri
    
    if settings:
        if settings.work_start_time: work_start_time = settings.work_start_time
        if settings.work_end_time: work_end_time = settings.work_end_time
        if settings.work_days: work_days = settings.work_days

    overrides = {
        o.date: o.availability_text 
        for o in AvailabilityOverride.objects.filter(user=user, date__range=[start_date, end_date])
    }
    
    years = set(d.year for d in date_list)
    custom_holidays = set(
        CustomHoliday.objects.filter(
            user=user,
            is_recurring=False,
            date__range=[start_date, end_date],
        ).values_list('date', flat=True)
    )
    recurring_holidays = list(
        CustomHoliday.objects.filter(user=user, is_recurring=True)
    )
    for year in years:
        projected_dates = project_recurring_holiday_dates(recurring_holidays, year)
        custom_holidays.update(
            projected_date
            for projected_date in projected_dates.values()
            if start_date <= projected_date <= end_date
        )

    fed_holidays = {}
    for year in years:
        fed_holidays.update(get_custom_us_holidays(year))
        
    events = Event.objects.filter(
        user=user,
        date__range=[start_date, end_date],
        parent_event__isnull=True
    )
    
    recurring_parents = Event.objects.filter(user=user, is_recurring=True, parent_event__isnull=True)
    generated_instances = []
    for p in recurring_parents:
        generated_instances.extend(generate_recurring_instances(p, start_date, end_date))

    events_by_date = {d: [] for d in date_list}
    
    def add_to_map(evt_date, s_time, e_time):
        if evt_date in events_by_date:
            events_by_date[evt_date].append((s_time, e_time))

    for e in events:
        s = parse_time_str(e.start_time)
        e_t = parse_time_str(e.end_time)
        if s and e_t and not e.is_recurring:
            add_to_map(e.date, s, e_t)

    for inst in generated_instances:
        s = parse_time_str(inst['start_time'])
        e_t = parse_time_str(inst['end_time'])
        if s and e_t:
            add_to_map(inst['date'], s, e_t)

    for d in date_list:
        date_str = d.strftime('%Y-%m-%d')
        
        if d in overrides:
            text = overrides[d]
            
        elif d in fed_holidays or d in custom_holidays:
            text = "Unavailable"
            
        elif d.weekday() not in work_days:
            text = "Unavailable"
            
        else:
            day_conflicts = []
            if d in events_by_date:
                for s, e in events_by_date[d]:
                    c_start = datetime.combine(d, s)
                    c_end = datetime.combine(d, e)
                    day_conflicts.append((c_start, c_end))

            ranges = get_work_time_ranges_for_day(settings, d.weekday(), work_start_time, work_end_time)

            all_slots = []
            for rng_start, rng_end in ranges:
                base_start = datetime.combine(d, rng_start)
                base_end = datetime.combine(d, rng_end)
                all_slots.extend(subtract_intervals(base_start, base_end, day_conflicts))

            if not all_slots:
                text = "Unavailable"
            else:
                parts = []
                for s_dt, e_dt in sorted(all_slots):
                    if (e_dt - s_dt).total_seconds() >= 900:
                        parts.append(format_availability_range(s_dt, e_dt))

                text = ", ".join(parts) if parts else "Unavailable"

        text = filter_expired_availability_text(text, d, timezone_str)

        if text != "Unavailable":
            availability[date_str] = {
                'date': date_str,
                'day_name': d.strftime('%A'),
                'readable_date': d.strftime('%b %d'),
                'availability': text
            }
        
    return availability

def export_data(queryset, serializer_class, export_format='csv', filename='export'):
    serializer = serializer_class(queryset, many=True)
    data = serializer.data
    
    if not data:
        df = pd.DataFrame()
    else:
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
        
        response.write(json.dumps(data, indent=2, default=str)) 
        return response

    else:
        return JsonResponse({'error': 'Invalid format. Supported: csv, xlsx, json'}, status=400)
