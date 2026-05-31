from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol


class InsightProvider(Protocol):
    def get_live_coaching(
        self,
        waypoint: Any,
        track_temp: float = 0.0,
        wind_speed: float = 0.0,
        wind_direction: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        ...

    def get_lap_coaching(
        self,
        lap_summary: Any,
        context: dict[str, Any] | None = None,
    ) -> str:
        ...


@dataclass(frozen=True)
class InsightContext:
    year: int | None = None
    event: str | int | None = None
    session_type: str | None = None
    driver1: str | None = None
    driver2: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "event": self.event,
            "session_type": self.session_type,
            "driver1": self.driver1,
            "driver2": self.driver2,
        }


class RuleFallbackInsightProvider:
    """Deterministic fallback for offline or failed AI calls."""

    SPEED_INSIGHT = (
        "Driver 2 is carrying noticeably more speed at this point; compare entry line, "
        "minimum speed, and throttle pickup against Driver 1."
    )
    LINE_INSIGHT = (
        "The two drivers are using different track positions here; focus on how the line "
        "choice changes rotation and exit speed."
    )
    BRAKING_INSIGHT = (
        "Driver 1 is off the brake while Driver 2 is still braking; compare brake release "
        "timing and how each driver rotates the car."
    )

    def get_live_coaching(
        self,
        waypoint: Any,
        track_temp: float = 0.0,
        wind_speed: float = 0.0,
        wind_direction: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        try:
            for rule in (
                self._speed_rule(waypoint),
                self._line_rule(waypoint),
                self._braking_rule(waypoint),
            ):
                if rule:
                    return rule
            return self._neutral_phrase(waypoint)
        except Exception:
            return "Telemetry is stable at this point; keep inputs progressive and compare the next sector."

    def get_lap_coaching(
        self,
        lap_summary: Any,
        context: dict[str, Any] | None = None,
    ) -> str:
        lap = getattr(lap_summary, "lap", 1)
        return f"Lap {lap} telemetry is consistent. Driver 2 should review their braking points and average cornering speed to improve lap time."

    def _speed_rule(self, waypoint: Any) -> str | None:
        if abs(self._value(waypoint, "speed_delta")) > 10.0:
            return self.SPEED_INSIGHT
        return None

    def _line_rule(self, waypoint: Any) -> str | None:
        if self._value(waypoint, "spatial_deviation") > 1.2:
            return self.LINE_INSIGHT
        return None

    def _braking_rule(self, waypoint: Any) -> str | None:
        if self._value(waypoint, "baseline_brake") == 0.0 and self._value(waypoint, "driver_brake") > 0.0:
            return self.BRAKING_INSIGHT
        return None

    def _neutral_phrase(self, waypoint: Any) -> str:
        speed_delta = self._value(waypoint, "speed_delta")
        line_delta = self._value(waypoint, "spatial_deviation")
        return (
            f"Driving comparison: speed delta {speed_delta:+.1f} km/h and line difference "
            f"{line_delta:.2f} m; compare how both drivers build the lap from this point."
        )

    def _value(self, waypoint: Any, key: str) -> float:
        if isinstance(waypoint, dict):
            if key == "speed_delta": return float(waypoint.get("deltas", {}).get("speed", 0))
            if key == "throttle_delta": return float(waypoint.get("deltas", {}).get("throttle", 0))
            if key == "spatial_deviation": return float(waypoint.get("deltas", {}).get("line", 0))
            
            if key == "baseline_speed": return float(waypoint.get("driver1", {}).get("speed", 0))
            if key == "baseline_throttle": return float(waypoint.get("driver1", {}).get("throttle", 0))
            if key == "baseline_brake": return float(waypoint.get("driver1", {}).get("brake", 0))
            
            if key == "driver_speed": return float(waypoint.get("driver2", {}).get("speed", 0))
            if key == "driver_throttle": return float(waypoint.get("driver2", {}).get("throttle", 0))
            if key == "driver_brake": return float(waypoint.get("driver2", {}).get("brake", 0))
            
            return float(waypoint.get(key, 0))
        
        if hasattr(waypoint, key):
            return float(getattr(waypoint, key))
        return float(waypoint[key])


class GraniteInsightProvider:
    """IBM watsonx.ai Granite-backed live coaching provider."""

    DEFAULT_MODEL_ID = "meta-llama/llama-3-3-70b-instruct"
    UNSUPPORTED_MODEL_REPLACEMENTS = {
        "ibm/granite-3-8b-instruct": DEFAULT_MODEL_ID,
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        project_id: str | None = None,
        url: str | None = None,
        model_id: str | None = None,
        max_new_tokens: int = 90,
    ) -> None:
        self.api_key = api_key or os.getenv("WATSONX_API_KEY")
        self.project_id = project_id or os.getenv("WATSONX_PROJECT_ID")
        self.url = url or os.getenv("WATSONX_URL")
        self.model_id = self._resolve_model_id(model_id or os.getenv("WATSONX_MODEL_ID"))
        self.max_new_tokens = max_new_tokens
        self._model: Any | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.project_id and self.url)

    def get_live_coaching(
        self,
        waypoint: Any,
        track_temp: float = 0.0,
        wind_speed: float = 0.0,
        wind_direction: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> str:
        if not self.is_configured:
            raise RuntimeError("IBM Granite is not configured. Set WATSONX_API_KEY, WATSONX_PROJECT_ID, and WATSONX_URL.")

        prompt = self.build_prompt(waypoint, context or {})
        response = self._get_model().generate_text(prompt=prompt, params=self._generation_params())
        return self._extract_text(response)

    def get_lap_coaching(
        self,
        lap_summary: Any,
        context: dict[str, Any] | None = None,
    ) -> str:
        if not self.is_configured:
            raise RuntimeError("IBM Granite is not configured. Set WATSONX_API_KEY, WATSONX_PROJECT_ID, and WATSONX_URL.")

        prompt = self.build_lap_prompt(lap_summary, context or {})
        response = self._get_model().generate_text(prompt=prompt, params=self._generation_params())
        return self._extract_text(response)

    def build_prompt(
        self,
        waypoint: Any,
        context: dict[str, Any],
    ) -> str:
        value = RuleFallbackInsightProvider()._value
        metadata = ", ".join(
            f"{key}={val}" for key, val in context.items() if val is not None and str(val).strip()
        )
        return (
            "You are ApexSim AI, an F1 race engineer giving live telemetry coaching. "
            "Compare how Driver 1 and Driver 2 are driving this part of the lap. "
            "Use only the supplied FastF1 telemetry. Give one or two concise, actionable sentences. "
            "Do not discuss weather, invent lap facts, sector names, setup changes, or unsafe driving advice. "
            "Do NOT include any notes, explanations, or conversational filler. ONLY output the coaching sentences.\n\n"
            f"Session: {metadata or 'not supplied'}\n"
            f"Waypoint: idx={int(value(waypoint, 'idx'))}, lap={int(value(waypoint, 'lap'))}, distance_m={value(waypoint, 'distance'):.1f}\n"
            f"Driver 1: speed_kmh={value(waypoint, 'baseline_speed'):.1f}, "
            f"throttle_pct={value(waypoint, 'baseline_throttle'):.1f}, brake={value(waypoint, 'baseline_brake'):.1f}\n"
            f"Driver 2: speed_kmh={value(waypoint, 'driver_speed'):.1f}, "
            f"throttle_pct={value(waypoint, 'driver_throttle'):.1f}, brake={value(waypoint, 'driver_brake'):.1f}\n"
            f"Deltas: speed_kmh={value(waypoint, 'speed_delta'):+.1f}, "
            f"throttle_pct={value(waypoint, 'throttle_delta'):+.1f}, "
            f"line_variance_m={value(waypoint, 'spatial_deviation'):.2f}\n"
            "Coaching:"
        )

    def build_lap_prompt(
        self,
        lap_summary: Any,
        context: dict[str, Any],
    ) -> str:
        metadata = ", ".join(
            f"{key}={val}" for key, val in context.items() if val is not None and str(val).strip()
        )
        return (
            "You are ApexSim AI, an F1 race engineer giving live telemetry coaching. "
            "Compare the overall performance of Driver 1 and Driver 2 over the specified lap. "
            "Provide strategic, high-level advice based on their average speeds, throttle, and braking profiles for this lap. "
            "Use only the supplied data. Give two or three concise, actionable sentences. "
            "Do NOT include any notes, explanations, or conversational filler. ONLY output the coaching sentences.\n\n"
            f"Session: {metadata or 'not supplied'}\n"
            f"Lap: {getattr(lap_summary, 'lap', 1)}\n"
            f"Driver 1 Lap Averages: speed_kmh={getattr(lap_summary, 'avg_baseline_speed', 0):.1f}, throttle_pct={getattr(lap_summary, 'avg_baseline_throttle', 0):.1f}, max_brake={getattr(lap_summary, 'max_baseline_brake', 0):.1f}\n"
            f"Driver 2 Lap Averages: speed_kmh={getattr(lap_summary, 'avg_driver_speed', 0):.1f}, throttle_pct={getattr(lap_summary, 'avg_driver_throttle', 0):.1f}, max_brake={getattr(lap_summary, 'max_driver_brake', 0):.1f}\n"
            f"Average Deltas for Lap: speed_kmh={getattr(lap_summary, 'avg_speed_delta', 0):+.1f}, throttle_pct={getattr(lap_summary, 'avg_throttle_delta', 0):+.1f}, max_line_variance_m={getattr(lap_summary, 'max_spatial_deviation', 0):.2f}\n"
            "Lap Summary Coaching:"
        )

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from ibm_watsonx_ai import Credentials
                from ibm_watsonx_ai.foundation_models import ModelInference
            except ImportError as exc:
                raise RuntimeError("Install ibm-watsonx-ai to use IBM Granite insights.") from exc

            self._model = ModelInference(
                model_id=self.model_id,
                credentials=Credentials(url=self.url, api_key=self.api_key),
                project_id=self.project_id,
            )
        return self._model

    def _resolve_model_id(self, model_id: str | None) -> str:
        requested = (model_id or self.DEFAULT_MODEL_ID).strip()
        return self.UNSUPPORTED_MODEL_REPLACEMENTS.get(requested, requested)

    def _generation_params(self) -> dict[str, Any]:
        return {
            "max_new_tokens": self.max_new_tokens,
            "temperature": 0.2,
            "decoding_method": "greedy",
            "repetition_penalty": 1.05,
        }

    def _extract_text(self, response: Any) -> str:
        if isinstance(response, str):
            text = response
        elif isinstance(response, dict):
            results = response.get("results")
            if isinstance(results, list) and results:
                first = results[0]
                text = str(first.get("generated_text") or first.get("text") or "")
            else:
                text = str(response.get("generated_text") or response.get("text") or "")
        else:
            text = str(response)
        text = text.strip()
        
        # Safety net: Strip out appended notes that models sometimes add
        if "Note:" in text:
            text = text.split("Note:")[0].strip()
        elif "Note that" in text:
            text = text.split("Note that")[0].strip()
            
        if not text:
            raise RuntimeError("IBM Granite returned an empty insight")
        return " ".join(text.split())


class InsightEngine:
    """Live coaching engine using IBM Granite with deterministic fallback."""

    AERO_INSIGHT = RuleFallbackInsightProvider.SPEED_INSIGHT
    THERMAL_INSIGHT = RuleFallbackInsightProvider.LINE_INSIGHT
    SPEED_INSIGHT = RuleFallbackInsightProvider.SPEED_INSIGHT
    LINE_INSIGHT = RuleFallbackInsightProvider.LINE_INSIGHT
    BRAKING_INSIGHT = RuleFallbackInsightProvider.BRAKING_INSIGHT

    def __init__(
        self,
        provider: InsightProvider | None = None,
        fallback_provider: RuleFallbackInsightProvider | None = None,
    ) -> None:
        self.fallback_provider = fallback_provider or RuleFallbackInsightProvider()
        self.provider = provider or GraniteInsightProvider()
        self.last_error: str | None = None

    def get_live_coaching(
        self,
        waypoint: Any,
        track_temp: float = 0.0,
        wind_speed: float = 0.0,
        wind_direction: float = 0.0,
        context: dict[str, Any] | InsightContext | None = None,
    ) -> str:
        context_dict = context.as_dict() if isinstance(context, InsightContext) else context
        try:
            self.last_error = None
            return self.provider.get_live_coaching(
                waypoint, track_temp, wind_speed, wind_direction, context_dict
            )
        except Exception as exc:
            self.last_error = str(exc)
            return self.fallback_provider.get_live_coaching(
                waypoint, track_temp, wind_speed, wind_direction, context_dict
            )

    def get_lap_coaching(
        self,
        lap_summary: Any,
        context: dict[str, Any] | InsightContext | None = None,
    ) -> str:
        context_dict = context.as_dict() if isinstance(context, InsightContext) else context
        try:
            self.last_error = None
            return self.provider.get_lap_coaching(lap_summary, context_dict)
        except Exception as exc:
            self.last_error = str(exc)
            return self.fallback_provider.get_lap_coaching(lap_summary, context_dict)

    def _aero_wind_rule(self, waypoint: Any, wind_speed: float, wind_direction: float) -> str | None:
        return self.fallback_provider._speed_rule(waypoint)

    def _thermal_tire_rule(self, waypoint: Any, track_temp: float) -> str | None:
        return self.fallback_provider._line_rule(waypoint)

    def _speed_rule(self, waypoint: Any) -> str | None:
        return self.fallback_provider._speed_rule(waypoint)

    def _line_rule(self, waypoint: Any) -> str | None:
        return self.fallback_provider._line_rule(waypoint)

    def _braking_rule(self, waypoint: Any) -> str | None:
        return self.fallback_provider._braking_rule(waypoint)

    def _neutral_phrase(self, waypoint: Any) -> str:
        return self.fallback_provider._neutral_phrase(waypoint)

    def _value(self, waypoint: Any, key: str) -> float:
        return self.fallback_provider._value(waypoint, key)
