"""ApexSim AI – FastAPI backend.

Exposes the FastF1 data engine and insight engine as REST endpoints
consumed by the Next.js frontend.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .data_engine import DataEngine, TelemetryUnavailableError
from .insight_engine import (
    GraniteInsightProvider,
    InsightContext,
    InsightEngine,
    RuleFallbackInsightProvider,
)
from .telemetry_export import build_telemetry_3d_payload

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Lifespan – eagerly create the DataEngine once
# ---------------------------------------------------------------------------

_engine: DataEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    _engine = DataEngine()
    yield


app = FastAPI(title="ApexSim AI API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow requests from Vercel and localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


def engine() -> DataEngine:
    assert _engine is not None
    return _engine


# ---------------------------------------------------------------------------
# Event / Session / Driver discovery
# ---------------------------------------------------------------------------


@app.get("/api/events")
def get_events(year: int = Query(...)):
    try:
        options = engine().get_event_options(year)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return [
        {
            "round_number": o.round_number,
            "event_name": o.event_name,
            "location": o.location,
            "country": o.country,
            "label": o.label,
        }
        for o in options
    ]


@app.get("/api/sessions")
def get_sessions(year: int = Query(...), event_round: int = Query(...)):
    try:
        return engine().get_session_options(year, event_round)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/drivers")
def get_drivers(
    year: int = Query(...),
    event_round: int = Query(...),
    session_type: str = Query(...),
):
    try:
        return engine().get_driver_options(year, event_round, session_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


# ---------------------------------------------------------------------------
# Telemetry loading – returns the 3-D export payload directly
# ---------------------------------------------------------------------------


@app.get("/api/telemetry")
def get_telemetry(
    year: int = Query(...),
    event_round: int = Query(...),
    session_type: str = Query(...),
    driver1: str = Query(...),
    driver2: str = Query(...),
):
    try:
        dataset = engine().load_session(
            year, event_round, session_type, driver1, driver2
        )
    except TelemetryUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    metadata: dict[str, Any] = {
        "year": year,
        "event_round": event_round,
        "event_name": f"Round {event_round}",
        "session_type": session_type,
        "driver1": driver1,
        "driver2": driver2,
    }
    return build_telemetry_3d_payload(dataset, metadata)


# ---------------------------------------------------------------------------
# Insight generation
# ---------------------------------------------------------------------------


class InsightRequest(BaseModel):
    waypoint: dict[str, Any]
    insight_mode: str = "IBM Granite"
    year: int | None = None
    event: str | None = None
    session_type: str | None = None
    driver1: str | None = None
    driver2: str | None = None


class LapInsightRequest(BaseModel):
    lap: int
    avg_speed_delta: float
    avg_throttle_delta: float
    max_spatial_deviation: float
    avg_baseline_speed: float
    avg_driver_speed: float
    avg_baseline_throttle: float
    avg_driver_throttle: float
    max_baseline_brake: float
    max_driver_brake: float
    insight_mode: str = "IBM Granite"
    year: int | None = None
    event: str | None = None
    session_type: str | None = None
    driver1: str | None = None
    driver2: str | None = None


@app.post("/api/insight")
def get_insight(body: InsightRequest):
    context = InsightContext(
        year=body.year,
        event=body.event,
        session_type=body.session_type,
        driver1=body.driver1,
        driver2=body.driver2,
    )
    if body.insight_mode == "IBM Granite":
        provider: Any = GraniteInsightProvider()
    else:
        provider = RuleFallbackInsightProvider()

    eng = InsightEngine(provider=provider)
    insight = eng.get_live_coaching(body.waypoint, context=context)
    return {
        "insight": insight,
        "warning": eng.last_error or "",
        "configured": GraniteInsightProvider().is_configured,
    }


@app.post("/api/lap-insight")
def get_lap_insight(body: LapInsightRequest):
    context = InsightContext(
        year=body.year,
        event=body.event,
        session_type=body.session_type,
        driver1=body.driver1,
        driver2=body.driver2,
    )
    if body.insight_mode == "IBM Granite":
        provider: Any = GraniteInsightProvider()
    else:
        provider = RuleFallbackInsightProvider()

    eng = InsightEngine(provider=provider)
    insight = eng.get_lap_coaching(body, context=context)
    return {
        "insight": insight,
        "warning": eng.last_error or "",
        "configured": GraniteInsightProvider().is_configured,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok", "granite_configured": GraniteInsightProvider().is_configured}
