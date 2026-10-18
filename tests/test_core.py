"""Core tests. Database tests for now; agent tests are added in later steps."""
import sqlite3
from datetime import date, timedelta

import pytest

import config
import db


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


@pytest.fixture
def dog_id(db_path):
    return db.add_pet("Rex", "dog", weight_kg=20, db_path=db_path)


def _count_logs(db_path):
    with db.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM daily_logs").fetchone()[0]


# ---------------------------------------------------------------- schema
def test_exactly_three_tables(db_path):
    with db.connect(db_path) as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert names == {"pets", "daily_logs", "analyses"}


def test_foreign_keys_enabled_on_every_connection(db_path):
    for _ in range(2):
        with db.connect(db_path) as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_database_rejects_orphan_log(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO daily_logs (pet_id, log_date) VALUES (999, '2026-01-01')")


# ------------------------------------------------------------------ pets
def test_dog_and_cat_profiles_listed(db_path):
    db.add_pet("Rex", "dog", db_path=db_path)
    db.add_pet("Mia", "Cat", db_path=db_path)
    species = {p["species"] for p in db.list_pets(db_path=db_path)}
    assert species == {"dog", "cat"}


def test_invalid_pet_rejected(db_path):
    with pytest.raises(ValueError):
        db.add_pet("", "dog", db_path=db_path)
    with pytest.raises(ValueError):
        db.add_pet("Bird", "parrot", db_path=db_path)
    with pytest.raises(ValueError):
        db.add_pet("Rex", "dog", weight_kg=-3, db_path=db_path)


def test_update_pet(db_path, dog_id):
    assert db.update_pet(dog_id, "Rexy", "dog", weight_kg=22, db_path=db_path)
    assert db.get_pet(dog_id, db_path)["name"] == "Rexy"


# ------------------------------------------------------------------ logs
def test_upsert_updates_instead_of_duplicating(db_path, dog_id):
    day = date.today()
    db.upsert_log(dog_id, day, activity_minutes=40, db_path=db_path)
    db.upsert_log(dog_id, day, activity_minutes=65, db_path=db_path)
    assert _count_logs(db_path) == 1
    assert db.get_log(dog_id, day, db_path)["activity_minutes"] == 65


def test_blank_values_stored_as_missing_not_zero(db_path, dog_id):
    log = db.upsert_log(dog_id, date.today(), activity_minutes=30,
                        food_grams="", sleep_hours=None, db_path=db_path)
    assert log["food_grams"] is None
    assert log["sleep_hours"] is None
    assert log["water_ml"] is None


def test_explicit_zero_is_kept_as_zero(db_path, dog_id):
    log = db.upsert_log(dog_id, date.today(), water_ml=0, db_path=db_path)
    assert log["water_ml"] == 0


def test_invalid_logs_rejected(db_path, dog_id):
    tomorrow = date.today() + timedelta(days=1)
    with pytest.raises(ValueError):
        db.upsert_log(dog_id, tomorrow, activity_minutes=30, db_path=db_path)
    with pytest.raises(ValueError):
        db.upsert_log(dog_id, date.today(), food_grams=-5, db_path=db_path)
    with pytest.raises(ValueError):
        db.upsert_log(dog_id, date.today(), sleep_hours=30, db_path=db_path)
    with pytest.raises(ValueError):
        db.upsert_log(dog_id, "not-a-date", activity_minutes=30, db_path=db_path)
    with pytest.raises(ValueError):
        db.upsert_log(dog_id, date.today(), db_path=db_path)  # nothing entered
    with pytest.raises(ValueError):
        db.upsert_log(999, date.today(), activity_minutes=30, db_path=db_path)
    assert _count_logs(db_path) == 0


# ------------------------------------------------------- demo separation
def test_demo_flag_inherited_from_pet(db_path):
    demo = db.add_pet("Demo Dog", "dog", is_demo=True, db_path=db_path)
    real = db.add_pet("Rex", "dog", db_path=db_path)
    assert db.upsert_log(demo, date.today(), activity_minutes=30,
                         db_path=db_path)["is_demo"] == 1
    assert db.upsert_log(real, date.today(), activity_minutes=30,
                         db_path=db_path)["is_demo"] == 0


def test_delete_demo_data_keeps_real_data(db_path):
    demo = db.add_pet("Demo Cat", "cat", is_demo=True, db_path=db_path)
    real = db.add_pet("Rex", "dog", db_path=db_path)
    db.upsert_log(demo, date.today(), activity_minutes=20, db_path=db_path)
    db.upsert_log(real, date.today(), activity_minutes=20, db_path=db_path)
    assert db.delete_demo_data(db_path) == 1
    assert [p["id"] for p in db.list_pets(db_path=db_path)] == [real]
    assert _count_logs(db_path) == 1


def test_real_pets_listed_before_demo_pets(db_path):
    db.add_pet("Aaa Demo", "dog", is_demo=True, db_path=db_path)
    db.add_pet("Zed", "cat", db_path=db_path)
    assert [p["is_demo"] for p in db.list_pets(db_path=db_path)] == [0, 1]


def test_cascade_delete_removes_logs_and_analyses(db_path, dog_id):
    db.upsert_log(dog_id, date.today(), activity_minutes=30, db_path=db_path)
    db.save_analysis(dog_id, {"headline": "x"}, db_path=db_path)
    assert db.delete_pet(dog_id, db_path)
    assert _count_logs(db_path) == 0
    assert db.list_analyses(dog_id, db_path) == []


# --------------------------------------------------------------- windows
def test_window_logs_split_and_do_not_fill_gaps(db_path, dog_id):
    end = date(2026, 10, 18)
    db.upsert_log(dog_id, end, activity_minutes=50, db_path=db_path)
    db.upsert_log(dog_id, end - timedelta(days=6), activity_minutes=40, db_path=db_path)
    db.upsert_log(dog_id, end - timedelta(days=7), activity_minutes=30, db_path=db_path)
    db.upsert_log(dog_id, end - timedelta(days=14), activity_minutes=20, db_path=db_path)
    w = db.get_window_logs(dog_id, end_date=end, db_path=db_path)
    assert w["current"]["start"] == "2026-10-12"
    assert w["previous"]["start"] == "2026-10-05"
    assert w["previous"]["end"] == "2026-10-11"
    assert len(w["current"]["logs"]) == 2    # only logged days, no filler
    assert len(w["previous"]["logs"]) == 1   # 14 days back is outside both windows


# -------------------------------------------------------------- analyses
def test_analysis_round_trip(db_path, dog_id):
    report = {"headline": "All typical", "flags": []}
    aid = db.save_analysis(dog_id, report, trace=[{"agent": "activity"}],
                           gemini_calls_used=1, used_fallback=True,
                           overall_status="normal", db_path=db_path)
    saved = db.get_analysis(aid, db_path)
    assert saved["report"] == report
    assert saved["trace"] == [{"agent": "activity"}]
    assert saved["used_fallback"] == 1
    assert len(db.list_analyses(dog_id, db_path)) == 1


def test_analysis_enforces_gemini_cap_and_status(db_path, dog_id):
    with pytest.raises(ValueError):
        db.save_analysis(dog_id, {}, gemini_calls_used=config.GEMINI_MAX_CALLS + 1,
                         db_path=db_path)
    with pytest.raises(ValueError):
        db.save_analysis(dog_id, {}, overall_status="diagnosed", db_path=db_path)


# ---------------------------------------------------------------- config
def test_placeholder_api_key_treated_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "your_key_here")
    assert config.get_gemini_api_key() is None
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert config.get_gemini_api_key() is None
    monkeypatch.setenv("GEMINI_API_KEY", "abc123")
    assert config.get_gemini_api_key() == "abc123"

