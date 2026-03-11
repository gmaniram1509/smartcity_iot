# =============================================================
#  SMART CITY — FOG LAYER: AGGREGATOR
#
#  WHAT THIS DOES (plain English):
#  ─────────────────────────────────────────────────────────────
#  Imagine you have a traffic sensor sending 10 readings per
#  minute. You don't want to send all 10 to the cloud — that's
#  expensive and wasteful.
#
#  Instead the aggregator:
#    1. Collects the 10 readings in a local buffer
#    2. When the buffer is full, computes averages
#    3. Returns ONE clean summary payload instead of 10
#    4. That ONE payload goes to the cloud
#
#  Result: 10 cloud messages → 1 cloud message = 90% reduction
#
#  This is the core academic argument for fog computing:
#  "Local aggregation dramatically reduces bandwidth and cost."
#
#  Each sensor gets its OWN independent buffer.
#  When a sensor's buffer is full, it flushes and resets.
# =============================================================

import time
import statistics
from collections import defaultdict, deque
from typing import Optional
from fog_config import AGGREGATE_WINDOW, HISTORY_SIZE


class SensorBuffer:
    """
    A buffer for ONE specific sensor (e.g. "air_02").

    Holds raw readings until the window is full,
    then computes statistics and flushes.
    """

    def __init__(self, sensor_id: str, sensor_type: str, window_size: int):
        self.sensor_id   = sensor_id
        self.sensor_type = sensor_type
        self.window_size = window_size

        # The raw readings waiting to be aggregated
        # deque with maxlen auto-discards oldest if overfilled
        self._buffer: deque = deque(maxlen=window_size * 2)

        # Running count of total readings received (for stats)
        self.total_received = 0
        self.total_aggregated = 0   # How many aggregation batches sent

        # Timestamps
        self.first_reading_time: Optional[float] = None
        self.last_flush_time:    Optional[float] = None

    def add(self, reading: dict) -> Optional[dict]:
        """
        Add one raw reading to the buffer.

        Returns an aggregated payload if the buffer is now full.
        Returns None if still collecting (buffer not full yet).

        This means the caller just does:
            result = buffer.add(reading)
            if result:
                send_to_cloud(result)   # Full window ready
            # else: still collecting, do nothing
        """
        self._buffer.append(reading)
        self.total_received += 1

        if self.first_reading_time is None:
            self.first_reading_time = time.time()

        # Not enough readings yet — keep collecting
        if len(self._buffer) < self.window_size:
            return None

        # Buffer is full — compute aggregation and flush
        aggregated = self._compute_aggregation()
        self._buffer.clear()
        self.total_aggregated += 1
        self.last_flush_time = time.time()

        return aggregated

    def _compute_aggregation(self) -> dict:
        """
        Takes all readings in the buffer and computes:
          - mean    (average value)
          - min     (lowest reading in the window)
          - max     (highest reading in the window)
          - std_dev (how much values varied — useful for detecting instability)
          - count   (how many raw readings were compressed into this one)

        The result replaces all those individual readings with ONE
        clean statistical summary.
        """
        readings = list(self._buffer)
        count    = len(readings)

        # ── Extract numeric fields from reading dicts ─────────
        # Different sensor types have different fields.
        # We extract ALL numeric values we find.
        numeric_fields = self._extract_numeric_fields(readings)

        # ── Compute stats for each numeric field ───────────────
        stats = {}
        for field, values in numeric_fields.items():
            if not values:
                continue
            try:
                stats[field] = {
                    "mean":    round(statistics.mean(values), 2),
                    "min":     round(min(values), 2),
                    "max":     round(max(values), 2),
                    "std_dev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
                }
            except Exception:
                stats[field] = {"mean": values[0]}

        # ── Collect non-numeric metadata (e.g. "category") ────
        # Take the most recent reading's metadata fields
        latest = readings[-1]
        metadata = {
            k: v for k, v in latest.items()
            if not isinstance(v, (int, float))
            and k not in ("timestamp", "burst", "seq")
        }

        return {
            "aggregated":      True,
            "sensor_id":       self.sensor_id,
            "sensor_type":     self.sensor_type,
            "window_size":     count,              # How many readings were compressed
            "stats":           stats,              # The actual statistical data
            "metadata":        metadata,           # Latest non-numeric info
            "window_start_ts": readings[0].get("timestamp", ""),
            "window_end_ts":   readings[-1].get("timestamp", ""),
            "fog_aggregation_count": self.total_aggregated + 1,
        }

    @staticmethod
    def _extract_numeric_fields(readings: list) -> dict:
        """
        Scans all readings and groups numeric values by field name.

        e.g. for air quality readings:
        [
          {"pm25": 45.1, "co2": 480, "category": "MODERATE"},
          {"pm25": 47.3, "co2": 495, "category": "MODERATE"},
          ...
        ]
        Returns: {"pm25": [45.1, 47.3, ...], "co2": [480, 495, ...]}
        """
        numeric_fields = defaultdict(list)
        for reading in readings:
            for key, val in reading.items():
                if isinstance(val, (int, float)) and key not in ("seq", "hour_simulated"):
                    numeric_fields[key].append(val)
        return dict(numeric_fields)

    @property
    def buffer_fill(self) -> int:
        """How many readings are currently in the buffer (0 to window_size)."""
        return len(self._buffer)

    @property
    def bandwidth_reduction_ratio(self) -> float:
        """
        Calculates actual bandwidth reduction achieved so far.
        e.g. if 50 raw readings compressed into 5 aggregations = 10:1 ratio
        """
        if self.total_aggregated == 0:
            return 0.0
        total_sent = self.total_aggregated
        return round(self.total_received / total_sent, 1)


