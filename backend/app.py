from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import time
from datetime import date, datetime
from math import hypot
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from data_engine import DataEngine, EventOption
from insight_engine import GraniteInsightProvider, InsightContext, InsightEngine, RuleFallbackInsightProvider
from telemetry_export import build_telemetry_3d_payload


BASELINE_COLOR = "#16a34a"
DRIVER_COLOR = "#dc2626"
AI_STEP_INTERVAL = 30


@st.cache_resource(show_spinner=False)
def get_insight_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="apexsim-insight")


@st.cache_data(ttl=3600, show_spinner=False)
def discover_events(year: int) -> list[EventOption]:
    return DataEngine().get_event_options(year)


@st.cache_data(ttl=3600, show_spinner=False)
def discover_sessions(year: int, event_round: int) -> list[str]:
    return DataEngine().get_session_options(year, event_round)


@st.cache_data(ttl=1800, show_spinner=False)
def discover_drivers(year: int, event_round: int, session_type: str) -> list[str]:
    return DataEngine().get_driver_options(year, event_round, session_type)


def main() -> None:
    load_dotenv()
    st.set_page_config(layout="wide", page_title="ApexSim AI")
    init_state()

    st.title("ApexSim AI")
    selected = render_sidebar()
    if selected is None:
        render_unavailable_state()
        return

    left, right = st.columns([0.65, 0.35], gap="large")
    dataset = st.session_state.dataset

    if dataset is None:
        with left:
            st.info("Select a FastF1 session and click Load Session to begin telemetry analysis.")
        with right:
            render_empty_metrics()
            render_ai_status()
        return

    waypoint_idx = min(st.session_state.waypoint_idx, len(dataset) - 1)
    current = dataset.iloc[waypoint_idx]
    active_selected = st.session_state.loaded_selection or selected

    with left:
        st.caption(render_session_caption(active_selected))
        render_track_map(dataset, current)
        render_strip_chart(dataset, current, "speed")
        render_strip_chart(dataset, current, "throttle")

    with right:
        render_metrics(current)
        render_ai_status()
        render_commentary(current, active_selected)

    if st.session_state.playing:
        st.session_state.waypoint_idx = (waypoint_idx + 1) % len(dataset)
        time.sleep(0.15)
        st.rerun()


