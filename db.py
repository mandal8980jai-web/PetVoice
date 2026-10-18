"""All SQLite operations for PetFit AI. No other file touches the database.

Every function accepts an optional db_path so tests can use a temporary file.
Foreign keys are enabled on every connection. Daily logs use upsert.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  species TEXT NOT NULL CHECK (species IN ('dog','cat')),
  breed TEXT, birth_date TEXT, weight_kg REAL,
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  log_date TEXT NOT NULL,
  activity_minutes INTEGER, food_grams INTEGER,
  water_ml INTEGER, sleep_hours REAL, notes TEXT,
  is_demo INTEGER NOT NULL DEFAULT 0,
  UNIQUE (pet_id, log_date)
);

CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  period_start TEXT, period_end TEXT,
  gemini_calls_used INTEGER NOT NULL DEFAULT 0,
  used_fallback INTEGER NOT NULL DEFAULT 0,
  overall_status TEXT,
  report_json TEXT NOT NULL,
  agent_trace_json TEXT
);
"""


# ------------------------------------------------------------ connection
@contextmanager
def connect(db_path=None):
    """Open a connection with foreign keys ON; commit on success, roll back on error."""
    conn = sqlite3.connect(db_path if db_path is not None else config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=None):
    """Create the three tables if they do not exist."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------- helpers
def _now():
    return datetime.now().isoformat(timespec="seconds")


def _to_iso(value, field):
    """Accept a date, datetime or ISO string; return a 'YYYY-MM-DD' string."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a valid date (YYYY-MM-DD).")


def _clean_number(value, field, maximum, integer=False):
    """None/blank -> None (missing). Otherwise a validated non-negative number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.")
    if number != number or number < 0:
        raise ValueError(f"{field} cannot be negative.")
    if number > maximum:
        raise ValueError(f"{field} cannot be more than {maximum}.")
    return int(round(number)) if integer else round(number, 2)


def _clean_text(value, max_chars=None):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_chars and len(text) > max_chars:
        raise ValueError(f"Text is too long (maximum {max_chars} characters).")
    return text


def _validate_pet_fields(name, species, breed, birth_date, weight_kg):
    name = _clean_text(name, 60)
    if not name:
        raise ValueError("Pet name is required.")
    species = (species or "").strip().lower()
    if species not in ("dog", "cat"):
        raise ValueError("Species must be 'dog' or 'cat'.")
    birth = None
    if birth_date not in (None, ""):
        birth = _to_iso(birth_date, "Birth date")
        if birth > date.today().isoformat():
            raise ValueError("Birth date cannot be in the future.")
    weight = _clean_number(weight_kg, "Weight", config.MAX_WEIGHT_KG)
    if weight is not None and weight == 0:
        raise ValueError("Weight must be greater than zero.")
    return name, species, _clean_text(breed, 60), birth, weight


def _rows(rows):
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ pets
def add_pet(name, species, breed=None, birth_date=None, weight_kg=None,
            is_demo=False, db_path=None):
    """Create a pet and return its id."""
    name, species, breed, birth, weight = _validate_pet_fields(
        name, species, breed, birth_date, weight_kg)
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO pets (name, species, breed, birth_date, weight_kg, "
            "is_demo, created_at) VALUES (?,?,?,?,?,?,?)",
            (name, species, breed, birth, weight, 1 if is_demo else 0, _now()))
        return cur.lastrowid


def get_pet(pet_id, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
    return dict(row) if row else None


def list_pets(include_demo=True, db_path=None):
    """Real pets first, then demo pets; alphabetical within each group."""
    sql = "SELECT * FROM pets"
    if not include_demo:
        sql += " WHERE is_demo = 0"
    sql += " ORDER BY is_demo, name COLLATE NOCASE"
    with connect(db_path) as conn:
        return _rows(conn.execute(sql).fetchall())


def update_pet(pet_id, name, species, breed=None, birth_date=None,
               weight_kg=None, db_path=None):
    """Update a pet's profile. Returns True if the pet exists."""
    name, species, breed, birth, weight = _validate_pet_fields(
        name, species, breed, birth_date, weight_kg)
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE pets SET name=?, species=?, breed=?, birth_date=?, "
            "weight_kg=? WHERE id=?",
            (name, species, breed, birth, weight, pet_id))
        return cur.rowcount > 0


def delete_pet(pet_id, db_path=None):
    """Delete a pet; its logs and analyses are removed by ON DELETE CASCADE."""
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM pets WHERE id = ?", (pet_id,)).rowcount > 0


def delete_demo_data(db_path=None):
    """Remove all synthetic demo pets (and, by cascade, their logs/analyses)."""
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM pets WHERE is_demo = 1").rowcount


