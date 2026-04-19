import json

from channels.generic.websocket import AsyncWebsocketConsumer


def get_conflict_alerts_group_name(user_id):
    return f"conflict_alerts_user_{user_id}"


class ConflictAlertConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        self.conflict_alerts_group = get_conflict_alerts_group_name(user.id)
        await self.channel_layer.group_add(self.conflict_alerts_group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "conflict_alerts_group"):
            await self.channel_layer.group_discard(self.conflict_alerts_group, self.channel_name)

    # Called when a message is received from the WebSocket client (not used)
    async def receive(self, text_data=None, bytes_data=None):
        pass

    # Called by channel_layer.group_send with type="conflict_alert"
    async def conflict_alert(self, event):
        await self.send(text_data=json.dumps(event))
