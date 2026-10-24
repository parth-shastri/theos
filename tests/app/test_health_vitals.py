"""Google Health v4 vitals contracts, cache upgrades, and incomplete imports."""

from datetime import date

import httpx
import pytest

from theos.services.health.imports import DATA_TYPES, SUMMARY_VERSION, import_summary
from theos.services.health.normalize import normalize_data_points
from theos.services.health.vitals import VITAL_COMPONENTS

from .conftest import call_tool
from .test_telegram_onboarding import bot_for, message, sent

DAY = {"year": 2026, "month": 10, "day": 23}
TIME = {"physicalTime": "2026-10-23T08:00:00Z", "utcOffset": "19800s"}


def vital_points():
    """Use the field names and units from the Google Health v4 REST schema."""
    components = {
        "daily-heart-rate-variability": {
            "date": DAY,
            "averageHeartRateVariabilityMilliseconds": 48.25,
            "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 62.5,
            "nonRemHeartRateBeatsPerMinute": "57",
            "entropy": 3.4,
        },
        "daily-oxygen-saturation": {
            "date": DAY,
            "averagePercentage": 97.2,
            "lowerBoundPercentage": 94.6,
            "upperBoundPercentage": 99.1,
            "standardDeviationPercentage": 0.5,
        },
        "daily-respiratory-rate": {"date": DAY, "breathsPerMinute": 14.2},
        "daily-sleep-temperature-derivations": {
            "date": DAY,
            "nightlyTemperatureCelsius": 33.1,
            "baselineTemperatureCelsius": 33.5,
            "relativeNightlyStddev30dCelsius": 0.2,
        },
        "heart-rate": {"sampleTime": TIME, "beatsPerMinute": "72"},
        "heart-rate-variability": {
            "sampleTime": TIME,
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 42.5,
            "standardDeviationMilliseconds": 51.5,
        },
        "oxygen-saturation": {"sampleTime": TIME, "percentage": 98.5},
        "core-body-temperature": {"sampleTime": TIME, "temperatureCelsius": 36.8},
        "blood-glucose": {"sampleTime": TIME, "bloodGlucoseMilligramsPerDeciliter": 95},
        "respiratory-rate-sleep-summary": {
            "sampleTime": TIME,
            "fullSleepStats": {"breathsPerMinute": 14.3, "standardDeviation": 0.8},
            "deepSleepStats": {"breathsPerMinute": 13.1, "signalToNoise": 5},
        },
    }
    return {
        kind: [{"name": f"users/me/dataTypes/{kind}/dataPoints/one", VITAL_COMPONENTS[kind]: value}]
        for kind, value in components.items()
    }


def test_vitals_preserve_daily_units_and_separate_sample_statistics():
    points = vital_points()
    heart = points["heart-rate"][0]
    points["heart-rate"] += [
        heart,
        {"name": "second", "heartRate": {"sampleTime": TIME, "beatsPerMinute": "84"}},
    ]
    day = normalize_data_points(points)[0].to_dict()
    assert day["date"] == "2026-10-23"
    vitals = day["vitals"]
    assert vitals["heart_rate_variability"] == {
        "daily_rmssd_ms": 48.25,
        "deep_sleep_rmssd_ms": 62.5,
        "non_rem_heart_rate_bpm": 57,
        "entropy": 3.4,
        "rmssd_samples_ms": {
            "sample_count": 1,
            "sample_mean": 42.5,
            "minimum": 42.5,
            "maximum": 42.5,
        },
        "sdnn_samples_ms": {
            "sample_count": 1,
            "sample_mean": 51.5,
            "minimum": 51.5,
            "maximum": 51.5,
        },
    }
    assert vitals["heart_rate"]["samples_bpm"] == {
        "sample_count": 2,
        "sample_mean": 78,
        "minimum": 72,
        "maximum": 84,
    }
    assert vitals["oxygen_saturation"]["daily_lower_confidence_bound_percent"] == 94.6
    assert vitals["oxygen_saturation"]["daily_upper_confidence_bound_percent"] == 99.1
    assert vitals["oxygen_saturation"]["samples_percent"]["sample_mean"] == 98.5
    assert vitals["respiratory_rate"]["daily_breaths_per_minute"] == 14.2
    assert vitals["respiratory_rate"]["sleep_summaries"] == [
        {
            "sample_time": TIME["physicalTime"],
            "full_sleep": {"breaths_per_minute": 14.3, "standard_deviation": 0.8},
            "deep_sleep": {"breaths_per_minute": 13.1, "signal_to_noise": 5},
        }
    ]
    assert vitals["skin_temperature"] == {
        "nightly_celsius": 33.1,
        "baseline_celsius": 33.5,
        "relative_nightly_stddev_30d_celsius": 0.2,
    }
    assert vitals["core_body_temperature"]["samples_celsius"]["sample_mean"] == 36.8
    assert vitals["blood_glucose"]["samples_mg_dl"]["sample_mean"] == 95
    assert "dataSource" not in str(day) and "dataPoints/one" not in str(day)


