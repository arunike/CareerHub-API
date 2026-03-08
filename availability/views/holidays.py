from datetime import datetime

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import CustomHoliday, UserSettings
from ..serializers import CustomHolidaySerializer
from ..utils import export_data, get_federal_holidays


class HolidayViewSet(viewsets.ModelViewSet):
    queryset = CustomHoliday.objects.all()
    serializer_class = CustomHolidaySerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This holiday is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['get'])
    def federal(self, request):
        year = datetime.now().year
        holidays_dict = get_federal_holidays(year)
        
        user_settings = UserSettings.objects.first()
        ignored_holidays = user_settings.ignored_federal_holidays if user_settings else []
        
        data = []
        for d, name in sorted(holidays_dict.items()):
            date_str = d.strftime('%Y-%m-%d')
            is_ignored = name in ignored_holidays or date_str in ignored_holidays
            data.append({
                'date': date_str, 
                'description': name,
                'is_ignored': is_ignored
            })
            
        return Response(data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), self.get_serializer_class(), fmt, 'holidays')

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = CustomHoliday.objects.filter(is_locked=False).delete()
        return Response(
            {'message': f'Deleted {count} holidays. Locked holidays were preserved.'},
            status=status.HTTP_200_OK,
        )
