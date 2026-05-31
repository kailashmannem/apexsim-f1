"use client";

import { useState, useCallback, useRef } from "react";
import Sidebar from "./components/Sidebar";
import TrackMap3D from "./components/TrackMap3D";
import MetricsPanel from "./components/MetricsPanel";
import LiveCommentary from "./components/LiveCommentary";
import { fetchTelemetry, fetchLapInsight } from "./lib/api";

const computeLapSummary = (points, lapNumber) => {
  const lapPoints = points.filter((p) => p.lap === lapNumber);
  if (lapPoints.length === 0) return null;

  const sum = lapPoints.reduce(
    (acc, p) => {
      acc.speed_delta += p.deltas.speed;
      acc.throttle_delta += p.deltas.throttle;
      acc.baseline_speed += p.driver1.speed;
      acc.driver_speed += p.driver2.speed;
      acc.baseline_throttle += p.driver1.throttle;
      acc.driver_throttle += p.driver2.throttle;
      acc.max_spatial_deviation = Math.max(acc.max_spatial_deviation, p.deltas.line);
      acc.max_baseline_brake = Math.max(acc.max_baseline_brake, p.driver1.brake);
      acc.max_driver_brake = Math.max(acc.max_driver_brake, p.driver2.brake);
      return acc;
    },
    {
      speed_delta: 0,
      throttle_delta: 0,
      baseline_speed: 0,
      driver_speed: 0,
      baseline_throttle: 0,
      driver_throttle: 0,
      max_spatial_deviation: 0,
      max_baseline_brake: 0,
      max_driver_brake: 0,
    }
  );

  const count = lapPoints.length;
  return {
    lap: lapNumber,
    avg_speed_delta: sum.speed_delta / count,
    avg_throttle_delta: sum.throttle_delta / count,
    max_spatial_deviation: sum.max_spatial_deviation,
    avg_baseline_speed: sum.baseline_speed / count,
    avg_driver_speed: sum.driver_speed / count,
    avg_baseline_throttle: sum.baseline_throttle / count,
    avg_driver_throttle: sum.driver_throttle / count,
    max_baseline_brake: sum.max_baseline_brake,
    max_driver_brake: sum.max_driver_brake,
  };
};

export default function Home() {
  const [payload, setPayload] = useState(null);
  const [sessionMeta, setSessionMeta] = useState(null);
  const [waypointIdx, setWaypointIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [commentary, setCommentary] = useState([]);
  const [pendingInsight, setPendingInsight] = useState(null);
  const [aiWarning, setAiWarning] = useState("");
  const [loadingSession, setLoadingSession] = useState(false);
  const [loadError, setLoadError] = useState("");

  const analyzedLaps = useRef(new Set());
  const isFetchingInsight = useRef(false);

  /* ── Load Session ──────────────────────────────────────────── */
  const handleLoadSession = useCallback(async (selected) => {
    setLoadingSession(true);
    setLoadError("");
    setPlaying(false);
    try {
      const data = await fetchTelemetry(
        selected.year,
        selected.eventRound,
        selected.sessionType,
        selected.driver1,
        selected.driver2
      );
      setPayload(data);
      setSessionMeta(selected);
      setWaypointIdx(0);
      setCommentary([]);
      analyzedLaps.current.clear();
      isFetchingInsight.current = false;
    } catch (err) {
      setLoadError(err.message);
    } finally {
      setLoadingSession(false);
    }
  }, []);

  /* ── Frame advance from the 3D component ───────────────────── */
  const handleFrameAdvance = useCallback(
    (frame) => {
      setWaypointIdx(frame);

      if (!payload || !payload.points) return;
      
      const point = payload.points[frame];
      if (!point) return;
      const currentLap = point.lap || 1;

      /* Generate insight when entering an unanalyzed lap */
      if (!analyzedLaps.current.has(currentLap) && !isFetchingInsight.current) {
        analyzedLaps.current.add(currentLap);
        
        const lapSummary = computeLapSummary(payload.points, currentLap);
        if (!lapSummary) return;

        setPendingInsight(currentLap);
        isFetchingInsight.current = true;
        
        fetchLapInsight(lapSummary, "IBM Granite", {
          year: sessionMeta?.year,
          event: sessionMeta?.eventName,
          session_type: sessionMeta?.sessionType,
          driver1: sessionMeta?.driver1,
          driver2: sessionMeta?.driver2,
        })
          .then((res) => {
            const now = new Date();
            const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
            setCommentary((prev) => [
              ...prev.slice(-249),
              { timestamp: ts, lap: currentLap, text: res.insight },
            ]);
            setAiWarning(res.warning || "");
          })
          .catch((err) => {
            setAiWarning(err.message);
          })
          .finally(() => {
            setPendingInsight(null);
            isFetchingInsight.current = false;
          });
      }
    },
    [payload, sessionMeta]
  );

  /* ── Current point ─────────────────────────────────────────── */
  const currentPoint =
    payload && payload.points && payload.points.length > waypointIdx
      ? payload.points[waypointIdx]
      : null;

  /* ── Session caption ───────────────────────────────────────── */
  const caption = sessionMeta
    ? `${sessionMeta.year} ${sessionMeta.eventName} – ${sessionMeta.sessionType} | Driver 1: ${sessionMeta.driver1} vs Driver 2: ${sessionMeta.driver2}`
    : "";

  return (
    <div className="app-layout">
      <Sidebar
        onLoadSession={handleLoadSession}
        telemetryLoaded={!!payload}
        playing={playing}
        onTogglePlay={() => setPlaying((p) => !p)}
      />

      <div className="main-content">
        {/* ── Left Panel: Visualizations ──────────────────────── */}
        <div className="left-panel">
          {loadingSession && (
            <div className="info-box">
              <span className="spinner" /> Loading FastF1 telemetry…
            </div>
          )}
          {loadError && <div className="error-box">{loadError}</div>}

          {!payload && !loadingSession && (
            <div className="info-box">
              Select a FastF1 session and click Load Session to begin telemetry
              analysis.
            </div>
          )}

          {payload && (
            <>
              {caption && <div className="session-caption">{caption}</div>}
              <TrackMap3D
                payload={payload}
                waypointIdx={waypointIdx}
                playing={playing}
                onFrameAdvance={handleFrameAdvance}
              />
            </>
          )}
        </div>

        {/* ── Right Panel: Metrics & Commentary ──────────────── */}
        <div className="right-panel">
          <MetricsPanel 
            point={currentPoint} 
            totalLapCount={
              payload?.points?.length > 0 
                ? Math.max(...payload.points.map(p => p.lap || 1))
                : 1
            }
          />

          {aiWarning && <div className="ai-warning">{aiWarning}</div>}

          <LiveCommentary
            entries={commentary}
            pendingWaypoint={pendingInsight}
          />
        </div>
      </div>
    </div>
  );
}
