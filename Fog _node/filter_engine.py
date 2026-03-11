# =============================================================
#  SMART CITY — FOG LAYER: FILTER ENGINE
#
#  WHAT THIS DOES (plain English):
#  ─────────────────────────────────────────────────────────────
#  Real sensors are imperfect. They sometimes produce garbage:
#    - A temperature sensor might glitch and read 999°C
#    - A traffic sensor might send null instead of a number
#    - A noisy circuit might produce a sudden spike of 200 dB
#
#  Without filtering, these corrupt values would:
#    - Skew your cloud database averages
#    - Trigger false alerts
#    - Waste bandwidth sending bad data
#
#  The filter engine catches these BEFORE they reach the cloud.
#
#  TWO layers of filtering:
#
#  LAYER 1 — Corruption Check (hard rules)
#    "Is this value physically impossible?"
#    Temperature of 500°C? CORRUPT. Discard immediately.
#    Humidity of -5%? CORRUPT. Discard.
#    This catches sensor hardware failures.
#
#  LAYER 2 — Outlier Detection (statistical)
#    "Is this value statistically unusual compared to recent history?"
#    Uses Z-score: if value is > 2.5 standard deviations from
#    the rolling mean → flag as outlier → discard.
#    This catches temporary spikes and electrical noise.
#    NOTE: Burst mode readings bypass this (they're intentionally extreme)
# =============================================================

import math
import statistics
from collections import defaultdict, deque
from typing import Tuple
from fog_config import (
    OUTLIER_STD_THRESHOLD,
    OUTLIER_MIN_SAMPLES,
    CORRUPTION_RULES,
    HISTORY_SIZE,
)


class FilterResult:
    """
    Wraps the result of a filter check so callers know exactly
    what happened and why.
    """
    def __init__(self, passed: bool, reason: str = "", field: str = "",
                 value=None, expected_range: str = ""):
        self.passed        = passed       # True = reading is clean
        self.reason        = reason       # Human-readable explanation
        self.field         = field        # Which field failed
        self.value         = value        # The actual bad value
        self.expected_range = expected_range

    def __bool__(self):
        return self.passed

    def __repr__(self):
        if self.passed:
            return "FilterResult(PASSED)"
        return f"FilterResult(FAILED: {self.reason} | {self.field}={self.value})"