def test_missing_and_invalid_vitals_do_not_become_zero_and_samples_use_local_dates():
    points = {
        "daily-heart-rate-variability": [{"dailyHeartRateVariability": {"date": DAY}}],
        "heart-rate-variability": [
            {
                "heartRateVariability": {
                    "sampleTime": TIME,
                    "rootMeanSquareOfSuccessiveDifferencesMilliseconds": value,
                }
            }
            for value in (None, True, "nan", float("inf"), -1, "unknown")
        ],
        "oxygen-saturation": [
            {
                "oxygenSaturation": {
                    "sampleTime": {"physicalTime": "2026-10-23T23:30:00Z", "utcOffset": "19800s"},
                    "percentage": 0,
                }
            }
        ],
        "daily-respiratory-rate": [
            {
                "dailyRespiratoryRate": {
                    "date": {"year": 2026, "month": 13, "day": 1},
                    "breathsPerMinute": 14,
                }
            }
        ],
    }
    days = [day.to_dict() for day in normalize_data_points(points)]
    assert days[0] == {"date": "2026-10-23", "source": "google_health"}
    assert days[1]["date"] == "2026-10-24"
    assert days[1]["vitals"] == {
        "oxygen_saturation": {
            "samples_percent": {
                "sample_count": 1,
                "sample_mean": 0,
                "minimum": 0,
                "maximum": 0,
            }
        }
    }


async def test_import_fetches_vitals_with_type_specific_filters_and_preserves_cache_on_failure(
    runtime,
):
    points = vital_points()
    calls = []
    fail = False

    async def request(owner, method, path, *, params):
        assert owner == "alice" and method == "GET"
        kind = path.split("/")[-2]
        calls.append((kind, params))
        if fail and kind == "daily-respiratory-rate":
            raise httpx.HTTPStatusError(
                "Unavailable",
                request=httpx.Request("GET", "https://example.invalid"),
                response=httpx.Response(503),
            )
        if kind == "heart-rate-variability" and "pageToken" not in params:
            return {"dataPoints": points[kind], "nextPageToken": "second"}
        return {"dataPoints": points.get(kind, [])}

    runtime.health.request = request
    start = end = date(2026, 10, 23)
    snapshot = await import_summary(runtime.health, "alice", start, end)
    assert snapshot["schema_version"] == SUMMARY_VERSION
    saved = runtime.db.record("alice", "health", "summary")
    assert saved == {"id": "summary", **snapshot}
    assert {kind for kind, _ in calls} == set(DATA_TYPES)
    assert len(calls) == len(DATA_TYPES) + 1
    by_type = dict(calls)
    assert (
        by_type["daily-heart-rate-variability"]["filter"]
        == 'daily_heart_rate_variability.date >= "2026-10-23" AND daily_heart_rate_variability.date < "2026-10-24"'
    )
    assert (
        by_type["heart-rate-variability"]["filter"]
        == 'heart_rate_variability.sample_time.civil_time >= "2026-10-23" AND heart_rate_variability.sample_time.civil_time < "2026-10-24"'
    )
    assert by_type["heart-rate-variability"]["pageToken"] == "second"
    assert (
        snapshot["days"][0]["vitals"]["heart_rate_variability"]["rmssd_samples_ms"]["sample_count"]
        == 1
    )
    imported_at = runtime.db.record("alice", "health", "last_import")
    fail = True
    with pytest.raises(httpx.HTTPStatusError):
        await import_summary(runtime.health, "alice", start, end)
    assert runtime.db.record("alice", "health", "summary") == saved
    assert runtime.db.record("alice", "health", "last_import") == imported_at


