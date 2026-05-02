from rest_framework.routers import DefaultRouter
from .views import (
    CompanyViewSet,
    ApplicationViewSet,
    ImportApplicationsView,
    JobBoardImportView,
    OfferViewSet,
    DocumentViewSet,
    TaskViewSet,
    ReferenceDataView,
    RentEstimateView,
    WeeklyReviewView,
    ExperienceViewSet,
    ImportExperiencesView,
    ApplicationTimelineEntryViewSet,
    GoogleSheetSyncConfigViewSet,
)
from django.urls import path

router = DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'applications', ApplicationViewSet)
router.register(r'offers', OfferViewSet)
router.register(r'documents', DocumentViewSet)
router.register(r'tasks', TaskViewSet)
router.register(r'experiences', ExperienceViewSet)
router.register(r'application-timeline', ApplicationTimelineEntryViewSet, basename='application-timeline')
router.register(r'google-sheet-syncs', GoogleSheetSyncConfigViewSet, basename='google-sheet-sync')

urlpatterns = [
    path('import/', ImportApplicationsView.as_view(), name='import-applications'),
    path('job-import/', JobBoardImportView.as_view(), name='job-board-import'),
    path('experiences/import/', ImportExperiencesView.as_view(), name='import-experiences'),
    path('reference-data/', ReferenceDataView.as_view(), name='career-reference-data'),
    path('rent-estimate/', RentEstimateView.as_view(), name='career-rent-estimate'),
    path('weekly-review/', WeeklyReviewView.as_view(), name='career-weekly-review'),
] + router.urls