# ======================= AGENT TESTS (step 4) =======================
import agents
import pdf_export

END = date(2026, 10, 18)
DOG = {"name": "Rex", "species": "dog", "breed": None, "weight_kg": 20, "is_demo": 0}
NORMAL = {"activity_minutes": 60, "food_grams": 300, "water_ml": 1400, "sleep_hours": 12}
FAKE_REPLY = "The owner described a quiet day."


def _log(day, **values):
    row = {"log_date": day.isoformat(), "activity_minutes": None, "food_grams": None,
           "water_ml": None, "sleep_hours": None, "notes": None}
    row.update(values)
    return row


def _logs(first_day, per_day):
    """One log per consecutive day starting at first_day."""
    return [_log(first_day + timedelta(days=i), **kw) for i, kw in enumerate(per_day)]


def _windows(cur_days, prev_days):
    cur_start = END - timedelta(days=6)
    prev_start = END - timedelta(days=13)
    cur = {"start": cur_start.isoformat(), "end": END.isoformat(),
           "logs": _logs(cur_start, cur_days)}
    prev = {"start": prev_start.isoformat(),
            "end": (END - timedelta(days=7)).isoformat(),
            "logs": _logs(prev_start, prev_days)}
    return cur, prev


def _safety(cur_days, prev_days, pet=DOG):
    cur, prev = _windows(cur_days, prev_days)
    activity = agents.activity_agent(pet, cur)
    trend = agents.trend_agent(cur, prev)
    obs = agents.observation_agent(pet, cur, agents.GeminiBudget(enabled=False))
    return agents.safety_agent(pet, cur, prev, activity, trend, obs)["data"]


