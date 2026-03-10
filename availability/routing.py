from django.urls import path

from .consumers import ConflictAlertConsumer

websocket_urlpatterns = [
    path("ws/conflicts/", ConflictAlertConsumer.as_asgi()),
]
