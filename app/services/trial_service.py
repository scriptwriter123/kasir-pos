import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TRIAL_DAYS = 7
STATE_FILENAME = "trial-state.json"
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


def default_trial_duration() -> timedelta:
    return timedelta(days=TRIAL_DAYS)


def format_duration(duration: timedelta, *, round_up: bool = False) -> str:
    total_seconds = duration.total_seconds()
    if round_up and total_seconds % 60:
        total_seconds += 60
    total_minutes = int(total_seconds // 60)
    if total_minutes < 60:
        return f"{max(total_minutes, 0)} menit"
    if total_minutes < 1440:
        return f"{total_minutes // 60} jam"
    return f"{total_minutes // 1440} hari"


class TrialError(ValueError):
    pass


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class TrialService:
    """Local trial with clock-rollback detection.

    The state file records when the trial started and the highest wall-clock
    time observed so far. If the system clock is moved backwards, the stored
    high-water mark is used instead, so rolling the clock back never extends
    the trial period.
    """

    def __init__(
        self,
        data_dir: Path,
        now_fn=None,
        duration: timedelta | None = None,
    ):
        self.data_dir = data_dir
        self.state_path = data_dir / STATE_FILENAME
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self.duration = duration or default_trial_duration()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, state: dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def effective_now(self) -> datetime:
        """Current time, never lower than the stored high-water mark."""
        now = self._now()
        state = self._load()
        last_seen = _parse_iso(state.get("last_seen_at"))
        if last_seen is not None and last_seen > now:
            return last_seen
        return now

    def status(self) -> tuple[bool, str]:
        """Return (trial_active, message). Starts the trial on first call."""
        state = self._load()
        now = self._now()
        started_at = _parse_iso(state.get("started_at"))
        last_seen = _parse_iso(state.get("last_seen_at"))

        if last_seen is not None and now < last_seen - CLOCK_SKEW_TOLERANCE:
            # Clock moved backwards: keep the high-water mark so the trial
            # cannot be extended by resetting the system date.
            now = last_seen

        if started_at is None:
            started_at = now
        if last_seen is None or now > last_seen:
            state["last_seen_at"] = now.isoformat()
        state["started_at"] = started_at.isoformat()
        self._save(state)

        trial_end = started_at + self.duration
        label = format_duration(self.duration)
        if now >= trial_end:
            return (
                False,
                f"Masa trial {label} berakhir pada "
                f"{trial_end.date().isoformat()}. "
                "Aktifkan lisensi untuk melanjutkan.",
            )
        remaining = trial_end - now
        remaining_label = format_duration(remaining, round_up=True)
        return (
            True,
            f"Masa trial berakhir pada {trial_end.date().isoformat()} "
            f"(sisa {remaining_label}).",
        )

    def reset_for_tests(self) -> None:
        if self.state_path.is_file():
            self.state_path.unlink()