def _rule_ids(data):
    return [f["rule_id"] for f in data["flags"]]


def _seed(db_path, n_days=7, with_note=True):
    pid = db.add_pet("Rex", "dog", weight_kg=20, db_path=db_path)
    for i in range(n_days):
        day = date.today() - timedelta(days=i)
        db.upsert_log(pid, day, activity_minutes=60, food_grams=300, water_ml=1400,
                      sleep_hours=12,
                      notes="Quiet day, ate well" if (with_note and i == 0) else None,
                      db_path=db_path)
    return pid


@pytest.fixture
def fake_gemini(monkeypatch):
    """Replaces the Gemini client so tests never touch the network."""
    calls = {"n": 0, "fail": False}

    class Resp:
        text = FAKE_REPLY

    class Models:
        def generate_content(self, **kwargs):
            calls["n"] += 1
            if calls["fail"]:
                raise RuntimeError("network down")
            return Resp()

    class Client:
        def __init__(self, *args, **kwargs):
            self.models = Models()

    monkeypatch.setattr("google.genai.Client", Client)
    monkeypatch.setattr(config, "get_gemini_api_key", lambda: "fake-key")
    return calls


# ----------------------------------------------------------------- trend
def _direction(cur_value, prev_value):
    cur, prev = _windows([{"activity_minutes": cur_value}] * 3,
                         [{"activity_minutes": prev_value}] * 3)
    data = agents.trend_agent(cur, prev)["data"]
    return data["metrics"]["activity_minutes"]["direction"]


def test_trend_up_down_stable():
    assert _direction(60, 40) == "up"
    assert _direction(30, 60) == "down"
    assert _direction(52, 50) == "stable"
    assert _direction(50, 50) == "stable"


def test_trend_insufficient_data_is_never_invented():
    cur, prev = _windows([{"activity_minutes": 50}] * 3, [])
    data = agents.trend_agent(cur, prev)["data"]
    entry = data["metrics"]["activity_minutes"]
    assert entry["direction"] == "insufficient_data"
    assert entry["percent_change"] is None
    assert data["has_any_trend"] is False
    cur, prev = _windows([{"activity_minutes": 50}] * 2, [{"activity_minutes": 40}] * 3)
    entry = agents.trend_agent(cur, prev)["data"]["metrics"]["activity_minutes"]
    assert entry["direction"] == "insufficient_data"


