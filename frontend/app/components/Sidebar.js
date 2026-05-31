"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchEvents,
  fetchSessions,
  fetchDrivers,
  fetchHealth,
} from "../lib/api";

export default function Sidebar({ onLoadSession, telemetryLoaded, playing, onTogglePlay, insightMode, onInsightModeChange }) {
  const currentYear = Math.min(new Date().getFullYear(), 2025);
  const [year, setYear] = useState(currentYear);
  const [events, setEvents] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState("");
  const [drivers, setDrivers] = useState([]);
  const [driver1, setDriver1] = useState("");
  const [driver2, setDriver2] = useState("");
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [graniteConfigured, setGraniteConfigured] = useState(false);

  /* Health check on mount */
  useEffect(() => {
    fetchHealth()
      .then((h) => setGraniteConfigured(h.granite_configured))
      .catch(() => {});
  }, []);

  /* Load events when year changes */
  useEffect(() => {
    let cancelled = false;
    setLoading("Discovering events…");
    setError("");
    fetchEvents(year)
      .then((data) => {
        if (cancelled) return;
        setEvents(data);
        if (data.length > 0) {
          setSelectedEvent(data[0]);
        }
        setLoading("");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
        setEvents([]);
        setLoading("");
      });
    return () => { cancelled = true; };
  }, [year]);

  /* Load sessions when event changes */
  useEffect(() => {
    if (!selectedEvent) {
      setSessions([]);
      return;
    }
    let cancelled = false;
    fetchSessions(year, selectedEvent.round_number)
      .then((data) => {
        if (cancelled) return;
        setSessions(data);
        if (data.length > 0) setSelectedSession(data[0]);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => { cancelled = true; };
  }, [year, selectedEvent]);

  /* Load drivers when session changes */
  useEffect(() => {
    if (!selectedEvent || !selectedSession) {
      setDrivers([]);
      return;
    }
    let cancelled = false;
    setLoading("Discovering drivers…");
    fetchDrivers(year, selectedEvent.round_number, selectedSession)
      .then((data) => {
        if (cancelled) return;
        setDrivers(data);
        if (data.length > 0) setDriver1(data[0]);
        if (data.length > 1) setDriver2(data[1]);
        setLoading("");
      })
      .catch((err) => {
        if (!cancelled) {
          setDrivers([]);
          setLoading("");
          setError(err.message);
        }
      });
    return () => { cancelled = true; };
  }, [year, selectedEvent, selectedSession]);

  const handleLoad = useCallback(() => {
    if (!selectedEvent || !selectedSession || !driver1 || !driver2) return;
    onLoadSession({
      year,
      eventRound: selectedEvent.round_number,
      eventName: selectedEvent.event_name,
      eventLabel: selectedEvent.label,
      sessionType: selectedSession,
      driver1,
      driver2,
      insightMode,
    });
  }, [year, selectedEvent, selectedSession, driver1, driver2, insightMode, onLoadSession]);

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <h1>ApexSim F1</h1>
      </div>

      {/* FastF1 Session Section */}
      <div className="sidebar-section">
        <h2>FastF1 Session</h2>

        <div className="field">
          <label htmlFor="year-select">Season</label>
          <input
            id="year-select"
            type="number"
            min={1950}
            max={new Date().getFullYear() + 1}
            value={year}
            onChange={(e) => setYear(parseInt(e.target.value, 10))}
          />
        </div>

        <div className="field">
          <label htmlFor="event-select">Track / Event</label>
          <select
            id="event-select"
            value={selectedEvent?.round_number || ""}
            onChange={(e) => {
              const ev = events.find(
                (x) => x.round_number === parseInt(e.target.value, 10)
              );
              setSelectedEvent(ev || null);
            }}
            disabled={events.length === 0}
          >
            {events.map((ev) => (
              <option key={ev.round_number} value={ev.round_number}>
                {ev.label}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="session-select">Session</label>
          <select
            id="session-select"
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            disabled={sessions.length === 0}
          >
            {sessions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="driver1-select">Driver 1</label>
          <select
            id="driver1-select"
            value={driver1}
            onChange={(e) => setDriver1(e.target.value)}
            disabled={drivers.length === 0}
          >
            {drivers.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="driver2-select">Driver 2</label>
          <select
            id="driver2-select"
            value={driver2}
            onChange={(e) => setDriver2(e.target.value)}
            disabled={drivers.length === 0}
          >
            {drivers.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Insights */}
      <div className="sidebar-section">
        <h2>Insights</h2>
        <div className="field">
          <label htmlFor="insight-mode">Insight Mode</label>
          <select
            id="insight-mode"
            value={insightMode}
            onChange={(e) => onInsightModeChange(e.target.value)}
          >
            <option value="IBM Granite">IBM Granite</option>
            <option value="Rule fallback">Rule fallback</option>
          </select>
        </div>
      </div>

      {/* Actions */}
      <div className="sidebar-section">
        <button
          className="btn btn-primary"
          onClick={handleLoad}
          disabled={!selectedEvent || !selectedSession || !driver1 || !driver2}
        >
          {loading ? (
            <>
              <span className="spinner" /> {loading}
            </>
          ) : (
            "Load Session"
          )}
        </button>

        <div className="toggle-group">
          <span>Play</span>
          <button
            className={`toggle ${playing ? "active" : ""}`}
            onClick={onTogglePlay}
            disabled={!telemetryLoaded}
            aria-label="Toggle playback"
          />
        </div>
      </div>

      {/* Status */}
      {error && <div className="error-box">{error}</div>}

      <div className="ai-status">
        <span className={`dot ${graniteConfigured ? "active" : "inactive"}`} />
        {graniteConfigured
          ? "IBM Granite configured"
          : "Granite unconfigured, using fallback"}
      </div>
    </aside>
  );
}
