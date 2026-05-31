from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


LOGGER = logging.getLogger(__name__)
WAYPOINT_COUNT = 500
REQUIRED_TELEMETRY_COLUMNS = ("X", "Y", "Speed", "Throttle", "Brake")
RACE_SESSION_CODES = {"R", "S"}
RACE_WAYPOINTS_PER_LAP = 150

SESSION_TYPE_MAP = {
    "Practice 1": "FP1",
    "Practice 2": "FP2",
    "Practice 3": "FP3",
    "Qualifying": "Q",
    "Sprint": "S",
    "Sprint Qualifying": "SQ",
    "Race": "R",
    "FP1": "FP1",
    "FP2": "FP2",
    "FP3": "FP3",
    "Q": "Q",
    "S": "S",
    "SQ": "SQ",
    "R": "R",
}


class TelemetryUnavailableError(Exception):
    """Raised when telemetry is missing or incomplete for a driver."""


@dataclass(frozen=True)
class WaypointRow:
    idx: int
    distance: float
    baseline_x: float
    baseline_y: float
    baseline_speed: float
    baseline_throttle: float
    baseline_brake: float
    driver_x: float
    driver_y: float
    driver_speed: float
    driver_throttle: float
    driver_brake: float
    speed_delta: float
    throttle_delta: float
    spatial_deviation: float
    lap: int = 1


@dataclass(frozen=True)
class WeatherStats:
    track_temperature: float = 25.0
    wind_speed: float = 0.0
    wind_direction: float = 0.0


@dataclass(frozen=True)
class EventOption:
    round_number: int
    event_name: str
    location: str
    country: str
    label: str


def normalize_session_type(session_type: str) -> str:
    """Return the FastF1 session code for a UI label or existing code."""
    try:
        return SESSION_TYPE_MAP[session_type]
    except KeyError as exc:
        valid = ", ".join(sorted(SESSION_TYPE_MAP))
        raise ValueError(f"Invalid session_type '{session_type}'. Expected one of: {valid}") from exc


