"""Synthetic demo data for PetVoice.

Everything created here is stored with is_demo=1 and the pet names carry
"(Demo)" so it can never be mistaken for real data. The numbers are random
but seeded (reproducible). The demo cat deliberately has two low-food days at
the end so the exhibition shows a safety flag.
"""
import random
from datetime import date, timedelta

import db

DEMO_DAYS = 14


def has_demo_data(db_path=None):
    return any(p["is_demo"] for p in db.list_pets(db_path=db_path))


def create_demo_data(db_path=None):
    """Create one demo dog and one demo cat. Returns [dog_id, cat_id].

    Does nothing (returns []) if demo data already exists.
    """
    if has_demo_data(db_path):
        return []
    rng = random.Random(42)
    today = date.today()

    dog_id = db.add_pet("Buddy (Demo)", "dog", breed="Synthetic demo dog",
                        weight_kg=22, is_demo=True, db_path=db_path)
    cat_id = db.add_pet("Luna (Demo)", "cat", breed="Synthetic demo cat",
                        weight_kg=4.5, is_demo=True, db_path=db_path)

    dog_notes = {2: "Enjoyed a long walk in the park.",
                 9: "Very playful this evening.",
                 12: "A little slower on the stairs this morning."}
    cat_notes = {3: "Lots of play with the feather toy.",
                 12: "Ate less than usual and seemed quiet.",
                 13: "Hid under the bed for most of the day."}

    for i in range(DEMO_DAYS):
        day = today - timedelta(days=DEMO_DAYS - 1 - i)

        if i != 4:  # one unlogged day on purpose, to show gaps are not filled in
            db.upsert_log(
                dog_id, day,
                activity_minutes=55 + (8 if i >= 7 else 0) + rng.randint(-8, 8),
                food_grams=280 + rng.randint(-15, 15),
                water_ml=1200 + rng.randint(-150, 150),
                sleep_hours=round(12.5 + rng.uniform(-1, 1), 1),
                notes=dog_notes.get(i), db_path=db_path)

        low_food = i >= 12
        db.upsert_log(
            cat_id, day,
            activity_minutes=35 + rng.randint(-8, 8),
            food_grams=(18 + 4 * (i - 12)) if low_food else 60 + rng.randint(-5, 5),
            water_ml=200 + rng.randint(-25, 25),
            sleep_hours=round(14 + rng.uniform(-1, 1), 1),
            notes=cat_notes.get(i), db_path=db_path)

    return [dog_id, cat_id]


def remove_demo_data(db_path=None):
    """Delete all demo pets (their logs and analyses go with them)."""
    return db.delete_demo_data(db_path)


if __name__ == "__main__":
    db.init_db()
    print("Created demo pets:", create_demo_data() or "already present")