from rest_framework.routers import DefaultRouter
from .views import (
    InterviewDebriefViewSet,
    ApplicationContactViewSet,
    ContactRelationshipViewSet,
    AIArtifactViewSet,
    AIArtifactGenerationJobViewSet,
    ApplicationViewSet,
    ApplicationTimelineAnalyticsView,
    ApplyImportApplicationsView,
    ImportApplicationsView,
    JobBoardImportView,
    OfferViewSet,
    OfferDecisionSnapshotViewSet,
    DocumentViewSet,
    TaskViewSet,
    ReferenceDataView,
    RentEstimateView,
    WeeklyReviewView,
    ExperienceViewSet,
    ImportExperiencesView,
    ApplicationTimelineEntryViewSet,
    GoogleOAuthCallbackView,
    GoogleOAuthViewSet,
    GoogleSheetSyncConfigViewSet,
)
from django.urls import path

router = DefaultRouter()
router.register(r'ai-artifacts', AIArtifactViewSet, basename='ai-artifact')
router.register(r'ai-artifact-jobs', AIArtifactGenerationJobViewSet, basename='ai-artifact-job')
router.register(r'applications', ApplicationViewSet)
router.register(r'application-contacts', ApplicationContactViewSet, basename='application-contact')
router.register(r'contacts', ApplicationContactViewSet, basename='contact')
router.register(r'contact-relationships', ContactRelationshipViewSet, basename='contact-relationship')
router.register(r'interview-debriefs', InterviewDebriefViewSet, basename='interview-debrief')
router.register(r'offers', OfferViewSet)
router.register(r'offer-decision-snapshots', OfferDecisionSnapshotViewSet, basename='offer-decision-snapshot')
router.register(r'documents', DocumentViewSet)
router.register(r'tasks', TaskViewSet)
router.register(r'experiences', ExperienceViewSet)
router.register(r'application-timeline', ApplicationTimelineEntryViewSet, basename='application-timeline')
router.register(r'google-oauth', GoogleOAuthViewSet, basename='google-oauth')
router.register(r'google-sheet-syncs', GoogleSheetSyncConfigViewSet, basename='google-sheet-sync')

urlpatterns = [
    path('import/', ImportApplicationsView.as_view(), name='import-applications'),
    path('import/apply/', ApplyImportApplicationsView.as_view(), name='apply-import-applications'),
    path('job-import/', JobBoardImportView.as_view(), name='job-board-import'),
    path('experiences/import/', ImportExperiencesView.as_view(), name='import-experiences'),
    path('reference-data/', ReferenceDataView.as_view(), name='career-reference-data'),
    path('rent-estimate/', RentEstimateView.as_view(), name='career-rent-estimate'),
    path('weekly-review/', WeeklyReviewView.as_view(), name='career-weekly-review'),
    path('application-timeline-analytics/', ApplicationTimelineAnalyticsView.as_view(), name='application-timeline-analytics'),
    path('google-oauth/callback/', GoogleOAuthCallbackView.as_view(), name='google-oauth-callback'),
] + router.urls