def test_streak_detection():
    rising = _logs(END, [{"activity_minutes": v} for v in (10, 20, 30, 40)])
    assert agents._streak(rising, "activity_minutes") == {"direction": "up", "changes": 3}
    gap = [_log(END, activity_minutes=10),
           _log(END + timedelta(days=1), activity_minutes=20),
           _log(END + timedelta(days=3), activity_minutes=30)]
    assert agents._streak(gap, "activity_minutes") is None  # a missing day breaks it


# -------------------------------------------------------------- activity
def _activity(value, pet=DOG):
    cur, _ = _windows([{"activity_minutes": value}] * 3, [])
    return agents.activity_agent(pet, cur)["data"]


def test_activity_averages_and_ratings():
    cur, _ = _windows([{"activity_minutes": 40}, {"activity_minutes": 50},
                       {"activity_minutes": 60}], [])
    data = agents.activity_agent(DOG, cur)["data"]
    assert data["averages"]["activity_minutes"] == 50
    assert data["ratings"]["activity_minutes"] == "typical"
    assert data["days_logged"] == 3
    assert data["completeness_pct"] == 43
    assert data["ratings"]["food_grams"] == "no_data"
    assert data["averages"]["sleep_hours"] is None
    assert _activity(10)["ratings"]["activity_minutes"] == "low"
    assert _activity(200)["ratings"]["activity_minutes"] == "high"


def test_activity_without_weight_or_data():
    pet = dict(DOG, weight_kg=None)
    cur, _ = _windows([{"water_ml": 500, "food_grams": 200}] * 3, [])
    result = agents.activity_agent(pet, cur)
    assert result["data"]["ratings"]["water_ml"] == "unrated"
    assert result["data"]["ratings"]["food_grams"] == "not_rated"
    assert result["warnings"]


# ---------------------------------------------------------------- safety
def test_safety_food_drop():
    cur = [NORMAL] * 5 + [dict(NORMAL, food_grams=100)] * 2
    data = _safety(cur, [NORMAL] * 7)
    assert "FOOD_DROP" in _rule_ids(data)
    assert data["overall_status"] == "watch"
    one_day = [NORMAL] * 6 + [dict(NORMAL, food_grams=100)]
    assert "FOOD_DROP" not in _rule_ids(_safety(one_day, [NORMAL] * 7))


def test_safety_zero_water():
    cur = [NORMAL] * 5 + [dict(NORMAL, water_ml=0)] * 2
    data = _safety(cur, [NORMAL] * 7)
    assert "WATER_ZERO" in _rule_ids(data)
    assert data["overall_status"] == "watch"


def test_safety_long_sleep():
    cur = [NORMAL] * 6 + [dict(NORMAL, sleep_hours=21)]
    assert "SLEEP_HIGH" in _rule_ids(_safety(cur, [NORMAL] * 7))


def test_safety_note_keywords():
    concern = [NORMAL] * 6 + [dict(NORMAL, notes="Seemed lethargic and not eating")]
    data = _safety(concern, [NORMAL] * 7)
    assert "NOTES_CONCERN" in _rule_ids(data)
    assert data["overall_status"] == "watch"
    serious = [NORMAL] * 6 + [dict(NORMAL, notes="Noticed blood in the stool")]
    data = _safety(serious, [NORMAL] * 7)
    assert "NOTES_SERIOUS" in _rule_ids(data)
    assert data["overall_status"] == "consult_vet"


def test_safety_normal_data_stays_normal():
    data = _safety([NORMAL] * 7, [NORMAL] * 7)
    assert data["overall_status"] == "normal"
    assert all(f["level"] == "info" for f in data["flags"])
    assert "FOOD_DROP" not in _rule_ids(data)


def test_sparse_data_skips_range_info_flags():
    """Regression (roni): 3 logged days must not produce 'below guidance' info flags."""
    cur = [dict(NORMAL, sleep_hours=9)] * 3
    ids = _rule_ids(_safety(cur, []))
    assert "SLEEP_RANGE" not in ids
    assert "LOW_DATA" in ids


