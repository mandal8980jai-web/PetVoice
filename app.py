"""PetVoice - Streamlit dashboard. UI only: logic is in agents.py, storage in db.py."""
import html
import re
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import agents
import config
import db
import demo_data
import pdf_export

st.set_page_config(page_title=config.APP_NAME, page_icon="\U0001F43E", layout="wide")
db.init_db()

C = config.COLORS
STATUS_COLORS = {"normal": C["teal"], "watch": C["demo"], "consult_vet": "#B83232",
                 None: "#6B7C93"}
FLAG_COLORS = {"vet": "#B83232", "watch": C["demo"], "info": C["blue"]}
FLAG_LABELS = {"vet": "Consider contacting your vet", "watch": "Keep an eye on",
               "info": "Info"}

CSS = """
<style>
.stApp { background: __LIGHT__; }
[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid __BORDER__; }
h1, h2, h3, h4, .stMarkdown, .stMarkdown p, label, [data-testid="stMetricValue"],
[data-testid="stMetricLabel"] { color: __NAVY__; }
[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid __BORDER__;
  border-radius: 10px; padding: 12px 16px; border-top: 3px solid __TEAL__; }
.stTabs [aria-selected="true"] { color: __BLUE__; }
.badge { display: inline-block; padding: 3px 12px; border-radius: 999px; color: #FFFFFF;
  font-size: 0.85rem; font-weight: 600; margin-right: 6px; }
.badge-soft { background: #E8F1FB; color: __NAVY__; }
.demo-banner { background: #FFF7E6; border: 1px solid __DEMO__; color: #7A4F0C;
  border-radius: 8px; padding: 8px 14px; margin-bottom: 10px; }
.flag { border-left: 4px solid; background: #FFFFFF; border-radius: 6px;
  padding: 8px 12px; margin-bottom: 8px; color: __NAVY__; }
.card { background: #FFFFFF; border: 1px solid __BORDER__; border-radius: 10px;
  padding: 14px 18px; margin-bottom: 10px; color: __NAVY__; }
</style>
"""
for token, value in (("__LIGHT__", C["light_bg"]), ("__BORDER__", C["border"]),
                     ("__NAVY__", C["navy"]), ("__TEAL__", C["teal"]),
                     ("__BLUE__", C["blue"]), ("__DEMO__", C["demo"])):
    CSS = CSS.replace(token, value)
