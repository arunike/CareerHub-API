from career.models import GoogleSheetSyncConfig


APPLICATION_DEFAULT_MAPPING = {
    'external_id': 'External ID',
    'company_name': 'Company',
    'role_title': 'Role',
    'status': 'Status',
    'job_link': 'Job Link',
    'salary_range': 'Salary',
    'location': 'Location',
    'office_location': 'Office Location',
    'date_applied': 'Date Applied',
    'notes': 'Notes',
}


EVENT_DEFAULT_MAPPING = {
    'external_id': 'External ID',
    'name': 'Name',
    'date': 'Date',
    'start_time': 'Start Time',
    'end_time': 'End Time',
    'timezone': 'Timezone',
    'location_type': 'Location Type',
    'location': 'Location',
    'meeting_link': 'Meeting Link',
    'category': 'Category',
    'notes': 'Notes',
}


DEFAULT_APPLICATION_STAGES = [
    {'key': 'APPLIED', 'label': 'Applied', 'shortLabel': 'Apply', 'tone': '#DCEBFF'},
    {'key': 'ROUND_1', 'label': '1st Round', 'shortLabel': 'R1', 'tone': '#A9CCFF'},
    {'key': 'ROUND_2', 'label': '2nd Round', 'shortLabel': 'R2', 'tone': '#6EA8FE'},
    {'key': 'ROUND_3', 'label': '3rd Round', 'shortLabel': 'R3', 'tone': '#7B8CDE'},
    {'key': 'ROUND_4', 'label': '4th Round', 'shortLabel': 'R4', 'tone': '#9B7EDE'},
    {'key': 'FINAL_ROUND', 'label': 'Final Round', 'shortLabel': 'Final', 'tone': '#6F42C1'},
    {'key': 'ONSITE', 'label': 'Onsite Interview', 'shortLabel': 'Onsite', 'tone': '#20B2AA'},
    {'key': 'OFFER', 'label': 'Offer', 'shortLabel': 'Offer', 'tone': '#34A853'},
    {'key': 'REJECTED', 'label': 'Rejected', 'shortLabel': 'Reject', 'tone': '#E85D5D'},
    {'key': 'GHOSTED', 'label': 'Ghosted', 'shortLabel': 'Ghost', 'tone': '#9AA0A6'},
    {'key': 'REMOVED_FROM_SHEET', 'label': 'Removed', 'shortLabel': 'Removed', 'tone': '#5F6368'},
]


REMOVED_FROM_SHEET_STATUS = 'REMOVED_FROM_SHEET'


REMOVED_FROM_SHEET_STAGE = {
    'key': REMOVED_FROM_SHEET_STATUS,
    'label': 'Removed',
    'shortLabel': 'Removed',
    'tone': '#5F6368',
}


STATUS_ALIASES = {
    'applied': 'APPLIED',
    'apply': 'APPLIED',
    'submitted': 'APPLIED',
    'online assessment': 'OA',
    'oa': 'OA',
    'assessment': 'OA',
    'phone screen': 'SCREEN',
    'screen': 'SCREEN',
    'recruiter screen': 'SCREEN',
    'recruiter call': 'SCREEN',
    'onsite': 'ONSITE',
    'onsite interview': 'ONSITE',
    'final': 'FINAL_ROUND',
    'final round': 'FINAL_ROUND',
    'offer': 'OFFER',
    'accepted': 'OFFER',
    'reject': 'REJECTED',
    'rejected': 'REJECTED',
    'declined': 'REJECTED',
    'ghosted': 'GHOSTED',
}


ROUND_TONES = ['#A9CCFF', '#6EA8FE', '#7B8CDE', '#9B7EDE']


CUSTOM_STAGE_TONES = ['bg-blue-500', 'bg-violet-500', 'bg-sky-500', 'bg-amber-500', 'bg-emerald-500']


def default_mapping_for_target(target_type):
    if target_type == GoogleSheetSyncConfig.TARGET_EVENTS:
        return EVENT_DEFAULT_MAPPING.copy()
    return APPLICATION_DEFAULT_MAPPING.copy()
