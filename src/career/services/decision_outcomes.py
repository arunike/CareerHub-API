from collections import defaultdict

from ..models import CRITERION_VERDICTS, DECISION_CRITERIA

# One reviewed decision proves nothing about a pattern; this is the floor for claiming one.
MINIMUM_DECISIONS_FOR_PATTERN = 3

CRITERION_LABELS = {
    'financial': 'Financial',
    'benefits': 'Benefits',
    'workLife': 'Work-life balance',
    'trajectory': 'Trajectory',
    'location': 'Location',
    'brand': 'Brand',
    'visa': 'Immigration',
}


def _completed_reviews(journal):
    """Only a finished look-back is evidence; a half-typed one is not an outcome."""
    reviews = journal.reviews if isinstance(journal.reviews, list) else []
    return [
        review
        for review in reviews
        if isinstance(review, dict) and review.get('completed_on')
    ]


def _latest_verdicts(journal):
    """The last word per criterion: a 90-day view supersedes the 30-day one it revisits."""
    verdicts = {}
    for review in sorted(_completed_reviews(journal), key=lambda item: item.get('milestone') or 0):
        for key, verdict in (review.get('criteria_verdicts') or {}).items():
            if key in DECISION_CRITERIA and verdict in CRITERION_VERDICTS:
                verdicts[key] = verdict
    return verdicts


def _label(journal):
    application = journal.offer.application
    company = getattr(getattr(application, 'company', None), 'name', '')
    return company or application.custom_company_name or 'An offer'


def build_decision_outcome_insights(user):
    """What the 30/90 day look-backs say about how these calls are actually being made."""
    from ..models import OfferDecisionJournal

    journals = list(
        OfferDecisionJournal.objects.filter(offer__application__user=user).select_related(
            'offer', 'offer__application', 'offer__application__company'
        )
    )

    reviewed = [journal for journal in journals if _completed_reviews(journal)]

    concerns_raised = 0
    concerns_resolved = 0
    realised_concerns = []
    for journal in journals:
        entries = journal.concerns if isinstance(journal.concerns, list) else []
        for concern in entries:
            if not isinstance(concern, dict):
                continue
            concerns_raised += 1
            outcome = concern.get('outcome')
            if outcome in ('REAL', 'AVOIDED'):
                concerns_resolved += 1
            if outcome == 'REAL':
                realised_concerns.append(
                    {
                        'journal_id': journal.id,
                        'company_name': _label(journal),
                        'decision': journal.decision,
                        'decided_on': journal.decided_on.isoformat(),
                        'text': concern.get('text') or '',
                    }
                )

    # Per criterion: how often it drove a call, and how those calls actually turned out.
    chosen = defaultdict(int)
    verdict_counts = defaultdict(lambda: defaultdict(int))
    for journal in journals:
        criteria = journal.criteria if isinstance(journal.criteria, list) else []
        for key in criteria:
            if key in DECISION_CRITERIA:
                chosen[key] += 1
        for key, verdict in _latest_verdicts(journal).items():
            verdict_counts[key][verdict] += 1

    criteria_rows = []
    for key in DECISION_CRITERIA:
        counts = verdict_counts[key]
        judged = sum(counts.values())
        if not chosen[key] and not judged:
            continue
        criteria_rows.append(
            {
                'key': key,
                'label': CRITERION_LABELS[key],
                'chosen_count': chosen[key],
                'judged_count': judged,
                'better': counts.get('BETTER', 0),
                'as_expected': counts.get('AS_EXPECTED', 0),
                'worse': counts.get('WORSE', 0),
                'below_minimum_sample': judged < MINIMUM_DECISIONS_FOR_PATTERN,
            }
        )
    criteria_rows.sort(key=lambda row: (-row['chosen_count'], -row['judged_count'], row['label']))

    return {
        'minimum_decisions_for_pattern': MINIMUM_DECISIONS_FOR_PATTERN,
        'journal_count': len(journals),
        'reviewed_count': len(reviewed),
        'concerns_raised': concerns_raised,
        'concerns_resolved': concerns_resolved,
        'concerns_became_real': realised_concerns,
        'criteria': criteria_rows,
    }
