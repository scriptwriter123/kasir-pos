from datetime import date, datetime, time, timedelta, timezone


def calculate_period_range(
    period: str,
    selected: date | datetime,
) -> tuple[datetime, datetime, str]:
    if period == "hour":
        if not isinstance(selected, datetime):
            raise TypeError("Laporan per jam memerlukan tanggal dan waktu.")
        local_start = selected.replace(minute=0, second=0, microsecond=0)
        local_start = local_start.astimezone()
        local_end = (
            local_start.astimezone(timezone.utc) + timedelta(hours=1)
        ).astimezone()
        label = local_start.strftime("%d-%m-%Y %H:00")
    elif period == "day":
        target = _as_date(selected)
        local_start = datetime.combine(target, time.min).astimezone()
        local_end = datetime.combine(
            target + timedelta(days=1),
            time.min,
        ).astimezone()
        label = target.strftime("%d-%m-%Y")
    elif period == "month":
        target = _as_date(selected)
        first = date(target.year, target.month, 1)
        if target.month == 12:
            following = date(target.year + 1, 1, 1)
        else:
            following = date(target.year, target.month + 1, 1)
        local_start = datetime.combine(first, time.min).astimezone()
        local_end = datetime.combine(following, time.min).astimezone()
        label = first.strftime("%B %Y")
    elif period == "year":
        year = selected.year
        local_start = datetime.combine(date(year, 1, 1), time.min).astimezone()
        local_end = datetime.combine(date(year + 1, 1, 1), time.min).astimezone()
        label = str(year)
    else:
        raise ValueError(f"Jenis periode laporan tidak dikenal: {period}")
    return local_start, local_end, label


def _as_date(selected: date | datetime) -> date:
    return selected.date() if isinstance(selected, datetime) else selected
