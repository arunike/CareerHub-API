from datetime import timedelta

from django.utils import timezone

DEFAULT_GHOSTING_THRESHOLD_DAYS = 30


def auto_ghost_stale_applications():
    from career.models import Application
    from career.services.cache import invalidate_applications_cache
    from availability.models import UserSettings

    count = 0
    user_settings_map = {
        settings.user_id: settings.ghosting_threshold_days or DEFAULT_GHOSTING_THRESHOLD_DAYS
        for settings in UserSettings.objects.exclude(user__isnull=True)
    }

    for user_id in Application.objects.exclude(user__isnull=True).values_list('user_id', flat=True).distinct():
        threshold_days = user_settings_map.get(user_id, DEFAULT_GHOSTING_THRESHOLD_DAYS)
        cutoff_date = timezone.localdate() - timedelta(days=threshold_days)
        stale_applications = Application.objects.filter(
            user_id=user_id,
            status="APPLIED",
            date_applied__lte=cutoff_date,
        )
        updated_count = stale_applications.update(status="GHOSTED")
        if updated_count:
            invalidate_applications_cache(user_id)
            count += updated_count

    return f"Ghosted {count} stale application(s)."


def backfill_tracked_stock_prices(period='2y'):
    """Fill the daily price log for every ticker any account tracks, one series per symbol."""
    from career.models import StockPrice
    from career.services.stock_quotes import backfill_history

    holders = {}
    # No .iterator(): the hosted Postgres refuses the server-side cursor it opens.
    for row in StockPrice.objects.exclude(user__isnull=True).select_related('user'):
        holders.setdefault(row.symbol, []).append(row.user)

    added, failed = 0, []
    for symbol, users in sorted(holders.items()):
        for user in users:
            try:
                added += backfill_history(user=user, symbol=symbol, period=period)['added']
            except Exception:  # noqa: BLE001 - one bad ticker must not stop the sweep
                failed.append(symbol)

    if failed:
        return f"Added {added} day(s) across {len(holders)} ticker(s); {len(failed)} failed."
    return f"Added {added} day(s) across {len(holders)} ticker(s)."


def refresh_tracked_stock_prices():
    """Refresh every ticker any account tracks, one quote per symbol."""
    from career.models import StockPrice
    from career.services.stock_quotes import fetch_quote, record_price

    holders = {}
    # No .iterator(): the hosted Postgres refuses the server-side cursor it opens.
    for row in StockPrice.objects.exclude(user__isnull=True).select_related('user'):
        holders.setdefault(row.symbol, []).append(row.user)

    refreshed, failed = 0, []
    for symbol, users in sorted(holders.items()):
        try:
            quote = fetch_quote(symbol)
        except Exception:  # noqa: BLE001 - one bad ticker must not stop the sweep
            failed.append(symbol)
            continue
        for user in users:
            record_price(
                user=user,
                symbol=quote['symbol'],
                price=quote['price'],
                as_of=quote['as_of'] or timezone.localdate(),
                source='API',
                note=f"Fetched at {quote['currency']}",
            )
        refreshed += 1

    if failed:
        return f"Refreshed {refreshed} of {len(holders)} ticker(s); {len(failed)} failed."
    return f"Refreshed {refreshed} ticker(s)."
