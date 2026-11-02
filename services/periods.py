from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class Period:
    key: str  # day / week / month: run keys, hashtags, admin commands
    since: str  # ?since= of github.com/trending
    days: int  # how far back the search fallback looks for new repositories
    word: str  # "Топ-10 за день", "+1 145 за день", "🔁 3-й день поспіль"

    @property
    def hashtag(self) -> str:
        return f"#{self.key}"


PERIODS = {
    "day": Period("day", "daily", 1, "день"),
    "week": Period("week", "weekly", 7, "тиждень"),
    "month": Period("month", "monthly", 30, "місяць"),
}

# Several posts due at once (the 1st falling on a Sunday) go out in this order
ORDER = ("day", "week", "month")

ALIASES = {
    "day": "day", "d": "day", "день": "day", "д": "day",
    "week": "week", "w": "week", "тиждень": "week", "т": "week",
    "month": "month", "m": "month", "місяць": "month", "м": "month",
}


@dataclass(frozen=True)
class Schedule:
    post_time: time
    weekly_day: int  # Monday is 0
    monthly_day: int  # 1..28

    def last_slot(self, key: str, now: datetime) -> datetime:
        """The latest scheduled time of the period at or before now, in now's time zone.

        The slot is built from the wall clock (date + POST_TIME in that zone), so
        06:00 stays 06:00 across the DST change instead of drifting by an hour.
        """
        tz = now.tzinfo
        today = now.date()
        if key == "day":
            day = today
            if self._at(day, tz) > now:
                day -= timedelta(days=1)
        elif key == "week":
            day = today - timedelta(days=(today.weekday() - self.weekly_day) % 7)
            if self._at(day, tz) > now:
                day -= timedelta(days=7)
        elif key == "month":
            day = today.replace(day=self.monthly_day)
            if self._at(day, tz) > now:
                day = _add_months(day, -1)
        else:
            raise ValueError(key)
        return self._at(day, tz)

    def next_slot(self, key: str, now: datetime) -> datetime:
        last = self.last_slot(key, now).date()
        if key == "day":
            day = last + timedelta(days=1)
        elif key == "week":
            day = last + timedelta(days=7)
        else:
            day = _add_months(last, 1)
        return self._at(day, now.tzinfo)

    def _at(self, day: date, tz) -> datetime:
        return datetime.combine(day, self.post_time, tzinfo=tz)


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    # monthly_day is at most 28, so the day exists in every month
    return day.replace(year=index // 12, month=index % 12 + 1)
