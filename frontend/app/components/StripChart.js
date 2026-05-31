"use client";

import dynamic from "next/dynamic";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const BASELINE_COLOR = "#16a34a";
const DRIVER_COLOR = "#dc2626";
const CURSOR_COLOR = "#e2e8f0";

/**
 * Renders a Speed or Throttle strip chart comparing two drivers over lap distance.
 *
 * @param {object} props
 * @param {object} props.payload – Full 3D telemetry payload
 * @param {number} props.waypointIdx – Current waypoint index
 * @param {"speed"|"throttle"} props.metric – Which metric to plot
 */
export default function StripChart({ payload, waypointIdx, metric = "speed" }) {
  if (!payload || !payload.points || payload.points.length === 0) {
    return null;
  }

  const points = payload.points;
  const label = metric === "speed" ? "Speed" : "Throttle";
  const unit = metric === "speed" ? "km/h" : "%";

  const distances = points.map((p) => p.distance);
  const driver1Values = points.map((p) => p.driver1[metric]);
  const driver2Values = points.map((p) => p.driver2[metric]);

  const currentDistance =
    waypointIdx < points.length ? points[waypointIdx].distance : 0;

  const data = [
    {
      x: distances,
      y: driver1Values,
      mode: "lines",
      name: "Driver 1",
      line: { color: BASELINE_COLOR, width: 2 },
    },
    {
      x: distances,
      y: driver2Values,
      mode: "lines",
      name: "Driver 2",
      line: { color: DRIVER_COLOR, width: 2 },
    },
  ];

  const layout = {
    title: { text: `${label} Trace`, font: { size: 13, color: "#94a3b8" } },
    height: 220,
    margin: { l: 48, r: 16, t: 40, b: 36 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { family: "Inter, sans-serif", color: "#94a3b8", size: 11 },
    xaxis: {
      title: { text: "Distance (m)", font: { size: 11 } },
      color: "#64748b",
      gridcolor: "rgba(148,163,184,0.08)",
      zerolinecolor: "rgba(148,163,184,0.08)",
    },
    yaxis: {
      title: { text: `${label} (${unit})`, font: { size: 11 } },
      color: "#64748b",
      gridcolor: "rgba(148,163,184,0.08)",
      zerolinecolor: "rgba(148,163,184,0.08)",
    },
    legend: { orientation: "h", y: 1.12, font: { size: 11 } },
    shapes: [
      {
        type: "line",
        x0: currentDistance,
        x1: currentDistance,
        y0: 0,
        y1: 1,
        yref: "paper",
        line: { color: CURSOR_COLOR, width: 2, dash: "dash" },
      },
    ],
  };

  const config = {
    displayModeBar: false,
    responsive: true,
  };

  return (
    <div className="chart-container">
      <Plot
        data={data}
        layout={layout}
        config={config}
        style={{ width: "100%", height: "100%" }}
        useResizeHandler
      />
    </div>
  );
}
