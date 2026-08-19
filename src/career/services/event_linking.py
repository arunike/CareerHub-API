"""Suggest which application a calendar event belongs to."""

import re

INTERVIEW_STATUSES = {'ROUND_1', 'ROUND_2', 'ROUND_3', 'ROUND_4', 'FINAL_ROUND', 'ONSITE'}
DECIDED_STATUSES = {'ACCEPTED', 'OFFER', 'OFFER_REJECTED'}
# Below this the name is too generic to match on ("AI", "Eve") and would fire on prose.
MIN_COMPANY_NAME = 3


# "Google Meet" / "Microsoft Teams" name the meeting tool, not the employer. Without this
# guard "Wisk Google Meet Interview" links to Google.
PLATFORM_SUFFIXES = ('meet', 'teams', 'meets', 'hangout', 'hangouts')


def _followed_by_platform_word(text, end):
    tail = text[end:].lstrip()
    return any(
        tail.startswith(word) and (len(tail) == len(word) or not tail[len(word)].isalnum())
        for word in PLATFORM_SUFFIXES
    )


def _company_pattern(name):
    # Word boundaries that also treat digits as part of a word, so "A1" cannot match "A19".
    return re.compile(r'(?<![a-z0-9])' + re.escape(name.lower()) + r'(?![a-z0-9])')


def match_company(title, companies):
    """Return the (id, name) of the longest company name appearing in the title."""
    low = (title or '').lower()
    if not low:
        return None
    for company_id, name in companies:
        match = _company_pattern(name).search(low)
        if match and not _followed_by_platform_word(low, match.end()):
            return company_id, name
    return None


def build_company_index(companies):
    """Longest name first so "Sony Interactive" wins over "Sony"."""
    return sorted(
        ((cid, name) for cid, name in companies if name and len(name.strip()) >= MIN_COMPANY_NAME),
        key=lambda row: -len(row[1]),
    )


def pick_application(applications, event_date):
    """Choose among several applications at the same company."""
    if not applications:
        return None
    if len(applications) == 1:
        return applications[0]

    def sort_key(app):
        in_interview = app.status in INTERVIEW_STATUSES
        decided = app.status in DECIDED_STATUSES
        applied = app.date_applied
        # Applications submitted before the event, closest first.
        if applied and event_date and applied <= event_date:
            proximity = (event_date - applied).days
            before = 0
        else:
            proximity = 10**6
            before = 1
        return (not (in_interview or decided), before, proximity)

    return sorted(applications, key=sort_key)[0]


def confidence_for(company_name, candidate_count):
    """How much a suggestion should be trusted, for ordering the review list."""
    if candidate_count == 1:
        return 'high'
    if len(company_name) >= 6:
        return 'medium'
    return 'low'
