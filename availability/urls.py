from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'events', views.EventViewSet, basename='event')
router.register(r'holidays', views.HolidayViewSet, basename='holiday')
router.register(r'overrides', views.AvailabilityOverrideViewSet, basename='override')
router.register(r'settings', views.AvailabilitySettingViewSet, basename='setting')
router.register(r'import', views.ImportViewSet, basename='import')
router.register(r'availability', views.AvailabilityViewSet, basename='availability')

router.register(r'categories', views.EventCategoryViewSet, basename='category')
router.register(r'user-settings', views.UserSettingsViewSet, basename='user-settings')
router.register(r'conflicts', views.ConflictAlertViewSet, basename='conflict')

urlpatterns = [
    path('', include(router.urls)),
]
