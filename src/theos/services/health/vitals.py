"""Normalize daily vitals and summarize sample measurements without raw payloads."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

VITAL_COMPONENTS = {
    "daily-heart-rate-variability": "dailyHeartRateVariability",
    "daily-oxygen-saturation": "dailyOxygenSaturation",
    "daily-respiratory-rate": "dailyRespiratoryRate",
    "daily-sleep-temperature-derivations": "dailySleepTemperatureDerivations",
    "heart-rate": "heartRate",
    "heart-rate-variability": "heartRateVariability",
    "oxygen-saturation": "oxygenSaturation",
    "core-body-temperature": "coreBodyTemperature",
    "blood-glucose": "bloodGlucose",
    "respiratory-rate-sleep-summary": "respiratoryRateSleepSummary",
}
SAMPLE_VITAL_TYPES = {kind for kind in VITAL_COMPONENTS if not kind.startswith("daily-")}
VITAL_METRICS = (
    "heart_rate_variability",
    "oxygen_saturation",
    "respiratory_rate",
    "skin_temperature",
    "heart_rate",
    "core_body_temperature",
    "blood_glucose",
)

DAILY_FIELDS = {
    "daily-heart-rate-variability": (
        "heart_rate_variability",
        {
            "averageHeartRateVariabilityMilliseconds": "daily_rmssd_ms",
            "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": "deep_sleep_rmssd_ms",
            "nonRemHeartRateBeatsPerMinute": "non_rem_heart_rate_bpm",
            "entropy": "entropy",
        },
    ),
    "daily-oxygen-saturation": (
        "oxygen_saturation",
        {
            "averagePercentage": "daily_average_percent",
            "lowerBoundPercentage": "daily_lower_confidence_bound_percent",
            "upperBoundPercentage": "daily_upper_confidence_bound_percent",
            "standardDeviationPercentage": "daily_standard_deviation_percent",
        },
    ),
    "daily-respiratory-rate": (
        "respiratory_rate",
        {"breathsPerMinute": "daily_breaths_per_minute"},
    ),
    "daily-sleep-temperature-derivations": (
        "skin_temperature",
        {
            "nightlyTemperatureCelsius": "nightly_celsius",
            "baselineTemperatureCelsius": "baseline_celsius",
            "relativeNightlyStddev30dCelsius": "relative_nightly_stddev_30d_celsius",
        },
    ),
}
SAMPLE_FIELDS = {
    "heart-rate": ("heart_rate", {"beatsPerMinute": "samples_bpm"}),
    "heart-rate-variability": (
        "heart_rate_variability",
        {
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": "rmssd_samples_ms",
            "standardDeviationMilliseconds": "sdnn_samples_ms",
        },
    ),
    "oxygen-saturation": ("oxygen_saturation", {"percentage": "samples_percent"}),
    "core-body-temperature": ("core_body_temperature", {"temperatureCelsius": "samples_celsius"}),
    "blood-glucose": ("blood_glucose", {"bloodGlucoseMilligramsPerDeciliter": "samples_mg_dl"}),
}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


@dataclass
class _Samples:
    count: int = 0
    mean: float = 0
    minimum: float = math.inf
    maximum: float = -math.inf

    def add(self, value):
        self.count += 1
        self.mean += (value - self.mean) / self.count
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    def to_dict(self):
        return {
            "sample_count": self.count,
            "sample_mean": round(self.mean, 3),
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass
class VitalBuilder:
    """Keep provider daily values separate from arithmetic sample statistics."""

    daily: dict = field(default_factory=dict)
    samples: dict = field(default_factory=dict)
    sleep: list = field(default_factory=list)
    seen: set = field(default_factory=set)

    def add(self, kind, component, record_key):
        key = (kind, record_key)
        if key in self.seen:
            return
        self.seen.add(key)
        if kind in DAILY_FIELDS:
            metric, fields = DAILY_FIELDS[kind]
            values = {
                target: value
                for source, target in fields.items()
                if (value := _number(component.get(source))) is not None
            }
            if values:
                self.daily.setdefault(metric, {}).update(values)
        elif kind in SAMPLE_FIELDS:
            metric, fields = SAMPLE_FIELDS[kind]
            for source, target in fields.items():
                value = _number(component.get(source))
                if value is not None:
                    self.samples.setdefault((metric, target), _Samples()).add(value)
        elif kind == "respiratory-rate-sleep-summary":
            self._add_sleep(component)

    def _add_sleep(self, component):
        result = {}
        sample_time = component.get("sampleTime")
        if isinstance(sample_time, Mapping) and isinstance(sample_time.get("physicalTime"), str):
            result["sample_time"] = sample_time["physicalTime"]
        for source, target in (
            ("fullSleepStats", "full_sleep"),
            ("deepSleepStats", "deep_sleep"),
            ("lightSleepStats", "light_sleep"),
            ("remSleepStats", "rem_sleep"),
        ):
            stats = component.get(source)
            if not isinstance(stats, Mapping):
                continue
            values = {
                target_key: value
                for key, target_key in (
                    ("breathsPerMinute", "breaths_per_minute"),
                    ("standardDeviation", "standard_deviation"),
                    ("signalToNoise", "signal_to_noise"),
                )
                if (value := _number(stats.get(key))) is not None
            }
            if values:
                result[target] = values
        if any(key != "sample_time" for key in result):
            self.sleep.append(result)

    def to_dict(self):
        result = {metric: dict(values) for metric, values in self.daily.items()}
        for (metric, field_name), samples in self.samples.items():
            result.setdefault(metric, {})[field_name] = samples.to_dict()
        if self.sleep:
            result.setdefault("respiratory_rate", {})["sleep_summaries"] = list(self.sleep)
        return result
