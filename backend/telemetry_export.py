from __future__ import annotations

from typing import Any

import pandas as pd


EXPORT_COLUMNS = (
    "idx",
    "distance",
    "lap",
    "baseline_x",
    "baseline_y",
    "baseline_speed",
    "baseline_throttle",
    "baseline_brake",
    "driver_x",
    "driver_y",
    "driver_speed",
    "driver_throttle",
    "driver_brake",
    "speed_delta",
    "throttle_delta",
    "spatial_deviation",
)


def build_telemetry_3d_payload(dataset: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
    """Return a compact JSON-serializable payload for the 3D telemetry prototype."""
    missing = [column for column in EXPORT_COLUMNS if column not in dataset.columns]
    if missing:
        raise ValueError(f"Dataset is missing required 3D export column(s): {', '.join(missing)}")

    points = []
    for row in dataset.loc[:, EXPORT_COLUMNS].itertuples(index=False):
        points.append(
            {
                "idx": int(row.idx),
                "distance": float(row.distance),
                "lap": int(row.lap),
                "driver1": {
                    "x": float(row.baseline_x),
                    "y": float(row.baseline_y),
                    "speed": float(row.baseline_speed),
                    "throttle": float(row.baseline_throttle),
                    "brake": float(row.baseline_brake),
                },
                "driver2": {
                    "x": float(row.driver_x),
                    "y": float(row.driver_y),
                    "speed": float(row.driver_speed),
                    "throttle": float(row.driver_throttle),
                    "brake": float(row.driver_brake),
                },
                "deltas": {
                    "speed": float(row.speed_delta),
                    "throttle": float(row.throttle_delta),
                    "line": float(row.spatial_deviation),
                },
            }
        )

    return {
        "version": 1,
        "source": "FastF1",
        "metadata": {
            "year": metadata.get("year"),
            "event": metadata.get("event_name") or metadata.get("event"),
            "session": metadata.get("session_type"),
            "driver1": metadata.get("driver1"),
            "driver2": metadata.get("driver2"),
        },
        "points": points,
    }
