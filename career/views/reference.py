from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import (
    build_reference_data_payload,
    build_weekly_review_payload,
    fetch_hud_rent_estimate,
)


class ReferenceDataView(APIView):
    def get(self, request, *args, **kwargs):
        return Response(build_reference_data_payload())


class RentEstimateView(APIView):
    def get(self, request, *args, **kwargs):
        city = (request.query_params.get('city') or '').strip()
        if not city:
            return Response({'error': 'city query param is required'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(fetch_hud_rent_estimate(city), status=status.HTTP_200_OK)


class WeeklyReviewView(APIView):
    def get(self, request, *args, **kwargs):
        payload, error = build_weekly_review_payload(
            request.query_params.get('start_date'),
            request.query_params.get('end_date'),
        )
        if error:
            return Response(error, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload, status=status.HTTP_200_OK)
