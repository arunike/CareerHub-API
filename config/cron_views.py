import os

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from availability.tasks import expire_stale_share_links, purge_expired_account_deletions
from career.tasks import auto_ghost_stale_applications


class DailyMaintenanceCronView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        cron_secret = (os.environ.get("CRON_SECRET") or "").strip()
        auth_header = request.headers.get("Authorization", "")
        if not cron_secret or auth_header != f"Bearer {cron_secret}":
            return Response({"detail": "Unauthorized."}, status=status.HTTP_401_UNAUTHORIZED)

        results = {
            "applications": auto_ghost_stale_applications(),
            "share_links": expire_stale_share_links(),
            "account_deletions": purge_expired_account_deletions(),
        }
        return Response({"ok": True, "results": results}, status=status.HTTP_200_OK)
