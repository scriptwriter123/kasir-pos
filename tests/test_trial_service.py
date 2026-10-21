import json
from datetime import datetime, timedelta, timezone

from app.services.trial_service import TrialService


def fixed_now(value: datetime):
    return lambda: value


def test_trial_starts_on_first_call_and_is_active(tmp_path):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    service = TrialService(tmp_path, now_fn=fixed_now(now))

    active, message = service.status()
    assert active is True
    assert "2026-01-08" in message
    assert (tmp_path / "trial-state.json").is_file()

    later = now + timedelta(days=6)
    service_later = TrialService(tmp_path, now_fn=fixed_now(later))
    active, message = service_later.status()
    assert active is True
    assert "sisa" in message


def test_trial_expires_after_seven_days(tmp_path):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    TrialService(tmp_path, now_fn=fixed_now(now)).status()

    after = now + timedelta(days=7, hours=1)
    active, message = TrialService(tmp_path, now_fn=fixed_now(after)).status()
    assert active is False
    assert "berakhir" in message


def test_clock_rollback_does_not_extend_trial(tmp_path):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    TrialService(tmp_path, now_fn=fixed_now(now)).status()

    # Day 6: observe time, updating the high-water mark.
    day_six = now + timedelta(days=6)
    active, _ = TrialService(tmp_path, now_fn=fixed_now(day_six)).status()
    assert active is True

    # Clock rolled back to day 1: high-water mark must be used, so after
    # seven days counted from the high-water mark the trial is over.
    rolled_back = day_six + timedelta(days=2)
    service = TrialService(tmp_path, now_fn=fixed_now(now))
    active, _ = service.status()
    # rolled_back is beyond started + 7 days when measured from high-water
    assert service.effective_now() >= day_six

    expired = TrialService(tmp_path, now_fn=fixed_now(rolled_back))
    active, message = expired.status()
    assert active is False


def test_trial_state_written_with_iso_timestamps(tmp_path):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    TrialService(tmp_path, now_fn=fixed_now(now)).status()

    state = json.loads(
        (tmp_path / "trial-state.json").read_text(encoding="utf-8")
    )
    assert datetime.fromisoformat(state["started_at"]).tzinfo is not None
    assert datetime.fromisoformat(state["last_seen_at"]).tzinfo is not None


def test_corrupt_state_file_starts_fresh_without_crashing(tmp_path):
    (tmp_path / "trial-state.json").write_text("not-json", encoding="utf-8")
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    active, message = TrialService(tmp_path, now_fn=fixed_now(now)).status()
    assert active is True
    assert "2026-01-08" in message
