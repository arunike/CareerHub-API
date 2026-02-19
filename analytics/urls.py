from django.urls import path
from .views import CustomWidgetQueryView

urlpatterns = [
    path('query/', CustomWidgetQueryView.as_view(), name='custom-widget-query'),
]
