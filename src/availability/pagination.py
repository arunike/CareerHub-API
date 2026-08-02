from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class ConditionalPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        if 'page' not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)

    def _unlocked_count(self):
        # object_list is the full filtered queryset, before slicing to a page.
        queryset = getattr(self.page.paginator, 'object_list', None)
        if queryset is None:
            return None
        model = getattr(queryset, 'model', None)
        if model is None or not any(f.name == 'is_locked' for f in model._meta.get_fields()):
            return None
        try:
            return queryset.filter(is_locked=False).count()
        except Exception:
            return None

    def get_paginated_response(self, data):
        payload = OrderedDict([
            ('count', self.page.paginator.count),
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data),
        ])
        unlocked = self._unlocked_count()
        if unlocked is not None:
            payload['unlocked_count'] = unlocked
        return Response(payload)