# ---------------------------------------------------------------- Gemini
def test_gemini_cap_is_two(fake_gemini):
    budget = agents.GeminiBudget(enabled=True)
    replies = [agents.call_gemini("hi", budget) for _ in range(5)]
    assert replies[:2] == [FAKE_REPLY, FAKE_REPLY]
    assert replies[2:] == [None, None, None]
    assert fake_gemini["n"] == 2
    assert budget.calls_used == 2
    assert budget.last_error == "call cap reached"


def test_reply_check_rejects_diagnosis_and_truncation():
    assert agents._reply_ok("The cat ate less and was quiet.")
    assert not agents._reply_ok("Your dog has arthritis.")
    assert not agents._reply_ok("The cat ate less and was")   # cut off mid-sentence
    assert not agents._reply_ok("")
    assert not agents._reply_ok("x. " * 2000)                  # too long


def test_offline_fallback_without_key(db_path, monkeypatch):
    monkeypatch.setattr(config, "get_gemini_api_key", lambda: None)
    pid = _seed(db_path)
    out = agents.run_analysis(pid, use_gemini=True, db_path=db_path)
    assert out["ok"]
    assert out["gemini_calls_used"] == 0
    assert out["report"]["overview_source"] == "rule_based"
    assert out["report"]["observations"]["source"] == "rule_based"
    assert out["used_fallback"] is True


def test_gemini_failure_falls_back(db_path, fake_gemini):
    fake_gemini["fail"] = True
    pid = _seed(db_path)
    out = agents.run_analysis(pid, use_gemini=True, db_path=db_path)
    assert out["ok"]
    assert out["gemini_calls_used"] <= config.GEMINI_MAX_CALLS
    assert fake_gemini["n"] <= config.GEMINI_MAX_CALLS
    assert out["report"]["overview_source"] == "rule_based"


def test_full_run_uses_exactly_two_calls(db_path, fake_gemini):
    pid = _seed(db_path)
    out = agents.run_analysis(pid, use_gemini=True, db_path=db_path)
    assert out["ok"]
    assert fake_gemini["n"] == 2
    assert out["gemini_calls_used"] == 2
    assert out["report"]["overview_source"] == "gemini"
    assert db.get_analysis(out["analysis_id"], db_path)["gemini_calls_used"] == 2


# ---------------------------------------------------------- orchestrator
def test_too_few_days_stops_politely(db_path):
    pid = _seed(db_path, n_days=2)
    out = agents.run_analysis(pid, use_gemini=False, db_path=db_path)
    assert out["ok"] is False
    assert "Only 2" in out["message"]
    assert db.list_analyses(pid, db_path) == []


def test_one_failed_agent_does_not_crash_run(db_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(agents, "trend_agent", boom)
    pid = _seed(db_path)
    out = agents.run_analysis(pid, use_gemini=False, db_path=db_path)
    assert out["ok"]
    statuses = {t["agent"]: t["status"] for t in out["trace"]}
    assert statuses["trend"] == "failed"
    assert statuses["safety"] != "failed"
    assert "Trend analysis" in out["report"]["unavailable_sections"]


def test_no_streak_claimed_without_trend(db_path):
    """Regression (roni): 3 days, no previous period -> no 'in a row' claim."""
    pid = db.add_pet("Roni", "dog", weight_kg=7, db_path=db_path)
    for i in range(3):
        day = date.today() - timedelta(days=2 - i)
        db.upsert_log(pid, day, activity_minutes=30 + 10 * i, db_path=db_path)
    out = agents.run_analysis(pid, use_gemini=False, db_path=db_path)
    assert out["ok"]
    text = " ".join(out["report"]["key_findings"])
    assert "in a row" not in text
    assert "No trend is claimed" in text


def test_pdf_is_generated(db_path):
    pid = _seed(db_path)
    out = agents.run_analysis(pid, use_gemini=False, db_path=db_path)
    pdf = pdf_export.build_pdf(out["report"])
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000