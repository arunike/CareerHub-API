from datetime import date


def replace_holiday_year(source_date, target_year):
    try:
        return source_date.replace(year=target_year)
    except ValueError:
        # Treat a yearly February 29 holiday as February 28 in non-leap years.
        return date(target_year, 2, 28)


def project_recurring_holiday_dates(holidays, target_year):
    projected_dates = {}
    grouped_holidays = {}

    for holiday in holidays:
        if holiday.is_recurring and holiday.group_id:
            grouped_holidays.setdefault(holiday.group_id, []).append(holiday)
        elif holiday.is_recurring:
            projected_dates[holiday.id] = replace_holiday_year(holiday.date, target_year)
        else:
            projected_dates[holiday.id] = holiday.date

    for group in grouped_holidays.values():
        ordered_group = sorted(group, key=lambda holiday: holiday.date)
        source_start = ordered_group[0].date
        projected_start = replace_holiday_year(source_start, target_year)
        for holiday in ordered_group:
            projected_dates[holiday.id] = projected_start + (holiday.date - source_start)

    return projected_dates