async def test_summary_upgrades_old_cache_and_exposes_default_and_selected_vitals(runtime):
    old = {
        "from": "2026-10-23T00:00:00+00:00",
        "to": "2026-10-24T00:00:00+00:00",
        "days": [{"date": "2026-10-23", "steps": 1234}],
    }
    runtime.db.put_record("alice", "health", "summary", old)
    runtime.db.put_record("bob", "health", "summary", old)
    calls = []

    async def request(owner, method, path, **kwargs):
        calls.append((owner, path))
        return {"dataPoints": vital_points().get(path.split("/")[-2], [])}

    runtime.health.request = request
    tools = runtime.health.tools("alice")
    result = await call_tool(tools, "get_health_summary")
    assert result["days"][0]["vitals"]["heart_rate_variability"]["daily_rmssd_ms"] == 48.25
    assert result["vitals_coverage"]["heart_rate_variability"] == {"days_with_readings": 1}
    assert {owner for owner, _ in calls} == {"alice"}
    assert runtime.db.record("bob", "health", "summary") == {"id": "summary", **old}
    count = len(calls)
    selected = await call_tool(
        tools, "get_health_summary", metrics=["heart_rate_variability", "respiratory_rate"]
    )
    assert len(calls) == count
    assert set(selected["days"][0]["vitals"]) == {"heart_rate_variability", "respiratory_rate"}
    assert set(selected["vitals_coverage"]) == {"heart_rate_variability", "respiratory_rate"}

    runtime.health.request = lambda *args, **kwargs: pytest.fail("Current cache should be used")
    cached = runtime.db.record("alice", "health", "summary")
    cached["days"] = [{"date": "2026-10-23", "steps": 2000}]
    runtime.db.put_record("alice", "health", "summary", cached)
    missing = await call_tool(tools, "get_health_summary", metrics=["vitals"])
    assert missing["days"] == [{"date": "2026-10-23"}]
    assert all(value == {"days_with_readings": 0} for value in missing["vitals_coverage"].values())


async def test_telegram_summary_refreshes_legacy_cache_without_truncating_vitals(runtime):
    import json

    bot = bot_for(runtime)
    for text in ("/start", "/skip", "/skip"):
        await message(bot, text)
    runtime.db.put_record("telegram:123", "health", "summary", {"days": []})
    day = normalize_data_points(vital_points())[0].to_dict()
    snapshot = {
        "schema_version": SUMMARY_VERSION,
        "from": "2026-10-21T00:00:00+00:00",
        "to": "2026-10-24T00:00:00+00:00",
        "days": [{**day, "date": f"2026-10-{number}"} for number in (21, 22, 23)],
    }
    calls = []

    async def import_summary(owner):
        calls.append(owner)
        runtime.db.put_record(owner, "health", "summary", snapshot)
        return snapshot

    runtime.health.import_summary = import_summary
    for expected_calls in (1, 1):
        start = len(sent(bot))
        await message(bot, "/health_summary")
        parts = sent(bot)[start:]
        assert len(parts) > 1
        assert len("".join(parts)) > 4000
        assert json.loads("".join(parts))["days"] == snapshot["days"]
        assert calls == ["telegram:123"] * expected_calls
