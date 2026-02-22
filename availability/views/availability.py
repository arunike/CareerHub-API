from datetime import datetime

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import AvailabilityOverride, AvailabilitySetting
from ..serializers import AvailabilityOverrideSerializer, AvailabilitySettingSerializer
from ..utils import calculate_availability_for_dates, get_next_two_weeks_weekdays


class AvailabilityOverrideViewSet(viewsets.ModelViewSet):
    queryset = AvailabilityOverride.objects.all()
    serializer_class = AvailabilityOverrideSerializer


class AvailabilitySettingViewSet(viewsets.ModelViewSet):
    queryset = AvailabilitySetting.objects.all()
    serializer_class = AvailabilitySettingSerializer
    lookup_field = 'key'


class AvailabilityViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['get'])
    def generate(self, request):
        target_tz = request.query_params.get('timezone', 'PT')
        start_date_str = request.query_params.get('start_date')

        start_date = None
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            except ValueError:
                return Response({'error': 'Invalid date format'}, status=status.HTTP_400_BAD_REQUEST)

        dates = get_next_two_weeks_weekdays(start_date)
        availability_map = calculate_availability_for_dates(dates, target_tz)

        response_data = []
        for date_obj in dates:
            date_str = date_obj.strftime('%Y-%m-%d')
            availability = availability_map.get(date_str)
            if availability:
                response_data.append(availability)
        return Response(response_data)
