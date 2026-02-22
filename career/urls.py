from rest_framework.routers import DefaultRouter
from .views import (
    CompanyViewSet,
    ApplicationViewSet,
    ImportApplicationsView,
    OfferViewSet,
    DocumentViewSet,
    TaskViewSet,
    ReferenceDataView,
    RentEstimateView,
    WeeklyReviewView,
)
from django.urls import path

router = DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'applications', ApplicationViewSet)
router.register(r'offers', OfferViewSet)
router.register(r'documents', DocumentViewSet)
router.register(r'tasks', TaskViewSet)

urlpatterns = [
    path('import/', ImportApplicationsView.as_view(), name='import-applications'),
    path('reference-data/', ReferenceDataView.as_view(), name='career-reference-data'),
    path('rent-estimate/', RentEstimateView.as_view(), name='career-rent-estimate'),
    path('weekly-review/', WeeklyReviewView.as_view(), name='career-weekly-review'),
] + router.urls
