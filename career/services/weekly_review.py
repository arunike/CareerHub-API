from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date

from availability.models import Event

from ..models import Application, Task


def is_interview_event(event: Event) -> bool:
    category_name = (event.category.name if event.category else '').lower()
    event_name = (event.name or '').lower()
    keywords = ('interview', 'onsite', 'screen', 'recruiter', 'recruiting', 'oa', 'assessment')
    return any(word in category_name for word in keywords) or any(word in event_name for word in keywords)


def build_weekly_review_payload(start_date_raw: str | None, end_date_raw: str | None):
    today = timezone.localdate()
    default_start = today - timedelta(days=6)
    default_end = today

    start_date = parse_date(start_date_raw or '') or default_start
    end_date = parse_date(end_date_raw or '') or default_end
    if start_date > end_date:
        return None, {'error': 'start_date must be on or before end_date'}

    applications = (
        Application.objects.filter(
            date_applied__isnull=False,
            date_applied__gte=start_date,
            date_applied__lte=end_date,
        )
        .select_related('company')
        .order_by('-date_applied', '-id')
    )
    applications_sent = applications.count()
    application_items = [
        {
            'id': app.id,
            'company': app.company.name,
            'role_title': app.role_title,
            'date_applied': app.date_applied,
            'status': app.status,
        }
        for app in applications[:10]
    ]

    week_events = Event.objects.filter(date__gte=start_date, date__lte=end_date).select_related(
        'category',
        'application',
        'application__company',
    )
    interview_events = [event for event in week_events if is_interview_event(event)]
    interviews_done = len(interview_events)
    interview_items = [
        {
            'id': event.id,
            'name': event.name,
            'date': event.date,
            'company': event.application.company.name if event.application else None,
            'role_title': event.application.role_title if event.application else None,
        }
        for event in sorted(interview_events, key=lambda e: (e.date, e.start_time), reverse=True)[:10]
    ]

    next_week_end = today + timedelta(days=7)
    next_actions_qs = Task.objects.filter(status__in=['TODO', 'IN_PROGRESS']).order_by(
        'due_date',
        'priority',
        'position',
    )
    next_actions_items = []
    for task in next_actions_qs:
        due = task.due_date
        if due and due > next_week_end:
            continue
        next_actions_items.append(
            {
                'id': task.id,
                'title': task.title,
                'status': task.status,
                'priority': task.priority,
                'due_date': task.due_date,
                'is_overdue': bool(task.due_date and task.due_date < today),
            }
        )
        if len(next_actions_items) >= 8:
            break

    interviews_word = 'interview' if interviews_done == 1 else 'interviews'
    applications_word = 'application' if applications_sent == 1 else 'applications'
    summary_lines = [
        f'Week {start_date} to {end_date}: sent {applications_sent} {applications_word} and completed {interviews_done} {interviews_word}.',
    ]
    if next_actions_items:
        top_action_phrases = []
        for item in next_actions_items[:3]:
            due_suffix = f" (due {item['due_date']})" if item['due_date'] else ''
            top_action_phrases.append(f"{item['title']}{due_suffix}")
        summary_lines.append('Top next actions: ' + '; '.join(top_action_phrases) + '.')
    else:
        summary_lines.append('No pending action items right now.')

    payload = {
        'start_date': start_date,
        'end_date': end_date,
        'applications_sent': applications_sent,
        'interviews_done': interviews_done,
        'next_actions_count': len(next_actions_items),
        'applications': application_items,
        'interviews': interview_items,
        'next_actions': next_actions_items,
        'summary_text': ' '.join(summary_lines),
        'generated_at': timezone.now(),
    }
    return payload, None
