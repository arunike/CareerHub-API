from datetime import datetime, timedelta
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY
from .models import Event

def parse_recurrence_rule(rule_dict):
    freq_map = {
        'daily': DAILY,
        'weekly': WEEKLY,
        'monthly': MONTHLY,
        'yearly': YEARLY,
    }
    
    freq = freq_map.get(rule_dict.get('frequency', 'weekly'), WEEKLY)
    interval = rule_dict.get('interval', 1)
    count = rule_dict.get('count')
    until_str = rule_dict.get('until')
    byweekday = rule_dict.get('byweekday')
    
    kwargs = {
        'freq': freq,
        'interval': interval,
    }
    
    if count:
        kwargs['count'] = count
    elif until_str:
        kwargs['until'] = datetime.strptime(until_str, '%Y-%m-%d')
    
    if byweekday and freq == WEEKLY:
        kwargs['byweekday'] = byweekday
    
    return kwargs

def generate_recurring_instances(parent_event, start_date, end_date):
    if not parent_event.is_recurring or not parent_event.recurrence_rule:
        return []
    
    rule_kwargs = parse_recurrence_rule(parent_event.recurrence_rule)
    
    # Start from the parent event's date
    dtstart = datetime.strptime(parent_event.date, '%Y-%m-%d') if isinstance(parent_event.date, str) else parent_event.date
    
    # Generate occurrences
    rule = rrule(dtstart=dtstart, **rule_kwargs)
    
    # Get excluded dates set for O(1) lookup
    excluded_dates = set()
    if parent_event.recurrence_rule.get('excluded_dates'):
        for d_str in parent_event.recurrence_rule['excluded_dates']:
            try:
                excluded_dates.add(datetime.strptime(d_str, '%Y-%m-%d').date())
            except ValueError:
                pass

    instances = []
    for occurrence_date in rule:
        occ_date = occurrence_date.date()
        
        # Skip if excluded
        if occ_date in excluded_dates:
            continue
            
        # Only include dates within the requested range
        if start_date <= occ_date <= end_date:
            instances.append({
                'name': parent_event.name,
                'date': occ_date,
                'start_time': parent_event.start_time,
                'end_time': parent_event.end_time,
                'timezone': parent_event.timezone,
                'category': parent_event.category_id if parent_event.category else None,
                'location_type': parent_event.location_type,
                'location': parent_event.location,
                'meeting_link': parent_event.meeting_link,
                'notes': parent_event.notes,
                'parent_event_id': parent_event.id,
                'is_recurring': False,  # Instances are not recurring themselves
            })
    
    return instances

def update_recurring_series(parent_event, updates):
    # Update the parent event
    for key, value in updates.items():
        if hasattr(parent_event, key):
            setattr(parent_event, key, value)
    parent_event.save()
    
    # Update all child instances that haven't occurred yet
    today = datetime.now().date()
    instances = Event.objects.filter(parent_event=parent_event, date__gte=today)
    
    count = instances.update(**updates)
    return count + 1  # +1 for parent

def delete_recurring_series(parent_event):
    # Delete all instances
    count = Event.objects.filter(parent_event=parent_event).delete()[0]
    
    # Delete parent
    parent_event.delete()
    
    return count + 1
