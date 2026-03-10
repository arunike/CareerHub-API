import json

from channels.generic.websocket import AsyncWebsocketConsumer

CONFLICT_ALERTS_GROUP = "conflict_alerts"


class ConflictAlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add(CONFLICT_ALERTS_GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(CONFLICT_ALERTS_GROUP, self.channel_name)

    # Called when a message is received from the WebSocket client (not used)
    async def receive(self, text_data=None, bytes_data=None):
        pass

    # Called by channel_layer.group_send with type="conflict_alert"
    async def conflict_alert(self, event):
        await self.send(text_data=json.dumps(event))
