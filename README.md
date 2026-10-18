# PetVoice

*Understand Their Habits. Care Beyond Words.*

A Streamlit dashboard for tracking a dog's or cat's daily activity, food intake,
water, sleep and owner observations. Five specialised agents and an orchestrator
analyse the latest 7 days against the previous 7 days and produce a non-diagnostic
report that can be downloaded as a PDF.

**PetVoice is informational only. It does not diagnose, treat or replace
professional veterinary advice.**

## Setup (Windows, Python 3.11)

```powershell
cd C:\Users\dell\Desktop\multiagent
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project folder with one line:
GEMINI_API_KEY=your_real_key_here

The key is read only from `.env` (git-ignored). Without a key the app still works
using rule-based summaries.

## Run

```powershell
streamlit run app.py
```

## Tests

```powershell
python -m pytest tests -q
```

The tests use temporary databases and a fake Gemini client, so they need no key
and no network.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI (Dashboard, Daily Log, Analysis, History) |
| `agents.py` | Activity, Trend, Observation, Safety and Report agents, orchestrator, Gemini helper |
| `db.py` | All SQLite operations (pets, daily_logs, analyses) |
| `config.py` | Thresholds, ranges, Gemini model name, theme colours, disclaimer text |
| `demo_data.py` | Synthetic demo dog and cat, clearly labelled |
| `pdf_export.py` | PDF report builder (ReportLab) |
| `tests/test_core.py` | Database and agent tests |

## How an analysis works

1. Load the latest 7 days and the previous 7 days of logs (missing days are never filled in).
2. Stop with a friendly message if fewer than 3 days are logged.
3. Activity Agent and Trend Agent (pure Python). A trend needs at least 3 logged days in both periods.
4. Observation Agent: Gemini call 1 summarises owner notes, with a keyword fallback.
5. Safety Agent: rule-based flags only, never decided by Gemini.
6. Report Agent: combines everything. Gemini call 2 rewrites only the short overview paragraph, with a template fallback.
7. The result is saved to history and can be downloaded as a PDF.

At most 2 Gemini calls are made per analysis. Replies that look truncated or
contain diagnostic wording are rejected in favour of the rule-based text.

## Changing the Gemini model

Edit `GEMINI_MODEL` in `config.py`. Check the current model name in Google AI
Studio before presenting.

## Demo walkthrough

1. Sidebar, "Synthetic demo data", then "Load synthetic demo data".
2. Select **Buddy (Demo)** (normal) and **Luna (Demo)** (food-intake flag).
3. Open the Analysis tab and click "Run analysis".
4. Untick "Use Gemini for summaries" and run again to show the offline fallback.
5. Download the PDF. Demo reports carry a "Synthetic demo data" banner.
6. "Remove all demo data" deletes only demo pets, never real ones.

## Limitations

- Reference ranges are broad, conservative general guidance, not veterinary standards.
- Keyword matching on owner notes cannot read context (for example "no vomiting").
- Averages can hide a single unusual day, so check the daily charts too.
- Single-user local app: no login, no cloud hosting.