class FilterEngine:
    """
    Two-stage filter for incoming sensor readings.

    Stage 1: Corruption check   (hard physical limits)
    Stage 2: Outlier detection  (statistical Z-score)

    Maintains a rolling history per sensor per field so
    the outlier detection gets smarter over time.
    """

    def __init__(self):
        # sensor_id → field_name → deque of recent values
        # Used for computing rolling mean/std for outlier detection
        self._history: dict = defaultdict(lambda: defaultdict(
            lambda: deque(maxlen=OUTLIER_MIN_SAMPLES * 4)
        ))

        # ── Stats counters ─────────────────────────────────────
        self.total_checked    = 0
        self.total_passed     = 0
        self.total_corrupt    = 0
        self.total_outliers   = 0

        # Keep a log of recent rejections for the dashboard
        self._rejection_log: deque = deque(maxlen=50)

    # ──────────────────────────────────────────────────────────
    # PUBLIC: Main entry point
    # ──────────────────────────────────────────────────────────
    def check(self, sensor_id: str, sensor_type: str,
              reading: dict, is_burst: bool = False) -> FilterResult:
        """
        Run both filter stages on a sensor reading.

        sensor_id   : e.g. "air_02"
        sensor_type : e.g. "air_quality"
        reading     : the data dict from the sensor payload
        is_burst    : if True, skip outlier check (burst is intentionally extreme)

        Returns FilterResult — if .passed is False, discard the reading.
        """
        self.total_checked += 1

        # ── Stage 1: Corruption check ─────────────────────────
        corrupt_result = self._check_corruption(sensor_type, reading)
        if not corrupt_result.passed:
            self.total_corrupt += 1
            self._log_rejection("CORRUPT", sensor_id, corrupt_result)
            return corrupt_result

        # ── Stage 2: Outlier check ────────────────────────────
        # Skip for burst mode — burst values are intentionally extreme
        if not is_burst:
            outlier_result = self._check_outlier(sensor_id, sensor_type, reading)
            if not outlier_result.passed:
                self.total_outliers += 1
                self._log_rejection("OUTLIER", sensor_id, outlier_result)
                return outlier_result

        # ── All checks passed — update history ────────────────
        self._update_history(sensor_id, reading)
        self.total_passed += 1

        return FilterResult(passed=True, reason="clean")

    # ──────────────────────────────────────────────────────────
    # STAGE 1: Corruption Check
    # ──────────────────────────────────────────────────────────
    def _check_corruption(self, sensor_type: str, reading: dict) -> FilterResult:
        """
        Checks every numeric value against hard physical limits.

        For example, humidity can NEVER be outside 0–100%.
        Temperature can NEVER be 500°C on a city street.
        These aren't "unusual" values — they're physically impossible,
        so they must be sensor hardware failures.
        """
        # Map sensor type to the relevant fields to check
        field_map = {
            "temperature": [("value", "temperature")],
            "humidity":    [("value", "humidity")],
            "air_quality": [("pm25", "pm25"), ("co2", "co2")],
            "noise":       [("value", "noise")],
            "traffic":     [
                ("vehicle_count",    "vehicle_count"),
                ("avg_speed_kmh",    "avg_speed_kmh"),
                ("congestion_index", "congestion_index"),
            ],
        }

        fields_to_check = field_map.get(sensor_type, [])

        for reading_key, rule_key in fields_to_check:
            val = reading.get(reading_key)

            # Missing entirely = corrupt
            if val is None:
                return FilterResult(
                    passed=False,
                    reason="missing_field",
                    field=reading_key,
                    value=None,
                    expected_range="present"
                )

            # Not a number = corrupt
            if not isinstance(val, (int, float)):
                return FilterResult(
                    passed=False,
                    reason="wrong_type",
                    field=reading_key,
                    value=val,
                    expected_range="numeric"
                )

            # NaN or Infinity = corrupt (sensor malfunction)
            if math.isnan(val) or math.isinf(val):
                return FilterResult(
                    passed=False,
                    reason="nan_or_inf",
                    field=reading_key,
                    value=val,
                    expected_range="finite number"
                )

            # Outside physical limits = corrupt
            if rule_key in CORRUPTION_RULES:
                rule = CORRUPTION_RULES[rule_key]
                if val < rule["min"] or val > rule["max"]:
                    return FilterResult(
                        passed=False,
                        reason="outside_physical_limits",
                        field=reading_key,
                        value=val,
                        expected_range=f"{rule['min']}–{rule['max']}"
                    )

        return FilterResult(passed=True)

    # ──────────────────────────────────────────────────────────
    # STAGE 2: Outlier Detection (Z-score method)
    # ──────────────────────────────────────────────────────────
    def _check_outlier(self, sensor_id: str, sensor_type: str,
                       reading: dict) -> FilterResult:
        """
        Uses the Z-score method to detect statistical outliers.

        Z-score = (value - mean) / std_deviation

        If Z-score > threshold (2.5), the value is an outlier.

        Plain English:
          - We keep a rolling history of the last N readings per sensor
          - We compute how far the new value is from "normal"
          - If it's too far away → outlier → discard

        Needs at least OUTLIER_MIN_SAMPLES readings before it can
        make statistical judgments (can't compute std with 1 reading).
        """
        numeric_fields = self._get_numeric_fields(sensor_type, reading)

        for field, value in numeric_fields:
            history = list(self._history[sensor_id][field])

            # Not enough history yet — let it through, can't judge
            if len(history) < OUTLIER_MIN_SAMPLES:
                continue

            try:
                mean   = statistics.mean(history)
                stdev  = statistics.stdev(history)

                # If std_dev is near zero (all identical readings),
                # any small change looks like an outlier — avoid this
                if stdev < 0.001:
                    continue

                z_score = abs(value - mean) / stdev

                if z_score > OUTLIER_STD_THRESHOLD:
                    return FilterResult(
                        passed=False,
                        reason="statistical_outlier",
                        field=field,
                        value=value,
                        expected_range=(
                            f"mean={mean:.2f} ±{stdev:.2f} "
                            f"(z={z_score:.2f} > {OUTLIER_STD_THRESHOLD})"
                        )
                    )

            except statistics.StatisticsError:
                continue  # Not enough data for stats — skip check

        return FilterResult(passed=True)

    # ──────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────
    def _update_history(self, sensor_id: str, reading: dict):
        """
        Adds clean reading values to the rolling history.
        Only called AFTER a reading passes all checks.
        This keeps the history clean — outliers never pollute it.
        """
        for key, val in reading.items():
            if isinstance(val, (int, float)):
                self._history[sensor_id][key].append(val)

    def _get_numeric_fields(self, sensor_type: str,
                            reading: dict) -> list:
        """
        Returns list of (field_name, value) tuples for
        the main numeric fields of each sensor type.
        """
        field_map = {
            "temperature": ["value"],
            "humidity":    ["value"],
            "air_quality": ["pm25", "co2"],
            "noise":       ["value"],
            "traffic":     ["vehicle_count", "avg_speed_kmh", "congestion_index"],
        }
        fields = field_map.get(sensor_type, [])
        result = []
        for f in fields:
            if f in reading and isinstance(reading[f], (int, float)):
                result.append((f, reading[f]))
        return result

    def _log_rejection(self, rejection_type: str, sensor_id: str,
                       result: FilterResult):
        """Keeps a recent log of rejections for the dashboard."""
        from datetime import datetime, timezone
        self._rejection_log.append({
            "type":      rejection_type,
            "sensor_id": sensor_id,
            "field":     result.field,
            "value":     result.value,
            "reason":    result.reason,
            "expected":  result.expected_range,
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        })

    # ──────────────────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """Returns filter performance statistics for the dashboard."""
        total = self.total_checked
        return {
            "total_checked":      total,
            "total_passed":       self.total_passed,
            "total_rejected":     self.total_corrupt + self.total_outliers,
            "corrupt_rejected":   self.total_corrupt,
            "outlier_rejected":   self.total_outliers,
            "rejection_rate_pct": round(
                ((self.total_corrupt + self.total_outliers) / total * 100)
                if total > 0 else 0, 1
            ),
            "recent_rejections":  list(self._rejection_log)[-10:],
        }