st.markdown(CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------- helpers
def esc(value):
    return html.escape("" if value is None else str(value))


def demo_banner():
    st.markdown(
        f'<div class="demo-banner"><b>{esc(config.DEMO_LABEL)}</b> &mdash; this pet and '
        f'its logs are generated for demonstration. Not a real animal.</div>',
        unsafe_allow_html=True)


def age_text(birth_iso):
    if not birth_iso:
        return None
    born, today = date.fromisoformat(birth_iso), date.today()
    months = (today.year - born.year) * 12 + today.month - born.month
    if today.day < born.day:
        months -= 1
    return f"{max(months, 0) // 12}y {max(months, 0) % 12}m"


# ----------------------------------------------------------------- sidebar
def sidebar():
    with st.sidebar:
        st.markdown(f"## \U0001F43E {config.APP_NAME}")
        st.caption(config.APP_TAGLINE)
        st.caption("Dog and cat activity, food, sleep and owner observations")

        pets = db.list_pets()
        ids = [p["id"] for p in pets]
        pending = st.session_state.pop("pending_pet", None)
        if pending in ids:
            st.session_state["selected_pet"] = pending
        if st.session_state.get("selected_pet") not in ids:
            st.session_state.pop("selected_pet", None)

        selected = None
        if pets:
            by_id = {p["id"]: p for p in pets}

            def fmt(pid):
                p = by_id[pid]
                tag = "  [DEMO]" if p["is_demo"] else ""
                return f"{p['name']} ({p['species'].title()}){tag}"

            pid = st.selectbox("Select pet", ids, format_func=fmt, key="selected_pet")
            selected = by_id[pid]

        st.divider()
        key_ok = config.get_gemini_api_key() is not None
        use_gemini = st.checkbox("Use Gemini for summaries", value=True,
                                 disabled=not key_ok, key="use_gemini")
        if key_ok:
            st.caption(f"Model: {config.GEMINI_MODEL}. At most "
                       f"{config.GEMINI_MAX_CALLS} calls per analysis. Untick to work offline.")
        else:
            st.caption("No Gemini key found in .env - using rule-based summaries.")
        use_gemini = bool(use_gemini and key_ok)

        st.divider()
        with st.expander("Add a pet"):
            with st.form("add_pet_form", clear_on_submit=True):
                name = st.text_input("Name")
                species = st.selectbox("Species", ["Dog", "Cat"])
                breed = st.text_input("Breed (optional)")
                weight = st.number_input("Weight in kg (0 = unknown)", min_value=0.0,
                                         max_value=float(config.MAX_WEIGHT_KG),
                                         value=0.0, step=0.5)
                has_birth = st.checkbox("Add birth date")
                birth = st.date_input("Birth date", value=date.today(),
                                      min_value=date(1990, 1, 1), max_value=date.today())
                submitted = st.form_submit_button("Add pet")
            if submitted:
                try:
                    new_id = db.add_pet(name, species.lower(), breed,
                                        birth if has_birth else None, weight or None)
                    st.session_state["pending_pet"] = new_id
                    st.session_state["flash"] = f"Added {name.strip()}."
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        if selected and not selected["is_demo"]:
            with st.expander("Edit or delete selected pet"):
                pid = selected["id"]
                with st.form(f"edit_pet_form_{pid}"):
                    e_name = st.text_input("Name", value=selected["name"], key=f"en_{pid}")
                    e_species = st.selectbox(
                        "Species", ["Dog", "Cat"], key=f"es_{pid}",
                        index=0 if selected["species"] == "dog" else 1)
                    e_breed = st.text_input("Breed", value=selected["breed"] or "",
                                            key=f"eb_{pid}")
                    e_weight = st.number_input(
                        "Weight in kg (0 = unknown)", min_value=0.0,
                        max_value=float(config.MAX_WEIGHT_KG), step=0.5,
                        value=float(selected["weight_kg"] or 0.0), key=f"ew_{pid}")
                    e_has_birth = st.checkbox("Has birth date",
                                              value=bool(selected["birth_date"]),
                                              key=f"ehb_{pid}")
                    e_birth = st.date_input(
                        "Birth date", key=f"ebd_{pid}", min_value=date(1990, 1, 1),
                        max_value=date.today(),
                        value=date.fromisoformat(selected["birth_date"])
                        if selected["birth_date"] else date.today())
                    saved = st.form_submit_button("Save changes")
                if saved:
                    try:
                        db.update_pet(pid, e_name, e_species.lower(), e_breed,
                                      e_birth if e_has_birth else None, e_weight or None)
                        st.session_state["flash"] = "Pet updated."
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                confirm = st.checkbox("I understand this deletes the pet, its logs "
                                      "and its analyses", key=f"confirm_del_{pid}")
                if st.button("Delete pet", disabled=not confirm, key=f"del_pet_{pid}"):
                    db.delete_pet(pid)
                    st.session_state.pop("analysis_view", None)
                    st.session_state["flash"] = "Pet deleted."
                    st.rerun()

        with st.expander(f"{config.DEMO_LABEL}"):
            st.caption("Generated for demonstration only. Demo pets are tagged [DEMO] "
                       "and never mixed with real pets.")
            if demo_data.has_demo_data():
                if st.button("Remove all demo data", key="remove_demo"):
                    demo_data.remove_demo_data()
                    st.session_state.pop("analysis_view", None)
                    st.session_state["flash"] = "Demo data removed."
                    st.rerun()
            elif st.button("Load synthetic demo data", key="load_demo"):
                ids_new = demo_data.create_demo_data()
                if ids_new:
                    st.session_state["pending_pet"] = ids_new[0]
                st.session_state["flash"] = "Synthetic demo pets loaded."
                st.rerun()
    return selected, use_gemini


# --------------------------------------------------------------- dashboard
def _avg(logs, metric):
    vals = [l[metric] for l in logs if l.get(metric) is not None]
    return (sum(vals) / len(vals) if vals else None), len(vals)


def build_frame(logs, days):
    end = date.today()
    start = end - timedelta(days=days - 1)
    frame = pd.DataFrame(logs)
    frame["log_date"] = pd.to_datetime(frame["log_date"])
    frame = frame.set_index("log_date")
    for metric in agents.METRICS:
        frame[metric] = pd.to_numeric(frame[metric], errors="coerce")
    return frame.reindex(pd.date_range(start, end))   # unlogged days stay empty


def make_figure(frame, metric, pet):
    label, unit = agents.METRIC_LABELS[metric]
    fig = go.Figure()
    if metric == "food_grams":
        fig.add_trace(go.Bar(x=frame.index, y=frame[metric], marker_color=C["blue"]))
    else:
        color = C["teal"] if metric in ("activity_minutes", "water_ml") else C["blue"]
        fig.add_trace(go.Scatter(x=frame.index, y=frame[metric], mode="lines+markers",
                                 connectgaps=False, line=dict(color=color, width=2.5),
                                 marker=dict(size=7)))
    ranges = config.SPECIES_RANGES[pet["species"]]
    band = None
    if metric in ("activity_minutes", "sleep_hours"):
        band = ranges[metric]
    elif metric == "water_ml" and pet.get("weight_kg"):
        low, high = ranges["water_ml_per_kg"]
        band = (low * pet["weight_kg"], high * pet["weight_kg"])
    if band:
        fig.add_hrect(y0=band[0], y1=band[1], fillcolor=C["teal"], opacity=0.10,
                      line_width=0, annotation_text="General guidance range",
                      annotation_position="top left", annotation_font_size=10)
    fig.update_layout(title=f"{label} ({unit})", height=300, showlegend=False,
                      margin=dict(l=10, r=10, t=45, b=10), paper_bgcolor="white",
                      plot_bgcolor="white", font=dict(color=C["navy"]))
    fig.update_xaxes(gridcolor=C["border"])
    fig.update_yaxes(gridcolor=C["border"])
    return fig


def render_dashboard(pet):
    pid = pet["id"]
    all_logs = db.get_logs(pid)
    if not all_logs:
        st.info("No logs yet. Add the first one in the Daily Log tab.")
        return
    windows = db.get_window_logs(pid)
    cur, prev = windows["current"], windows["previous"]

    cols = st.columns(4)
    for col, metric in zip(cols, agents.METRICS):
        label, unit = agents.METRIC_LABELS[metric]
        cur_avg, n_cur = _avg(cur["logs"], metric)
        prev_avg, n_prev = _avg(prev["logs"], metric)
        delta = None
        if (cur_avg is not None and prev_avg is not None
                and n_cur >= config.MIN_DAYS_FOR_TREND
                and n_prev >= config.MIN_DAYS_FOR_TREND):
            delta = f"{cur_avg - prev_avg:+.1f} vs previous"
        col.metric(f"{label} ({unit})",
                   "-" if cur_avg is None else f"{cur_avg:.1f}",
                   delta, delta_color="off")
        col.caption(f"{n_cur} day(s) logged")
    st.caption(f"Averages cover the latest {config.WINDOW_DAYS} days "
               f"({cur['start']} to {cur['end']}). A change is shown only when both "
               f"periods have at least {config.MIN_DAYS_FOR_TREND} logged days. "
               f"Unlogged days are left blank, never filled in.")

    choice = st.radio("Chart range", ["Last 14 days", "Last 30 days", "Last 90 days"],
                      horizontal=True, key=f"range_{pid}")
    days = int(choice.split()[1])
    frame = build_frame(all_logs, days)
    left, right = st.columns(2)
    for i, metric in enumerate(agents.METRICS):
        target = left if i % 2 == 0 else right
        with target:
            if frame[metric].notna().any():
                st.plotly_chart(make_figure(frame, metric, pet), key=f"chart_{pid}_{metric}")
            else:
                st.info(f"No {agents.METRIC_LABELS[metric][0].lower()} data logged "
                        f"in this period.")
    st.caption(config.GUIDANCE_LABEL)

    st.markdown("#### Recent logs")
    recent = list(reversed(all_logs))[:14]
    table = pd.DataFrame([{
        "Date": l["log_date"],
        "Activity (min)": l["activity_minutes"],
        "Food (g)": l["food_grams"],
        "Water (ml)": l["water_ml"],
        "Sleep (h)": l["sleep_hours"],
        "Notes": l["notes"] or "",
        "Source": config.DEMO_LABEL if l["is_demo"] else "Real entry"} for l in recent])
    st.dataframe(table, hide_index=True)


# --------------------------------------------------------------- daily log
def render_daily_log(pet):
    pid = pet["id"]
    st.subheader("Daily log")
    st.caption("Leave a field blank if you did not record it - blank is stored as "
               "'missing', not zero. Enter 0 only if the value really was zero.")
    if pet["is_demo"]:
        st.warning("You are editing synthetic demo data.")
    log_date = st.date_input("Date", value=date.today(), max_value=date.today(),
                             key=f"log_date_{pid}")
    existing = db.get_log(pid, log_date)
    tag = f"{pid}_{log_date.isoformat()}"

    def prefill(field):
        value = existing.get(field) if existing else None
        return "" if value is None else str(value)

    if existing:
        st.info("A log already exists for this date. Saving will update it.")
    with st.form(f"log_form_{tag}"):
        c1, c2 = st.columns(2)
        activity = c1.text_input("Activity (minutes)", value=prefill("activity_minutes"),
                                 key=f"act_{tag}")
        food = c2.text_input("Food eaten (grams)", value=prefill("food_grams"),
                             key=f"food_{tag}")
        c3, c4 = st.columns(2)
        sleep = c3.text_input("Sleep (hours)", value=prefill("sleep_hours"),
                              key=f"sleep_{tag}")
        water = c4.text_input("Water (ml, optional)", value=prefill("water_ml"),
                              key=f"water_{tag}")
        notes = st.text_area("Owner observations (optional)", value=prefill("notes"),
                             key=f"notes_{tag}", max_chars=config.MAX_NOTES_CHARS,
                             placeholder="e.g. Ate eagerly, played in the garden")
        saved = st.form_submit_button("Save log", type="primary")
    if saved:
        try:
            db.upsert_log(pid, log_date, activity_minutes=activity, food_grams=food,
                          water_ml=water, sleep_hours=sleep, notes=notes)
            st.session_state["flash"] = f"Log saved for {log_date.isoformat()}."
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if existing and st.button("Delete this day's log", key=f"del_log_{tag}"):
        db.delete_log(pid, log_date)
        st.session_state["flash"] = f"Log deleted for {log_date.isoformat()}."
        st.rerun()


# ---------------------------------------------------------------- reports
def render_report(analysis, key_prefix):
    report = analysis["report"]
    status = analysis.get("overall_status")
    color = STATUS_COLORS.get(status, STATUS_COLORS[None])
    period = report.get("period", {})

    if report.get("demo_label"):
        demo_banner()

    ai_used = (report.get("overview_source") == "gemini"
               or report.get("observations", {}).get("source") == "gemini")
    source_badge = "AI-assisted summary" if ai_used else "Rule-based summary"
    st.markdown(
        f'<span class="badge" style="background:{color}">'
        f'{esc(report.get("status_label", "Unavailable"))}</span>'
        f'<span class="badge badge-soft">{source_badge}</span>'
        f'<span class="badge badge-soft">Gemini calls: '
        f'{analysis.get("gemini_calls_used", 0)} of {config.GEMINI_MAX_CALLS}</span>',
        unsafe_allow_html=True)
    st.markdown(f"### {report.get('headline', '')}")
    st.caption(f"Period {period.get('start')} to {period.get('end')} compared with "
               f"{period.get('previous_start')} to {period.get('previous_end')}  |  "
               f"Created {analysis.get('created_at', '')}")
    st.markdown(f'<div class="card">{esc(report.get("overview", ""))}</div>',
                unsafe_allow_html=True)

    if report.get("unavailable_sections"):
        st.warning("Unavailable in this run: " + ", ".join(report["unavailable_sections"]))

    left, right = st.columns(2)
    with left:
        st.markdown("#### Key findings")
        for line in report.get("key_findings", []):
            st.markdown(f"- {line}")
    with right:
        st.markdown("#### Safety flags")
        flags = report.get("flags", [])
        if not flags:
            st.markdown("No safety rules were triggered by the logged data "
                        "(this is not a health clearance).")
        for f in flags:
            level = f.get("level", "info")
            st.markdown(
                f'<div class="flag" style="border-color:{FLAG_COLORS.get(level, C["blue"])}">'
                f'<b>{esc(FLAG_LABELS.get(level, level))}</b><br>{esc(f.get("message"))}</div>',
                unsafe_allow_html=True)

    if report.get("metrics"):
        st.markdown("#### Averages vs general guidance")
        rows = [{"Metric": f"{m['label']} ({m['unit']})",
                 "Average": "-" if m["average"] is None else str(m["average"]),
                 "Days logged": str(m["days_logged"]),
                 "Compared with guidance": m["rating_text"],
                 "General guidance range": m["range_text"]} for m in report["metrics"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        st.caption(report.get("guidance_label", config.GUIDANCE_LABEL))

    if report.get("trends"):
        st.markdown("#### Trends")
        for t in report["trends"]:
            st.markdown(f"- {t['text']}")

    obs = report.get("observations", {})
    if obs.get("available"):
        st.markdown("#### Owner observations")
        st.write(obs.get("summary", ""))
        st.caption("Summary by Gemini" if obs.get("source") == "gemini"
                   else "Rule-based summary")

    if report.get("suggestions"):
        st.markdown("#### General suggestions")
        for line in report["suggestions"]:
            st.markdown(f"- {line}")

    quality = report.get("data_quality", {})
    with st.expander("Data quality and agent trace"):
        st.write(f"{quality.get('days_logged', 0)} of {quality.get('days_in_window', 7)} "
                 f"days logged ({quality.get('completeness_pct', 0)}%).")
        for note in quality.get("notes", []):
            st.markdown(f"- {note}")
        trace = analysis.get("trace") or []
        if trace:
            st.dataframe(pd.DataFrame([{
                "Agent": t["agent"], "Status": t["status"],
                "Time (ms)": t["elapsed_ms"], "Notes": "; ".join(t["warnings"])}
                for t in trace]), hide_index=True)

    st.info(report.get("disclaimer", config.DISCLAIMER))

    pet_name = re.sub(r"[^A-Za-z0-9_-]+", "_", report.get("pet", {}).get("name", "pet"))
    try:
        pdf_bytes = pdf_export.build_pdf(report)
        st.download_button(
            "Download PDF report", data=pdf_bytes, mime="application/pdf",
            file_name=f"petfit_report_{pet_name}_{period.get('end', 'report')}.pdf",
            key=f"pdf_{key_prefix}_{analysis['id']}")
    except Exception as exc:
        st.error(f"The PDF could not be created ({type(exc).__name__}).")


def render_analysis(pet, use_gemini):
    pid = pet["id"]
    st.subheader("Analysis")
    st.caption(f"Compares the latest {config.WINDOW_DAYS} days with the previous "
               f"{config.WINDOW_DAYS} days. Needs at least "
               f"{config.MIN_DAYS_FOR_ANALYSIS} logged days in the latest period. "
               f"Missing days are never filled in, and nothing here is a diagnosis.")
    st.caption("Mode: " + (f"AI-assisted (at most {config.GEMINI_MAX_CALLS} Gemini calls)"
                           if use_gemini else "Rule-based only (works offline)"))
    if st.button("Run analysis", type="primary", key=f"run_{pid}"):
        with st.spinner("The agents are working..."):
            outcome = agents.run_analysis(pid, use_gemini=use_gemini)
        if outcome["ok"]:
            st.session_state["analysis_view"] = {"pet_id": pid,
                                                 "analysis_id": outcome["analysis_id"]}
            st.rerun()
        else:
            st.session_state.pop("analysis_view", None)
            st.warning(outcome["message"])
    view = st.session_state.get("analysis_view")
    if view and view["pet_id"] == pid:
        analysis = db.get_analysis(view["analysis_id"])
        if analysis:
            render_report(analysis, key_prefix="latest")


def render_history(pet):
    pid = pet["id"]
    st.subheader("Analysis history")
    analyses = db.list_analyses(pid)
    if not analyses:
        st.info("No saved analyses yet. Run one in the Analysis tab.")
        return
    st.dataframe(pd.DataFrame([{
        "Created": a["created_at"],
        "Period": f"{a['period_start']} to {a['period_end']}",
        "Status": agents.STATUS_LABELS.get(a["overall_status"], "Unavailable"),
        "Gemini calls": a["gemini_calls_used"],
        "Summary": "Rule-based" if a["used_fallback"] else "AI-assisted"}
        for a in analyses]), hide_index=True)
    by_id = {a["id"]: a for a in analyses}
    choice = st.selectbox(
        "Open a saved analysis", list(by_id), key=f"hist_{pid}",
        format_func=lambda i: f"{by_id[i]['created_at']} - "
                              f"{agents.STATUS_LABELS.get(by_id[i]['overall_status'], 'Unavailable')}")
    render_report(by_id[choice], key_prefix="history")


# -------------------------------------------------------------------- main
def main():
    pet, use_gemini = sidebar()
    st.title(f"\U0001F43E {config.APP_NAME}")
    st.caption(config.APP_TAGLINE)

    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)

    if pet is None:
        st.markdown("### Welcome")
        st.write("Add your first dog or cat from the sidebar, or load the clearly "
                 "labelled synthetic demo data to explore the dashboard.")
        st.caption(config.DISCLAIMER)
        return

    if pet["is_demo"]:
        demo_banner()
    bits = [pet["species"].title()]
    if pet["breed"]:
        bits.append(pet["breed"])
    if pet["weight_kg"]:
        bits.append(f"{pet['weight_kg']} kg")
    if age_text(pet["birth_date"]):
        bits.append(age_text(pet["birth_date"]))
    st.markdown(f"## {pet['name']}")
    st.caption("  |  ".join(bits))

    tab_dash, tab_log, tab_analysis, tab_history = st.tabs(
        ["Dashboard", "Daily Log", "Analysis", "History"])
    with tab_dash:
        render_dashboard(pet)
    with tab_log:
        render_daily_log(pet)
    with tab_analysis:
        render_analysis(pet, use_gemini)
    with tab_history:
        render_history(pet)

    st.divider()
    st.caption(config.DISCLAIMER)


main()