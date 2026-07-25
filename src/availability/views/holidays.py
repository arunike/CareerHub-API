from datetime import datetime

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.core.cache import cache

from ..models import CustomHoliday, UserSettings
from ..serializers import CustomHolidaySerializer
from ..utils import export_data, get_federal_holidays
from ..cache import get_holidays_cache_key, invalidate_holidays_cache
from ..holiday_recurrence import project_recurring_holiday_dates


def _get_requested_holiday_year(request):
    raw_year = request.query_params.get('year')
    if raw_year in (None, ''):
        return datetime.now().year

    try:
        year = int(raw_year)
    except (TypeError, ValueError) as exc:
        raise ValidationError({'year': 'Year must be a four-digit number.'}) from exc

    if year < 1900 or year > 2100:
        raise ValidationError({'year': 'Year must be between 1900 and 2100.'})
    return year


class HolidayViewSet(viewsets.ModelViewSet):
    queryset = CustomHoliday.objects.all()
    serializer_class = CustomHolidaySerializer

    def get_queryset(self):
        queryset = CustomHoliday.objects.filter(user=self.request.user)
        if self.action == 'list':
            return queryset.exclude(holiday_type='federal')
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {'error': 'This holiday is locked and cannot be deleted. Unlock it first.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        user_id = request.user.id
        cache_key = get_holidays_cache_key(user_id, "list-personal", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=300)
        return response

    @action(detail=False, methods=['get'])
    def federal(self, request):
        user_id = request.user.id
        cache_key = get_holidays_cache_key(user_id, "federal", request.query_params)
        
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)
            
        year = _get_requested_holiday_year(request)
        holidays_dict = get_federal_holidays(year)
        
        user_settings = UserSettings.objects.filter(user=request.user).first()
        ignored_holidays = user_settings.ignored_federal_holidays if user_settings else []
        
        data = []
        for d, name in sorted(holidays_dict.items()):
            date_str = d.strftime('%Y-%m-%d')
            is_ignored = name in ignored_holidays or date_str in ignored_holidays
            data.append({
                'date': date_str, 
                'description': name,
                'holiday_type': 'federal_native',
                'is_ignored': is_ignored
            })
            
        custom_federal = list(
            CustomHoliday.objects.filter(
                Q(date__year=year) | Q(is_recurring=True),
                user=request.user,
                holiday_type='federal',
            )
        )
        projected_dates = project_recurring_holiday_dates(custom_federal, year)
        for custom in custom_federal:
            date_str = projected_dates[custom.id].strftime('%Y-%m-%d')
            is_ignored = custom.description in ignored_holidays or date_str in ignored_holidays
            data.append({
                'id': custom.id,
                'date': date_str,
                'group_id': custom.group_id,
                'description': custom.description,
                'holiday_type': 'federal',
                'is_recurring': custom.is_recurring,
                'is_locked': custom.is_locked,
                'is_ignored': is_ignored
            })
            
        data.sort(key=lambda x: x['date'])
        
        cache.set(cache_key, data, timeout=300)
        return Response(data)

    @action(detail=False, methods=['get'])
    def export(self, request):
        fmt = request.query_params.get('fmt', 'csv')
        return export_data(self.get_queryset(), self.get_serializer_class(), fmt, 'holidays')

    @action(detail=False, methods=['delete'])
    def delete_all(self, request):
        count, _ = self.get_queryset().exclude(
            holiday_type='federal'
        ).filter(is_locked=False).delete()
        invalidate_holidays_cache(request.user.id)
        return Response(
            {'message': f'Deleted {count} holidays. Locked holidays were preserved.'},
            status=status.HTTP_200_OK,
        )
