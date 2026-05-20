"""Utilities for EDGAR XBRL period strings (CY{year}, CY{year}Q{n}, CY{year}Q{n}I)."""

import re
from datetime import date, timedelta
from typing import Any

_ANNUAL_RE = re.compile(r"^CY(\d{4})$")
_QUARTERLY_RE = re.compile(r"^CY(\d{4})Q([1-4])$")
_INSTANT_RE = re.compile(r"^CY(\d{4})Q([1-4])I$")

# Quarter end dates in reverse order — used when scanning for the most recent
# complete quarter relative to a given date.
_Q_ENDS = [(4, 12, 31), (3, 9, 30), (2, 6, 30), (1, 3, 31)]


def fmt_type(period: str) -> str:
    """Return 'annual', 'quarterly', or 'instant' for a period string."""
    if _ANNUAL_RE.match(period):
        return "annual"
    if _QUARTERLY_RE.match(period):
        return "quarterly"
    if _INSTANT_RE.match(period):
        return "instant"
    raise ValueError(f"Unrecognized period format: {period!r}")


def _period_to_tuple(period: str) -> tuple[int, int]:
    """Return (year, quarter) for ordering; quarter is 0 for annual periods."""
    if m := _ANNUAL_RE.match(period):
        return (int(m.group(1)), 0)
    if m := _QUARTERLY_RE.match(period):
        return (int(m.group(1)), int(m.group(2)))
    if m := _INSTANT_RE.match(period):
        return (int(m.group(1)), int(m.group(2)))
    raise ValueError(f"Unrecognized period format: {period!r}")


def resolve_current(fmt: str) -> str:
    """
    Return the most recently available EDGAR period matching fmt's format.

    Annual: CY{last_year} — FY data is reliably filed by ~April, so year-1 is
    conservative and safe year-round.

    Quarterly / instant: subtract a 45-day filing lag from today, then walk
    backwards through quarter-end dates to find the last quarter whose 10-Q/10-K
    has had time to appear in EDGAR.
    """
    today = date.today()

    if fmt_type(fmt) == "annual":
        return f"CY{today.year - 1}"

    lag = today - timedelta(days=45)
    for q, month, day in _Q_ENDS:
        if lag >= date(lag.year, month, day):
            year, quarter = lag.year, q
            break
    else:
        year, quarter = lag.year - 1, 4

    if fmt_type(fmt) == "quarterly":
        return f"CY{year}Q{quarter}"
    return f"CY{year}Q{quarter}I"


def resolve_period_range(from_period: str, to_period: str) -> list[str]:
    """
    Expand a period range into an explicit list of period strings.

    to_period may be 'CURRENT', which resolves to the latest available period
    matching from_period's format (annual / quarterly / instant).
    """
    fmt = fmt_type(from_period)

    if to_period == "CURRENT":
        to_period = resolve_current(from_period)

    if fmt_type(to_period) != fmt:
        raise ValueError(
            f"from_period {from_period!r} and to_period {to_period!r} have different formats"
        )

    from_tup = _period_to_tuple(from_period)
    to_tup = _period_to_tuple(to_period)

    if from_tup > to_tup:
        raise ValueError(
            f"from_period {from_period!r} is after resolved to_period {to_period!r}"
        )

    periods: list[str] = []

    if fmt == "annual":
        for y in range(from_tup[0], to_tup[0] + 1):
            periods.append(f"CY{y}")
    else:
        year, quarter = from_tup
        to_year, to_quarter = to_tup
        suffix = "I" if fmt == "instant" else ""
        while (year, quarter) <= (to_year, to_quarter):
            periods.append(f"CY{year}Q{quarter}{suffix}")
            quarter += 1
            if quarter > 4:
                quarter = 1
                year += 1

    return periods


def expand_params(cfg: dict[str, Any]) -> dict[str, list]:
    """
    Expand run preset params into lists ready for cartesian product.

    Scalars → [scalar]
    Lists   → as-is
    Period interval dicts ({from, to}) → resolve_period_range()
    """
    result: dict[str, list] = {}
    for key, val in cfg.items():
        if isinstance(val, dict) and "from" in val and "to" in val:
            result[key] = resolve_period_range(val["from"], val["to"])
        elif isinstance(val, list):
            result[key] = val
        else:
            result[key] = [val]
    return result