def init_state() -> None:
    defaults = {
        "dataset": None,
        "waypoint_idx": 0,
        "playing": False,
        "commentary_log": [],
        "loaded_config": None,
        "loaded_selection": None,
        "last_insight_waypoint": None,
        "last_insight_text": "",
        "pending_ai_future": None,
        "pending_ai_waypoint": None,
        "ai_warning": "",
        "insight_mode": "IBM Granite",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar() -> dict[str, Any] | None:
    st.sidebar.header("FastF1 Session")
    year = int(
        st.sidebar.number_input(
            "Season",
            min_value=1950,
            max_value=date.today().year + 1,
            value=min(date.today().year, 2025),
            step=1,
        )
    )

    events = load_event_options(year)
    if not events:
        st.session_state.playing = False
        return None

    event_labels = [event.label for event in events]
    selected_label = st.sidebar.selectbox("Track/Event", event_labels)
    event = events[event_labels.index(selected_label)]

    sessions = load_session_options(year, event.round_number)
    if not sessions:
        st.session_state.playing = False
        return None

    session_type = st.sidebar.selectbox("Session", sessions)
    drivers = load_driver_options(year, event.round_number, session_type)
    if not drivers:
        st.session_state.playing = False
        return None

    driver1 = st.sidebar.selectbox("Driver 1", drivers, index=0)
    driver2_index = 1 if len(drivers) > 1 else 0
    driver2 = st.sidebar.selectbox("Driver 2", drivers, index=driver2_index)

    st.sidebar.header("Insights")
    insight_mode = st.sidebar.selectbox("Insight Mode", ["IBM Granite", "Rule fallback"])
    st.session_state.insight_mode = insight_mode

    selected = {
        "year": year,
        "event_round": event.round_number,
        "event_name": event.event_name,
        "event_label": event.label,
        "session_type": session_type,
        "driver1": driver1,
        "driver2": driver2,
        "insight_mode": insight_mode,
    }

    if st.sidebar.button("Load Session", type="primary", use_container_width=True):
        load_selected_session(selected)

    disabled = st.session_state.dataset is None
    playing = st.sidebar.toggle("Play", value=bool(st.session_state.playing), disabled=disabled)
    st.session_state.playing = bool(playing and not disabled)
    render_3d_export_control(selected)
    return selected


def load_event_options(year: int) -> list[EventOption]:
    try:
        with st.spinner("Discovering FastF1 events..."):
            return discover_events(year)
    except Exception as exc:
        st.sidebar.error(f"FastF1 could not provide the {year} event schedule: {exc}")
        return []


def load_session_options(year: int, event_round: int) -> list[str]:
    try:
        return discover_sessions(year, event_round)
    except Exception as exc:
        st.sidebar.error(f"FastF1 could not provide sessions for this event: {exc}")
        return []


def load_driver_options(year: int, event_round: int, session_type: str) -> list[str]:
    try:
        with st.spinner("Discovering FastF1 drivers..."):
            return discover_drivers(year, event_round, session_type)
    except Exception as exc:
        st.sidebar.error(f"FastF1 could not provide drivers for this session: {exc}")
        return []


def load_selected_session(selected: dict[str, Any]) -> None:
    config = (
        selected["year"],
        selected["event_round"],
        selected["session_type"],
        selected["driver1"],
        selected["driver2"],
    )
    with st.spinner("Loading FastF1 telemetry..."):
        try:
            dataset = DataEngine().load_session(
                int(selected["year"]),
                int(selected["event_round"]),
                str(selected["session_type"]),
                str(selected["driver1"]),
                str(selected["driver2"]),
            )
        except Exception as exc:
            st.session_state.playing = False
            st.error(str(exc))
            return

    st.session_state.dataset = dataset
    if st.session_state.loaded_config != config:
        st.session_state.waypoint_idx = 0
        st.session_state.commentary_log = []
        st.session_state.last_insight_waypoint = None
        st.session_state.last_insight_text = ""
        st.session_state.pending_ai_future = None
        st.session_state.pending_ai_waypoint = None
        st.session_state.ai_warning = ""
    st.session_state.loaded_config = config
    st.session_state.loaded_selection = selected.copy()


def render_unavailable_state() -> None:
    st.error(
        "FastF1 data discovery is unavailable. The app does not use static F1 data, "
        "so schedule/session/driver dropdowns require FastF1 cache or network access."
    )


def render_3d_export_control(selected: dict[str, Any]) -> None:
    loaded_selection = st.session_state.loaded_selection
    if st.session_state.dataset is None or loaded_selection is None:
        return

    payload = build_telemetry_3d_payload(st.session_state.dataset, loaded_selection)
    file_name = (
        f"apexsim-3d-{loaded_selection['year']}-{loaded_selection['event_round']}-"
        f"{loaded_selection['session_type']}-{loaded_selection['driver1']}-{loaded_selection['driver2']}.json"
    ).replace(" ", "-")
    st.sidebar.download_button(
        "Download 3D Telemetry JSON",
        data=json.dumps(payload, separators=(",", ":")),
        file_name=file_name,
        mime="application/json",
        use_container_width=True,
    )


def render_session_caption(selected: dict[str, Any]) -> str:
    return (
        f"{selected['year']} {selected['event_name']} - {selected['session_type']} | "
        f"Driver 1: {selected['driver1']} vs Driver 2: {selected['driver2']}"
    )


def render_track_map(dataset: pd.DataFrame, current: pd.Series) -> None:
    fig = go.Figure()
    driver1_x = float(current["baseline_x"])
    driver1_y = float(current["baseline_y"])
    driver2_x = float(current["driver_x"])
    driver2_y = float(current["driver_y"])
    current_gap = hypot(driver2_x - driver1_x, driver2_y - driver1_y)
    fig.add_trace(
        go.Scatter(
            x=dataset["baseline_x"],
            y=dataset["baseline_y"],
            mode="lines",
            name="Driver 1",
            line={"color": BASELINE_COLOR, "width": 3},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dataset["driver_x"],
            y=dataset["driver_y"],
            mode="lines",
            name="Driver 2",
            line={"color": DRIVER_COLOR, "width": 3},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[driver1_x],
            y=[driver1_y],
            mode="markers",
            name="Driver 1 position",
            marker={
                "color": BASELINE_COLOR,
                "size": 22,
                "symbol": "circle-open",
                "line": {"color": "#052e16", "width": 2},
            },
            hovertemplate=(
                "Driver 1<br>"
                f"Speed: {current['baseline_speed']:.1f} km/h<br>"
                f"Throttle: {current['baseline_throttle']:.0f}%<br>"
                f"Brake: {current['baseline_brake']:.1f}<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[driver2_x],
            y=[driver2_y],
            mode="markers",
            name="Driver 2 position",
            marker={
                "color": DRIVER_COLOR,
                "size": 13,
                "symbol": "diamond",
                "line": {"color": "#450a0a", "width": 2},
            },
            hovertemplate=(
                "Driver 2<br>"
                f"Speed: {current['driver_speed']:.1f} km/h<br>"
                f"Throttle: {current['driver_throttle']:.0f}%<br>"
                f"Brake: {current['driver_brake']:.1f}<extra></extra>"
            ),
        )
    )
    if current_gap > 0.05:
        fig.add_trace(
            go.Scatter(
                x=[driver1_x, driver2_x],
                y=[driver1_y, driver2_y],
                mode="lines",
                name="Current gap",
                line={"color": "#111827", "width": 2, "dash": "dot"},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    fig.update_layout(
        title="Track Map",
        height=430,
        margin={"l": 10, "r": 10, "t": 45, "b": 10},
        xaxis={"visible": False, "scaleanchor": "y", "scaleratio": 1},
        yaxis={"visible": False},
        legend={"orientation": "h", "y": 1.05},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_strip_chart(dataset: pd.DataFrame, current: pd.Series, metric: str) -> None:
    label = "Speed" if metric == "speed" else "Throttle"
    unit = "km/h" if metric == "speed" else "%"
    baseline_col = f"baseline_{metric}"
    driver_col = f"driver_{metric}"

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dataset["distance"],
            y=dataset[baseline_col],
            mode="lines",
            name="Driver 1",
            line={"color": BASELINE_COLOR, "width": 2},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=dataset["distance"],
            y=dataset[driver_col],
            mode="lines",
            name="Driver 2",
            line={"color": DRIVER_COLOR, "width": 2},
        )
    )
    fig.add_vline(x=float(current["distance"]), line_width=2, line_dash="dash", line_color="#111827")
    fig.update_layout(
        title=f"{label} Trace",
        height=260,
        margin={"l": 10, "r": 10, "t": 45, "b": 35},
        xaxis_title="Distance (m)",
        yaxis_title=f"{label} ({unit})",
        legend={"orientation": "h", "y": 1.08},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_empty_metrics() -> None:
    st.metric("Distance", "0 m")
    st.metric("D2 - D1 Speed", "+0.0 km/h")
    st.metric("Line Difference", "0.00 m")


def render_metrics(current: pd.Series) -> None:
    first, second, third = st.columns(3)
    first.metric("Distance", f"{current['distance']:.0f} m")
    second.metric("D2 - D1 Speed", f"{current['speed_delta']:+.1f} km/h")
    third.metric("Line Difference", f"{current['spatial_deviation']:.2f} m")

    driver1, driver2 = st.columns(2)
    driver1.metric("Driver 1 Speed", f"{current['baseline_speed']:.1f} km/h")
    driver1.metric("Driver 1 Throttle", f"{current['baseline_throttle']:.0f}%")
    driver2.metric("Driver 2 Speed", f"{current['driver_speed']:.1f} km/h")
    driver2.metric("Driver 2 Throttle", f"{current['driver_throttle']:.0f}%")


def render_ai_status() -> None:
    if st.session_state.insight_mode == "IBM Granite":
        configured = GraniteInsightProvider().is_configured
        label = "configured" if configured else "not configured, using fallback until credentials are set"
        st.caption(f"IBM Granite: {label}")
    else:
        st.caption("Insight mode: deterministic rule fallback")
    if st.session_state.ai_warning:
        st.warning(st.session_state.ai_warning)


def render_commentary(current: pd.Series, selected: dict[str, Any]) -> None:
    completed = poll_pending_ai_insight()
    if completed is not None:
        waypoint_idx, insight = completed
        append_commentary(waypoint_idx, insight)

    if st.session_state.playing:
        insight, generated = get_step_insight(current, selected)
        if generated:
            append_commentary(int(current["idx"]), insight)

    st.subheader("Live Commentary")
    if st.session_state.pending_ai_future is not None:
        st.caption(f"IBM insight running for WP {int(st.session_state.pending_ai_waypoint):03d}; playback continues.")
    with st.container(height=500):
        for entry in reversed(st.session_state.commentary_log):
            st.markdown(entry)


def append_commentary(waypoint_idx: int, insight: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"`{timestamp}` WP {waypoint_idx:03d}: {insight}"
    st.session_state.commentary_log.append(entry)
    st.session_state.commentary_log = st.session_state.commentary_log[-250:]


def get_step_insight(current: pd.Series, selected: dict[str, Any]) -> tuple[str, bool]:
    waypoint_idx = int(current["idx"])
    should_generate = (
        st.session_state.last_insight_waypoint is None
        or waypoint_idx % AI_STEP_INTERVAL == 0
        or not st.session_state.last_insight_text
    )
    if not should_generate:
        return str(st.session_state.last_insight_text), False

    context = InsightContext(
        year=int(selected["year"]),
        event=selected["event_name"],
        session_type=str(selected["session_type"]),
        driver1=str(selected["driver1"]),
        driver2=str(selected["driver2"]),
    )

    if selected["insight_mode"] == "IBM Granite":
        return submit_granite_insight(current, context)

    provider = RuleFallbackInsightProvider()
    engine = InsightEngine(provider=provider)
    insight = engine.get_live_coaching(
        current,
        context=context,
    )
    st.session_state.ai_warning = engine.last_error or ""
    st.session_state.last_insight_waypoint = waypoint_idx
    st.session_state.last_insight_text = insight
    return insight, True


def submit_granite_insight(current: pd.Series, context: InsightContext) -> tuple[str, bool]:
    pending: Future[tuple[int, str, str]] | None = st.session_state.pending_ai_future
    if pending is not None and not pending.done():
        return str(st.session_state.last_insight_text), False

    waypoint = current.to_dict()
    waypoint_idx = int(waypoint["idx"])
    future = get_insight_executor().submit(generate_granite_insight, waypoint, context.as_dict())
    st.session_state.pending_ai_future = future
    st.session_state.pending_ai_waypoint = waypoint_idx
    st.session_state.last_insight_waypoint = waypoint_idx
    return str(st.session_state.last_insight_text), False


def poll_pending_ai_insight() -> tuple[int, str] | None:
    pending: Future[tuple[int, str, str]] | None = st.session_state.pending_ai_future
    if pending is None or not pending.done():
        return None

    st.session_state.pending_ai_future = None
    st.session_state.pending_ai_waypoint = None
    try:
        waypoint_idx, insight, warning = pending.result()
    except Exception as exc:
        st.session_state.ai_warning = str(exc)
        return None

    st.session_state.ai_warning = warning
    st.session_state.last_insight_waypoint = waypoint_idx
    st.session_state.last_insight_text = insight
    return waypoint_idx, insight


def generate_granite_insight(waypoint: dict[str, Any], context: dict[str, Any]) -> tuple[int, str, str]:
    engine = InsightEngine(provider=GraniteInsightProvider())
    insight = engine.get_live_coaching(
        waypoint,
        context=context,
    )
    return int(waypoint["idx"]), insight, engine.last_error or ""


if __name__ == "__main__":
    main()
