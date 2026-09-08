from collections import defaultdict
from urllib.parse import urlparse

# Matching application_stats keeps the two dashboards from disagreeing on the same application.
NO_RESPONSE_STATUSES = {'APPLIED', 'GHOSTED', 'REMOVED_FROM_SHEET'}
INTERVIEW_STAGES = {'ROUND_1', 'ROUND_2', 'ROUND_3', 'ROUND_4', 'FINAL_ROUND', 'ONSITE'}
OFFER_STAGES = {'OFFER', 'ACCEPTED', 'OFFER_REJECTED'}

# Below this, a rate is one or two applications wearing a percentage sign.
MINIMUM_SAMPLE_SIZE = 5

EMPLOYMENT_TYPE_LABELS = {
    'full_time': 'Full-time',
    'part_time': 'Part-time',
    'internship': 'Internship',
    'contract': 'Contract',
    'freelance': 'Freelance',
}

# Host suffix to name, so a board is counted once however the URL was built.
JOB_BOARD_NAMES = (
    ('linkedin.com', 'LinkedIn'),
    ('indeed.com', 'Indeed'),
    ('greenhouse.io', 'Greenhouse'),
    ('lever.co', 'Lever'),
    ('ashbyhq.com', 'Ashby'),
    ('myworkdayjobs.com', 'Workday'),
    ('workday.com', 'Workday'),
    ('smartrecruiters.com', 'SmartRecruiters'),
    ('icims.com', 'iCIMS'),
    ('taleo.net', 'Taleo'),
    ('glassdoor.com', 'Glassdoor'),
    ('wellfound.com', 'Wellfound'),
    ('angel.co', 'Wellfound'),
    ('otta.com', 'Otta'),
    ('hire.google.com', 'Google Hire'),
)


def _rate(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0


def source_label(job_link):
    """Where the application came from, read off the job link rather than asked for."""
    host = urlparse((job_link or '').strip()).netloc.lower()
    if not host:
        return 'No link'
    if host.startswith('www.'):
        host = host[4:]
    for suffix, name in JOB_BOARD_NAMES:
        if host == suffix or host.endswith(f'.{suffix}'):
            return name
    return 'Company site' if host else 'No link'


def role_type_label(employment_type):
    key = (employment_type or '').strip().lower()
    return EMPLOYMENT_TYPE_LABELS.get(key, 'Unspecified')


class _Tally:
    """Counts for one group, kept as a class so every breakdown reports the same shape."""

    def __init__(self):
        self.applications = 0
        self.responded = 0
        self.interviewed = 0
        self.offers = 0

    def add(self, responded, interviewed, offered):
        self.applications += 1
        self.responded += 1 if responded else 0
        self.interviewed += 1 if interviewed else 0
        self.offers += 1 if offered else 0

    def as_dict(self, **extra):
        return {
            'applications': self.applications,
            'responded': self.responded,
            'interviewed': self.interviewed,
            'offers': self.offers,
            'response_rate': _rate(self.responded, self.applications),
            'interview_rate': _rate(self.interviewed, self.applications),
            'offer_rate': _rate(self.offers, self.applications),
            'below_minimum_sample': self.applications < MINIMUM_SAMPLE_SIZE,
            **extra,
        }


def _outcome(status, timeline_stages):
    """Furthest point reached, from the current status or any stage the timeline recorded."""
    status = (status or '').upper()
    reached = timeline_stages | {status}
    offered = bool(reached & OFFER_STAGES)
    # An offer implies the interviews that produced it, recorded or not.
    interviewed = offered or bool(reached & INTERVIEW_STAGES)
    responded = interviewed or status not in NO_RESPONSE_STATUSES
    return responded, interviewed, offered


def _breakdown(groups):
    return [
        group.as_dict(key=key, label=label)
        for (key, label), group in sorted(
            groups.items(), key=lambda item: (-item[1].applications, item[0][1])
        )
    ]


def build_resume_version_analytics(user, year=None):
    """How each submitted resume version actually performed, from records already kept."""
    from ..models import Application, ApplicationTimelineEntry

    applications = Application.objects.filter(user=user)
    if year:
        applications = applications.filter(date_applied__year=year)
    applications = applications.prefetch_related('submitted_documents').only(
        'id', 'status', 'employment_type', 'job_link', 'date_applied'
    )

    stages_by_application = defaultdict(set)
    for application_id, stage in ApplicationTimelineEntry.objects.filter(
        user=user, deleted_by_user_at__isnull=True
    ).values_list('application_id', 'stage'):
        stages_by_application[application_id].add((stage or '').upper())

    totals = _Tally()
    versions = {}
    role_types = defaultdict(lambda: defaultdict(_Tally))
    sources = defaultdict(lambda: defaultdict(_Tally))
    used_on = defaultdict(list)
    tracked_application_ids = set()

    for application in applications:
        responded, interviewed, offered = _outcome(
            application.status, stages_by_application.get(application.id, set())
        )
        totals.add(responded, interviewed, offered)

        resumes = [
            document
            for document in application.submitted_documents.all()
            if document.document_type == 'RESUME'
        ]
        if not resumes:
            continue
        tracked_application_ids.add(application.id)

        role = (application.employment_type, role_type_label(application.employment_type))
        source = (source_label(application.job_link), source_label(application.job_link))
        for document in resumes:
            if document.id not in versions:
                versions[document.id] = (document, _Tally())
            versions[document.id][1].add(responded, interviewed, offered)
            role_types[document.id][role].add(responded, interviewed, offered)
            sources[document.id][source].add(responded, interviewed, offered)
            if application.date_applied:
                used_on[document.id].append(application.date_applied)

    rows = []
    for document_id, (document, tally) in versions.items():
        dates = sorted(used_on[document_id])
        rows.append(
            tally.as_dict(
                document_id=document_id,
                root_id=document.root_document_id or document.id,
                title=document.title,
                version_number=document.version_number,
                label=f'{document.title} · v{document.version_number}',
                is_current=document.is_current,
                first_used=dates[0].isoformat() if dates else None,
                last_used=dates[-1].isoformat() if dates else None,
                by_role_type=_breakdown(role_types[document_id]),
                by_source=_breakdown(sources[document_id]),
            )
        )

    # Most-used first: the version with the evidence behind it is the one worth reading.
    rows.sort(key=lambda row: (-row['applications'], row['label']))

    return {
        'minimum_sample_size': MINIMUM_SAMPLE_SIZE,
        'versions': rows,
        'total_applications': totals.applications,
        'tracked_applications': len(tracked_application_ids),
        'untracked_applications': totals.applications - len(tracked_application_ids),
        'overall': totals.as_dict(),
    }
