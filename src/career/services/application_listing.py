from django.db.models import Case, Count, IntegerField, Q, Value, When

OFFER_RECEIVED_FILTER = Q(offer__isnull=False)


def build_application_summary(queryset):
    return queryset.aggregate(
        total=Count('id'),
        interviews=Count(
            'id',
            filter=(
                Q(status='SCREEN')
                | Q(status='FINAL_ROUND')
                | Q(status='ONSITE')
                | Q(status__startswith='ROUND_')
            ),
        ),
        offers=Count('id', filter=OFFER_RECEIVED_FILTER),
        locked=Count('id', filter=Q(is_locked=True)),
    )


def apply_application_ordering(queryset, ordering):
    ordering = (ordering or '').strip()
    if ordering in {'status', '-status'}:
        queryset = queryset.annotate(status_rank=_status_order_expression())
        direction = '-' if ordering.startswith('-') else ''
        return queryset.order_by(f'{direction}status_rank', '-date_applied', '-created_at', '-id')
    return queryset.order_by('-date_applied', '-created_at', '-id')


def _status_order_expression():
    round_whens = [
        When(status=f'ROUND_{round_number}', then=Value(100 - round_number))
        for round_number in range(1, 51)
    ]
    return Case(
        When(status='OFFER', then=Value(0)),
        When(status='FINAL_ROUND', then=Value(30)),
        When(status='ONSITE', then=Value(40)),
        *round_whens,
        When(status='SCREEN', then=Value(110)),
        When(status='OA', then=Value(120)),
        When(status='APPLIED', then=Value(130)),
        When(status='GHOSTED', then=Value(140)),
        When(status='REJECTED', then=Value(150)),
        When(status='REMOVED_FROM_SHEET', then=Value(160)),
        default=Value(125),
        output_field=IntegerField(),
    )