# ------------------------------------------------------------ daily logs
def upsert_log(pet_id, log_date, activity_minutes=None, food_grams=None,
               water_ml=None, sleep_hours=None, notes=None, db_path=None):
    """Insert a log, or update it if this pet already has one for that date.

    Blank values are stored as NULL (missing), never as 0.
    The demo flag is inherited from the pet so demo data stays distinguishable.
    """
    day = _to_iso(log_date, "Log date")
    if day > date.today().isoformat():
        raise ValueError("Log date cannot be in the future.")
    activity = _clean_number(activity_minutes, "Activity minutes",
                             config.MAX_ACTIVITY_MINUTES, integer=True)
    food = _clean_number(food_grams, "Food grams", config.MAX_FOOD_GRAMS, integer=True)
    water = _clean_number(water_ml, "Water ml", config.MAX_WATER_ML, integer=True)
    sleep = _clean_number(sleep_hours, "Sleep hours", config.MAX_SLEEP_HOURS)
    note = _clean_text(notes, config.MAX_NOTES_CHARS)
    if all(v is None for v in (activity, food, water, sleep, note)):
        raise ValueError("Enter at least one value or a note.")

    pet = get_pet(pet_id, db_path)
    if pet is None:
        raise ValueError("Pet not found.")

    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO daily_logs (pet_id, log_date, activity_minutes, "
            "food_grams, water_ml, sleep_hours, notes, is_demo) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(pet_id, log_date) DO UPDATE SET "
            "activity_minutes=excluded.activity_minutes, "
            "food_grams=excluded.food_grams, water_ml=excluded.water_ml, "
            "sleep_hours=excluded.sleep_hours, notes=excluded.notes, "
            "is_demo=excluded.is_demo",
            (pet_id, day, activity, food, water, sleep, note, pet["is_demo"]))
    return get_log(pet_id, day, db_path)


def get_log(pet_id, log_date, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM daily_logs WHERE pet_id=? AND log_date=?",
            (pet_id, _to_iso(log_date, "Log date"))).fetchone()
    return dict(row) if row else None


def get_logs(pet_id, start_date=None, end_date=None, db_path=None):
    """Logs for a pet in ascending date order, optionally within a date range."""
    sql, params = "SELECT * FROM daily_logs WHERE pet_id = ?", [pet_id]
    if start_date is not None:
        sql += " AND log_date >= ?"
        params.append(_to_iso(start_date, "Start date"))
    if end_date is not None:
        sql += " AND log_date <= ?"
        params.append(_to_iso(end_date, "End date"))
    sql += " ORDER BY log_date"
    with connect(db_path) as conn:
        return _rows(conn.execute(sql, params).fetchall())


def delete_log(pet_id, log_date, db_path=None):
    with connect(db_path) as conn:
        return conn.execute(
            "DELETE FROM daily_logs WHERE pet_id=? AND log_date=?",
            (pet_id, _to_iso(log_date, "Log date"))).rowcount > 0


def get_window_logs(pet_id, end_date=None, window_days=None, db_path=None):
    """Return the latest window and the window before it (default 7 + 7 days).

    Only days that were actually logged are returned; missing days are NOT
    filled in. Agents decide whether there is enough data to compare.
    """
    window_days = window_days or config.WINDOW_DAYS
    end = date.fromisoformat(_to_iso(end_date, "End date")) if end_date else date.today()
    cur_start = end - timedelta(days=window_days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window_days - 1)
    return {
        "current": {
            "start": cur_start.isoformat(), "end": end.isoformat(),
            "logs": get_logs(pet_id, cur_start, end, db_path)},
        "previous": {
            "start": prev_start.isoformat(), "end": prev_end.isoformat(),
            "logs": get_logs(pet_id, prev_start, prev_end, db_path)},
    }


# -------------------------------------------------------------- analyses
def save_analysis(pet_id, report, trace=None, gemini_calls_used=0,
                  used_fallback=False, overall_status=None,
                  period_start=None, period_end=None, db_path=None):
    """Store one analysis run and return its id."""
    if not 0 <= int(gemini_calls_used) <= config.GEMINI_MAX_CALLS:
        raise ValueError(
            f"gemini_calls_used must be between 0 and {config.GEMINI_MAX_CALLS}.")
    if overall_status is not None and overall_status not in config.STATUS_LEVELS:
        raise ValueError(f"overall_status must be one of {config.STATUS_LEVELS}.")
    if get_pet(pet_id, db_path) is None:
        raise ValueError("Pet not found.")
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO analyses (pet_id, created_at, period_start, period_end, "
            "gemini_calls_used, used_fallback, overall_status, report_json, "
            "agent_trace_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (pet_id, _now(), period_start, period_end, int(gemini_calls_used),
             1 if used_fallback else 0, overall_status,
             json.dumps(report, default=str),
             json.dumps(trace, default=str) if trace is not None else None))
        return cur.lastrowid


def _parse_analysis(row):
    data = dict(row)
    data["report"] = json.loads(data.pop("report_json"))
    trace = data.pop("agent_trace_json")
    data["trace"] = json.loads(trace) if trace else None
    return data


def get_analysis(analysis_id, db_path=None):
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
    return _parse_analysis(row) if row else None


def list_analyses(pet_id, db_path=None):
    """All analyses for a pet, newest first."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE pet_id = ? ORDER BY created_at DESC, id DESC",
            (pet_id,)).fetchall()
    return [_parse_analysis(r) for r in rows]