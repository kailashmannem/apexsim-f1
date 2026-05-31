"use client";

/**
 * Displays the key telemetry metrics for the current waypoint.
 */
export default function MetricsPanel({ point, totalLapCount }) {
  if (!point) {
    return (
      <>
        <div className="metrics-grid">
          <MetricCard label="Distance" value="0 m" />
          <MetricCard label="D2 − D1 Speed" value="+0.0 km/h" />
          <MetricCard label="Line Difference" value="0.00 m" />
        </div>
        <div className="driver-metrics">
          <DriverCard driver={1} speed="0.0" throttle="0" />
          <DriverCard driver={2} speed="0.0" throttle="0" />
        </div>
      </>
    );
  }

  const speedDelta = point.deltas.speed;
  const lineDiff = point.deltas.line;
  const lap = point.lap ?? 1;
  const totalLaps = totalLapCount ?? null;

  return (
    <>
      <div className="metrics-grid">
        <MetricCard label="Distance" value={`${point.distance.toFixed(0)} m`} />
        <MetricCard
          label="D2 − D1 Speed"
          value={`${speedDelta >= 0 ? "+" : ""}${speedDelta.toFixed(1)} km/h`}
        />
        <MetricCard label="Line Difference" value={`${lineDiff.toFixed(2)} m`} />
        {totalLaps && totalLaps > 1 && (
          <MetricCard label="Lap" value={`${lap} / ${totalLaps}`} />
        )}
      </div>
      <div className="driver-metrics">
        <DriverCard
          driver={1}
          speed={point.driver1.speed.toFixed(1)}
          throttle={point.driver1.throttle.toFixed(0)}
        />
        <DriverCard
          driver={2}
          speed={point.driver2.speed.toFixed(1)}
          throttle={point.driver2.throttle.toFixed(0)}
        />
      </div>
    </>
  );
}

function MetricCard({ label, value }) {
  return (
    <div className="metric-card">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </div>
  );
}

function DriverCard({ driver, speed, throttle }) {
  return (
    <div className={`driver-metric driver${driver}`}>
      <div className="driver-label">Driver {driver}</div>
      <div className="stat">
        <span className="stat-name">Speed</span>
        <span className="stat-value">{speed} km/h</span>
      </div>
      <div className="stat">
        <span className="stat-name">Throttle</span>
        <span className="stat-value">{throttle}%</span>
      </div>
    </div>
  );
}
