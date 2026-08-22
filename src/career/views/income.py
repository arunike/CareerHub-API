from rest_framework import viewsets

from ..models import IncomeYear, PaycheckActual, TaxProfile
from ..serializers import IncomeYearSerializer, PaycheckActualSerializer, TaxProfileSerializer


class TaxProfileViewSet(viewsets.ModelViewSet):
    queryset = TaxProfile.objects.all()
    serializer_class = TaxProfileSerializer

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return TaxProfile.objects.none()
        return TaxProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class IncomeYearViewSet(viewsets.ModelViewSet):
    queryset = IncomeYear.objects.all()
    serializer_class = IncomeYearSerializer

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return IncomeYear.objects.none()
        return IncomeYear.objects.filter(user=self.request.user).prefetch_related('actuals')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PaycheckActualViewSet(viewsets.ModelViewSet):
    queryset = PaycheckActual.objects.all()
    serializer_class = PaycheckActualSerializer

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return PaycheckActual.objects.none()
        return PaycheckActual.objects.filter(income_year__user=self.request.user)
