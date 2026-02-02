
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from availability.models import Event, EventCategory

def run():
    cat, created = EventCategory.objects.get_or_create(
        name='Interview',
        defaults={'color': '#f59e0b', 'icon': 'briefcase'}
    )
    
    if not created:
        cat.icon = 'briefcase'
        cat.save()
        print(f"Updated category '{cat.name}' icon to 'briefcase'")
    else:
        print(f"Created category: {cat.name} with icon 'briefcase'")

    events = Event.objects.all()
    updated_count = events.update(category=cat)
    print(f"Updated {updated_count} events to be 'Interview' category.")

if __name__ == '__main__':
    run()