class Aggregator:
    """
    Manages ALL sensor buffers.

    One SensorBuffer per unique sensor_id.
    Buffers are created automatically when a new sensor is seen.
    """

    def __init__(self):
        # sensor_id → SensorBuffer
        self._buffers: dict[str, SensorBuffer] = {}

        # History of all aggregated payloads (for stats endpoint)
        self._aggregation_history: deque = deque(maxlen=HISTORY_SIZE)

        # Running totals
        self.total_raw_received  = 0
        self.total_aggregated_sent = 0

    def process(self, sensor_id: str, sensor_type: str,
                reading: dict) -> Optional[dict]:
        """
        Main entry point. Call this for every incoming sensor reading.

        Returns an aggregated payload if a window just completed.
        Returns None if still collecting.
        """
        self.total_raw_received += 1

        # Create buffer for new sensors automatically
        if sensor_id not in self._buffers:
            window = AGGREGATE_WINDOW.get(sensor_type, 5)
            self._buffers[sensor_id] = SensorBuffer(sensor_id, sensor_type, window)

        result = self._buffers[sensor_id].add(reading)

        if result:
            self.total_aggregated_sent += 1
            self._aggregation_history.append(result)

        return result

    def get_buffer_status(self) -> list:
        """
        Returns current fill level of every sensor buffer.
        Useful for the stats dashboard.
        e.g. [{"sensor": "air_02", "fill": "3/5", "total_received": 47}]
        """
        status = []
        for sid, buf in self._buffers.items():
            status.append({
                "sensor_id":    sid,
                "sensor_type":  buf.sensor_type,
                "buffer_fill":  f"{buf.buffer_fill}/{buf.window_size}",
                "total_received":   buf.total_received,
                "total_aggregated": buf.total_aggregated,
                "bandwidth_ratio":  f"{buf.bandwidth_reduction_ratio}:1",
            })
        return status

    def get_bandwidth_savings_pct(self) -> float:
        """
        Overall bandwidth savings across all sensors.
        e.g. 200 raw readings → 20 aggregated = 90% saving
        """
        if self.total_raw_received == 0:
            return 0.0
        saved = self.total_raw_received - self.total_aggregated_sent
        return round((saved / self.total_raw_received) * 100, 1)

    def get_recent_aggregations(self, n: int = 10) -> list:
        """Returns the last N aggregated payloads."""
        history = list(self._aggregation_history)
        return history[-n:]