class DataEngine:
    def __init__(self, cache_dir: str | Path = "f1_cache") -> None:
        self.cache_dir = Path(os.getenv("FASTF1_CACHE_DIR", str(cache_dir)))

    def get_event_schedule(self, year: int) -> pd.DataFrame:
        """Return the FastF1 event schedule for a season."""
        self._enable_cache()
        try:
            import fastf1

            schedule = fastf1.get_event_schedule(int(year), include_testing=False)
        except ValueError as exc:
            raise ValueError(f"FastF1 could not load the {year} event schedule") from exc
        except Exception as exc:
            raise RuntimeError(f"FastF1 event schedule discovery failed for {year}: {exc}") from exc

        schedule_df = pd.DataFrame(schedule).copy()
        if schedule_df.empty:
            raise ValueError(f"FastF1 returned no events for {year}")
        return schedule_df

    def get_event_options(self, year: int) -> list[EventOption]:
        """Build event dropdown options from FastF1's schedule data."""
        schedule = self.get_event_schedule(year)
        required = ("RoundNumber", "EventName")
        missing = [column for column in required if column not in schedule.columns]
        if missing:
            raise ValueError(f"FastF1 schedule is missing required column(s): {', '.join(missing)}")

        options: list[EventOption] = []
        for _, row in schedule.sort_values("RoundNumber").iterrows():
            round_number = int(row["RoundNumber"])
            event_name = str(row["EventName"])
            location = self._string_or_empty(row.get("Location", ""))
            country = self._string_or_empty(row.get("Country", ""))
            suffix_parts = [part for part in (location, country) if part]
            suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
            options.append(
                EventOption(
                    round_number=round_number,
                    event_name=event_name,
                    location=location,
                    country=country,
                    label=f"Round {round_number}: {event_name}{suffix}",
                )
            )
        return options

    def get_session_options(self, year: int, event_round_or_name: int | str) -> list[str]:
        """Return valid session names for one event from FastF1 schedule fields."""
        event = self._get_event(year, event_round_or_name)
        sessions = []
        for index in range(1, 6):
            value = self._string_or_empty(event.get(f"Session{index}", ""))
            if value:
                sessions.append(value)
        if not sessions:
            raise ValueError(f"FastF1 returned no sessions for event '{event_round_or_name}'")
        return sessions

    def get_driver_options(self, year: int, event_round_or_name: int | str, session_type: str) -> list[str]:
        """Return driver abbreviations present in the selected FastF1 session."""
        session = self._load_fastf1_session(year, event_round_or_name, session_type, telemetry=False, weather=False)
        laps = getattr(session, "laps", None)
        if laps is None or len(laps) == 0:
            raise TelemetryUnavailableError(
                f"No lap data available for {year} event '{event_round_or_name}' session '{session_type}'"
            )

        laps_df = pd.DataFrame(laps)
        for column in ("Driver", "DriverNumber"):
            if column in laps_df.columns:
                values = sorted(
                    {
                        str(value)
                        for value in laps_df[column].dropna().tolist()
                        if str(value).strip()
                    }
                )
                if values:
                    return values
        raise ValueError("FastF1 lap data does not include driver identifiers")

    def load_session(
        self,
        year: int,
        location: str,
        session_type: str,
        ref_driver: str,
        user_driver: str,
    ) -> tuple[pd.DataFrame, WeatherStats]:
        """Load a FastF1 session and return a waypoint comparison dataset.

        For race/sprint sessions all common laps are concatenated; for other
        session types the fastest lap of each driver is used.
        """
        self._enable_cache()
        session = self._load_fastf1_session(year, location, session_type, telemetry=True, weather=True)

        if self._is_race_session(session_type):
            baseline_tel, driver_tel, lap_boundaries = self._build_race_telemetry(
                session, ref_driver, user_driver,
            )
            wp_count = min(RACE_WAYPOINTS_PER_LAP * len(lap_boundaries), 15000)
            dataset = self._resample(baseline_tel, driver_tel, waypoint_count=wp_count)
            dataset["lap"] = self._assign_lap_numbers(dataset["distance"], lap_boundaries)
        else:
            baseline_lap, driver_lap = self._extract_laps(session, ref_driver, user_driver)
            baseline_tel = self._validate_telemetry(baseline_lap, ref_driver)
            driver_tel = self._validate_telemetry(driver_lap, user_driver)
            dataset = self._resample(baseline_tel, driver_tel)
            dataset["lap"] = 1

        weather = self._extract_weather(session)
        return dataset, weather

    def _is_race_session(self, session_type: str) -> bool:
        """Return True if the session type corresponds to a race or sprint."""
        try:
            code = normalize_session_type(session_type)
        except ValueError:
            code = session_type
        return code in RACE_SESSION_CODES

    def _build_race_telemetry(
        self,
        session: Any,
        ref_driver: str,
        user_driver: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[float, float, int]]]:
        """Concatenate telemetry for all common laps in a race/sprint session."""
        ref_all = self._get_all_laps(session, ref_driver)
        user_all = self._get_all_laps(session, user_driver)

        ref_nums = set(ref_all["LapNumber"].dropna().astype(int))
        user_nums = set(user_all["LapNumber"].dropna().astype(int))
        common = sorted(ref_nums & user_nums)

        if not common:
            raise TelemetryUnavailableError(
                f"No common laps between '{ref_driver}' and '{user_driver}'"
            )

        ref_parts: list[pd.DataFrame] = []
        user_parts: list[pd.DataFrame] = []
        lap_boundaries: list[tuple[float, float, int]] = []
        cumulative = 0.0

        for lap_num in common:
            ref_lap = ref_all[ref_all["LapNumber"] == lap_num].iloc[0]
            user_lap = user_all[user_all["LapNumber"] == lap_num].iloc[0]

            try:
                ref_tel = self._validate_telemetry(ref_lap, f"{ref_driver} L{lap_num}")
                user_tel = self._validate_telemetry(user_lap, f"{user_driver} L{lap_num}")
            except (TelemetryUnavailableError, ValueError):
                LOGGER.warning("Skipping lap %d \u2013 telemetry unavailable", lap_num)
                continue

            ref_tel = ref_tel.copy()
            user_tel = user_tel.copy()
            ref_tel["Distance"] = ref_tel["Distance"] + cumulative
            user_tel["Distance"] = user_tel["Distance"] + cumulative

            lap_end = max(float(ref_tel["Distance"].max()), float(user_tel["Distance"].max()))
            lap_boundaries.append((cumulative, lap_end, int(lap_num)))
            cumulative = lap_end

            ref_parts.append(ref_tel)
            user_parts.append(user_tel)

        if not ref_parts:
            raise TelemetryUnavailableError("No laps yielded valid telemetry")

        return (
            pd.concat(ref_parts, ignore_index=True),
            pd.concat(user_parts, ignore_index=True),
            lap_boundaries,
        )

    def _get_all_laps(self, session: Any, driver: str) -> Any:
        """Return all laps for a driver, raising if empty."""
        try:
            laps = session.laps.pick_driver(driver)
        except Exception as exc:
            raise ValueError(f"Invalid driver '{driver}' or missing lap data") from exc
        if laps is None or len(laps) == 0:
            raise TelemetryUnavailableError(f"No laps found for driver '{driver}'")
        return laps

    @staticmethod
    def _assign_lap_numbers(
        distances: pd.Series, lap_boundaries: list[tuple[float, float, int]]
    ) -> np.ndarray:
        """Map resampled distance values to their originating lap number."""
        laps = np.ones(len(distances), dtype=int)
        for start, end, lap_num in lap_boundaries:
            mask = (distances >= start) & (distances <= end)
            laps[mask] = lap_num
        return laps

    def _load_fastf1_session(
        self,
        year: int,
        event_round_or_name: int | str,
        session_type: str,
        *,
        telemetry: bool,
        weather: bool,
    ) -> Any:
        session_identifier = self._session_identifier(year, event_round_or_name, session_type)
        try:
            import fastf1

            session = fastf1.get_session(int(year), event_round_or_name, session_identifier)
        except ValueError as exc:
            raise ValueError(
                f"Invalid session parameters: year={year}, event='{event_round_or_name}', "
                f"session_type='{session_type}'"
            ) from exc
        except Exception as exc:
            raise ValueError(
                f"Unable to locate FastF1 session for year={year}, event='{event_round_or_name}', "
                f"session_type='{session_type}': {exc}"
            ) from exc

        try:
            session.load(laps=True, telemetry=telemetry, weather=weather, messages=False)
        except TypeError:
            session.load()
        except Exception as exc:
            raise TelemetryUnavailableError(f"Unable to load FastF1 session payload: {exc}") from exc
        return session

    def _session_identifier(self, year: int, event_round_or_name: int | str, session_type: str) -> str:
        try:
            event = self._get_event(year, event_round_or_name)
            return str(event.get_session_name(session_type))
        except Exception:
            return normalize_session_type(session_type)

    def _get_event(self, year: int, event_round_or_name: int | str) -> Any:
        self._enable_cache()
        try:
            import fastf1

            schedule = fastf1.get_event_schedule(int(year), include_testing=False)
            if isinstance(event_round_or_name, int) or str(event_round_or_name).isdigit():
                return schedule.get_event_by_round(int(event_round_or_name))
            event = schedule.get_event_by_name(str(event_round_or_name), exact_match=True)
            if event is None:
                event = schedule.get_event_by_name(str(event_round_or_name))
            if event is None:
                raise ValueError(f"No FastF1 event matched '{event_round_or_name}'")
            return event
        except Exception as exc:
            raise ValueError(f"Unable to resolve FastF1 event '{event_round_or_name}' for {year}: {exc}") from exc

    def _enable_cache(self) -> None:
        """Create and enable the local FastF1 cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            import fastf1

            fastf1.Cache.enable_cache(str(self.cache_dir))
        except ImportError as exc:
            raise ImportError(
                "fastf1 is required to load real telemetry. Install dependencies with "
                "'pip install -r requirements.txt'."
            ) from exc

    def _extract_laps(self, session: Any, ref_driver: str, user_driver: str) -> tuple[Any, Any]:
        """Return the fastest lap for the reference and comparison drivers."""
        baseline_lap = self._pick_fastest_lap(session, ref_driver, "reference")
        driver_lap = self._pick_fastest_lap(session, user_driver, "comparison")
        return baseline_lap, driver_lap

    def _pick_fastest_lap(self, session: Any, driver: str, role: str) -> Any:
        try:
            driver_laps = session.laps.pick_driver(driver)
        except Exception as exc:
            raise ValueError(f"Invalid {role} driver '{driver}' or missing lap data") from exc

        if driver_laps is None or len(driver_laps) == 0:
            raise TelemetryUnavailableError(f"No laps found for {role} driver '{driver}'")

        fastest = driver_laps.pick_fastest()
        if fastest is None or (hasattr(fastest, "empty") and fastest.empty):
            raise TelemetryUnavailableError(f"No fastest lap available for {role} driver '{driver}'")
        return fastest

    def _validate_telemetry(self, lap: Any, driver_label: str) -> pd.DataFrame:
        """Return distance-annotated telemetry after validating required streams."""
        try:
            telemetry = lap.get_telemetry().add_distance()
        except Exception as exc:
            raise TelemetryUnavailableError(
                f"Telemetry unavailable for driver '{driver_label}': {exc}"
            ) from exc

        if telemetry is None or len(telemetry) == 0:
            raise TelemetryUnavailableError(f"Telemetry payload is empty for driver '{driver_label}'")

        telemetry_df = pd.DataFrame(telemetry).copy()
        required = (*REQUIRED_TELEMETRY_COLUMNS, "Distance")
        for column in required:
            if column not in telemetry_df.columns:
                raise ValueError(f"Missing telemetry column '{column}' for driver '{driver_label}'")
            numeric = pd.to_numeric(telemetry_df[column], errors="coerce")
            if numeric.isna().any():
                raise ValueError(f"Null telemetry values in column '{column}' for driver '{driver_label}'")
            telemetry_df[column] = numeric.astype(float)

        return telemetry_df

    def _resample(
        self,
        baseline_tel: pd.DataFrame,
        driver_tel: pd.DataFrame,
        cross_session: bool = False,
        *,
        waypoint_count: int = WAYPOINT_COUNT,
    ) -> pd.DataFrame:
        """Resample both telemetry traces to a shared distance grid and compute deltas."""
        baseline_clean = self._prepare_for_interp(baseline_tel, "baseline")
        driver_clean = self._prepare_for_interp(driver_tel, "driver")

        max_shared_distance = min(
            float(baseline_clean["Distance"].max()), float(driver_clean["Distance"].max())
        )
        if not np.isfinite(max_shared_distance) or max_shared_distance <= 0:
            raise ValueError("Shared track distance must be a positive finite value")

        grid = np.linspace(0.0, max_shared_distance, waypoint_count)
        baseline = self._interp_trace(baseline_clean, grid, "baseline")
        driver = self._interp_trace(driver_clean, grid, "driver")

        if cross_session:
            for axis in ("x", "y"):
                baseline[axis] = baseline[axis] - np.mean(baseline[axis])
                driver[axis] = driver[axis] - np.mean(driver[axis])

        speed_delta = driver["speed"] - baseline["speed"]
        throttle_delta = driver["throttle"] - baseline["throttle"]
        spatial_deviation = np.sqrt((driver["x"] - baseline["x"]) ** 2 + (driver["y"] - baseline["y"]) ** 2)

        dataset = pd.DataFrame(
            {
                "idx": np.arange(waypoint_count, dtype=int),
                "distance": grid,
                "baseline_x": baseline["x"],
                "baseline_y": baseline["y"],
                "baseline_speed": baseline["speed"],
                "baseline_throttle": baseline["throttle"],
                "baseline_brake": baseline["brake"],
                "driver_x": driver["x"],
                "driver_y": driver["y"],
                "driver_speed": driver["speed"],
                "driver_throttle": driver["throttle"],
                "driver_brake": driver["brake"],
                "speed_delta": speed_delta,
                "throttle_delta": throttle_delta,
                "spatial_deviation": spatial_deviation,
            }
        )

        if len(dataset) != waypoint_count:
            raise ValueError(f"Resampling produced {len(dataset)} rows, expected {waypoint_count}")
        if dataset.isna().any().any():
            column = dataset.columns[dataset.isna().any()].tolist()[0]
            raise ValueError(f"Resampling produced invalid values in column '{column}'")
        return dataset

    def _prepare_for_interp(self, telemetry: pd.DataFrame, driver_label: str) -> pd.DataFrame:
        required = (*REQUIRED_TELEMETRY_COLUMNS, "Distance")
        frame = telemetry.loc[:, required].copy()
        for column in required:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame[column].isna().any() or not np.isfinite(frame[column]).all():
                raise ValueError(f"Invalid numeric values in column '{column}' for {driver_label}")

        frame = frame.sort_values("Distance")
        frame = frame.drop_duplicates(subset="Distance", keep="first")
        if len(frame) < 2:
            raise ValueError(f"Telemetry for {driver_label} has fewer than two valid distance samples")
        return frame

    def _interp_trace(self, telemetry: pd.DataFrame, grid: np.ndarray, driver_label: str) -> dict[str, np.ndarray]:
        source_columns = {
            "x": "X",
            "y": "Y",
            "speed": "Speed",
            "throttle": "Throttle",
            "brake": "Brake",
        }
        result: dict[str, np.ndarray] = {}
        distance = telemetry["Distance"].to_numpy(dtype=float)
        for target, source in source_columns.items():
            values = telemetry[source].to_numpy(dtype=float)
            interp_values = np.interp(grid, distance, values)
            valid_count = int(np.isfinite(interp_values).sum())
            if valid_count < len(grid):
                raise ValueError(
                    f"Resampled column '{source}' for {driver_label} has {valid_count} valid values"
                )
            result[target] = interp_values
        return result

    def _extract_weather(self, session: Any) -> WeatherStats:
        """Extract average session weather, falling back to MVP defaults."""
        weather = getattr(session, "weather_data", None)
        if weather is None:
            LOGGER.warning("Weather data absent; using default weather values")
            return WeatherStats()

        weather_df = pd.DataFrame(weather)
        required = ("TrackTemperature", "WindSpeed", "WindDirection")
        if weather_df.empty or any(column not in weather_df.columns for column in required):
            LOGGER.warning("Weather data incomplete; using default weather values")
            return WeatherStats()

        try:
            values = {
                column: pd.to_numeric(weather_df[column], errors="coerce").dropna()
                for column in required
            }
            if any(series.empty for series in values.values()):
                LOGGER.warning("Weather data contains no numeric samples; using default weather values")
                return WeatherStats()
            return WeatherStats(
                track_temperature=float(values["TrackTemperature"].mean()),
                wind_speed=float(values["WindSpeed"].mean()),
                wind_direction=float(values["WindDirection"].mean()),
            )
        except Exception:
            LOGGER.warning("Weather extraction failed; using default weather values", exc_info=True)
            return WeatherStats()

    def _string_or_empty(self, value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()
