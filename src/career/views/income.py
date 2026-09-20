from rest_framework import viewsets

from ..models import IncomeYear
from ..serializers import IncomeYearSerializer


class IncomeYearViewSet(viewsets.ModelViewSet):
    queryset = IncomeYear.objects.all()
    serializer_class = IncomeYearSerializer

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return IncomeYear.objects.none()
        return IncomeYear.objects.filter(user=self.request.user).prefetch_related('actuals')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


