from rest_framework.routers import DefaultRouter
from .views import CompanyViewSet, ApplicationViewSet, ImportApplicationsView, OfferViewSet
from django.urls import path

router = DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'applications', ApplicationViewSet)
router.register(r'offers', OfferViewSet)

urlpatterns = [
    path('import/', ImportApplicationsView.as_view(), name='import-applications'),
] + router.urls
