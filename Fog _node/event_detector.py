# =============================================================
#  SMART CITY — FOG LAYER: EVENT DETECTOR
#
#  WHAT THIS DOES (plain English):
#  ─────────────────────────────────────────────────────────────
#  This is the "brain" of the fog layer. It watches every
#  incoming reading and asks: "Does this need immediate action?"
#
#  If PM2.5 suddenly jumps above 80 μg/m³, the city needs to
#  know RIGHT NOW — not in 30 seconds when the next aggregation
#  batch is ready.
#
#  The event detector triggers IMMEDIATE alerts for:
#    🌫️  Air pollution spikes  (PM2.5 > 80 μg/m³)
#    🚗  Traffic congestion    (index > 0.85)
#    🔊  Noise emergencies     (> 85 dB)
#    🌡️  Heatwave alerts       (> 39°C)
#    💧  Flood risk            (humidity > 95%)
#
#  These alerts BYPASS the aggregation queue and go straight
#  to the cloud. This is the latency benefit of fog computing:
#    Without fog: sensor → cloud (30s aggregation delay)
#    With fog:    sensor → fog → immediate alert (< 1s)
#
#  Also implements COOLDOWN to prevent alert storms:
#    If PM2.5 stays high, you don't want 1000 identical alerts.
#    After triggering, the detector waits N seconds before
#    it can trigger the same alert again.
# =============================================================

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional
from fog_config import ALERT_RULES


# Cooldown period in seconds — prevents alert spam
# e.g. if PM2.5 stays above threshold, only alert every 30 seconds
ALERT_COOLDOWN = {
    "critical": 30,   # seconds between repeated critical alerts
    "warning":  60,   # seconds between repeated warning alerts
}

# Severity levels
CRITICAL = "CRITICAL"
WARNING  = "WARNING"
INFO     = "INFO"


class Event:
    """
    Represents a detected event/alert.
    Sent immediately to the cloud bypassing the aggregation queue.
    """
    def __init__(self, sensor_id: str, sensor_type: str, location: str,
                 severity: str, event_type: str, message: str,
                 field: str, value, threshold: float):
        self.sensor_id   = sensor_id
        self.sensor_type = sensor_type
        self.location    = location
        self.severity    = severity
        self.event_type  = event_type    # e.g. "POLLUTION_SPIKE"
        self.message     = message
        self.field       = field         # e.g. "pm25"
        self.value       = value
        self.threshold   = threshold
        self.timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        return {
            "event":       True,
            "event_type":  self.event_type,
            "severity":    self.severity,
            "sensor_id":   self.sensor_id,
            "sensor_type": self.sensor_type,
            "location":    self.location,
            "field":       self.field,
            "value":       self.value,
            "threshold":   self.threshold,
            "message":     self.message,
            "timestamp":   self.timestamp,
        }

    def __repr__(self):
        return (f"[{self.severity}] {self.event_type} | "
                f"{self.sensor_id} | {self.field}={self.value}")


class EventDetector:
    """
    Rule-based event detection engine.

    Processes every incoming sensor reading and checks it
    against threshold rules. Fires Events when rules are breached.

    Uses per-sensor cooldown timers to prevent alert flooding.
    """

    def __init__(self):
        # Last time each alert was fired: sensor_id+event_type → timestamp
        self._last_alert_time: dict = defaultdict(float)

        # All events fired (kept for dashboard display)
        self._event_history: deque = deque(maxlen=200)

        # Stats
        self.total_events_fired    = 0
        self.total_critical_events = 0
        self.total_warning_events  = 0
        self.total_suppressed      = 0  # Alerts suppressed by cooldown

    # ──────────────────────────────────────────────────────────
    # PUBLIC: Main entry point
    # ──────────────────────────────────────────────────────────
    def check(self, sensor_id: str, sensor_type: str,
              location: str, reading: dict) -> Optional[Event]:
        """
        Check a reading against all rules for its sensor type.

        Returns an Event if a threshold is breached (and cooldown passed).
        Returns None if everything is normal (or cooldown active).
        """
        # Route to the correct rule checker based on sensor type
        checker = {
            "air_quality": self._check_air_quality,
            "noise":       self._check_noise,
            "temperature": self._check_temperature,
            "traffic":     self._check_traffic,
            "humidity":    self._check_humidity,
        }.get(sensor_type)

        if not checker:
            return None

        event = checker(sensor_id, sensor_type, location, reading)

        if event:
            cooldown = ALERT_COOLDOWN.get(event.severity.lower(),
                                          ALERT_COOLDOWN["warning"])
            key = f"{sensor_id}:{event.event_type}"

            # Check cooldown — suppress if fired too recently
            if time.time() - self._last_alert_time[key] < cooldown:
                self.total_suppressed += 1
                return None

            # Fire the event
            self._last_alert_time[key] = time.time()
            self._event_history.append(event)
            self.total_events_fired += 1

            if event.severity == CRITICAL:
                self.total_critical_events += 1
            else:
                self.total_warning_events += 1

        return event

    # ──────────────────────────────────────────────────────────
    # RULE CHECKERS (one per sensor type)
    # ──────────────────────────────────────────────────────────
    def _check_air_quality(self, sensor_id, sensor_type,
                            location, reading) -> Optional[Event]:
        rules = ALERT_RULES.get("air_quality", {})
        pm25  = reading.get("pm25")
        co2   = reading.get("co2")

        # PM2.5 check — most important air quality metric
        if pm25 is not None and "pm25" in rules:
            pm25_rules = rules["pm25"]
            if pm25 >= pm25_rules.get("critical", 999):
                return Event(
                    sensor_id=sensor_id, sensor_type=sensor_type,
                    location=location, severity=CRITICAL,
                    event_type="POLLUTION_SPIKE",
                    message=(
                        f"CRITICAL: PM2.5 level {pm25} μg/m³ in {location}. "
                        f"Threshold: {pm25_rules['critical']} μg/m³. "
                        f"Immediate action required — notify citizens."
                    ),
                    field="pm25", value=pm25,
                    threshold=pm25_rules["critical"]
                )
            elif pm25 >= pm25_rules.get("warning", 999):
                return Event(
                    sensor_id=sensor_id, sensor_type=sensor_type,
                    location=location, severity=WARNING,
                    event_type="AIR_QUALITY_WARNING",
                    message=(
                        f"WARNING: PM2.5 rising — {pm25} μg/m³ in {location}. "
                        f"Monitoring closely."
                    ),
                    field="pm25", value=pm25,
                    threshold=pm25_rules["warning"]
                )

        # CO2 check
        if co2 is not None and "co2" in rules:
            co2_rules = rules["co2"]
            if co2 >= co2_rules.get("critical", 999):
                return Event(
                    sensor_id=sensor_id, sensor_type=sensor_type,
                    location=location, severity=CRITICAL,
                    event_type="CO2_CRITICAL",
                    message=(
                        f"CRITICAL: CO2 at {co2} ppm in {location}. "
                        f"Ventilation required immediately."
                    ),
                    field="co2", value=co2,
                    threshold=co2_rules["critical"]
                )
            elif co2 >= co2_rules.get("warning", 999):
                return Event(
                    sensor_id=sensor_id, sensor_type=sensor_type,
                    location=location, severity=WARNING,
                    event_type="CO2_WARNING",
                    message=f"WARNING: CO2 elevated at {co2} ppm in {location}.",
                    field="co2", value=co2,
                    threshold=co2_rules["warning"]
                )
        return None

    def _check_noise(self, sensor_id, sensor_type,
                     location, reading) -> Optional[Event]:
        rules = ALERT_RULES.get("noise", {}).get("value", {})
        val   = reading.get("value")
        if val is None:
            return None

        if val >= rules.get("critical", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=CRITICAL,
                event_type="NOISE_EMERGENCY",
                message=(
                    f"CRITICAL: Noise level {val} dB in {location}. "
                    f"Exceeds safe limit of {rules['critical']} dB. "
                    f"Potential hearing damage risk."
                ),
                field="value", value=val,
                threshold=rules["critical"]
            )
        elif val >= rules.get("warning", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=WARNING,
                event_type="NOISE_WARNING",
                message=f"WARNING: Noise at {val} dB in {location}.",
                field="value", value=val,
                threshold=rules["warning"]
            )
        return None

    def _check_temperature(self, sensor_id, sensor_type,
                            location, reading) -> Optional[Event]:
        rules = ALERT_RULES.get("temperature", {}).get("value", {})
        val   = reading.get("value")
        if val is None:
            return None

        if val >= rules.get("critical", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=CRITICAL,
                event_type="HEATWAVE_ALERT",
                message=(
                    f"CRITICAL: Temperature {val}°C in {location}. "
                    f"Heatwave conditions — public health risk."
                ),
                field="value", value=val,
                threshold=rules["critical"]
            )
        elif val >= rules.get("warning", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=WARNING,
                event_type="HIGH_TEMPERATURE",
                message=f"WARNING: High temperature {val}°C in {location}.",
                field="value", value=val,
                threshold=rules["warning"]
            )
        return None

    def _check_traffic(self, sensor_id, sensor_type,
                        location, reading) -> Optional[Event]:
        """
        Traffic congestion requires TWO conditions BOTH to be true:
          1. Congestion index is high (>= threshold)
          2. AND vehicle count is high
        This prevents false alerts when roads are simply quiet.
        """
        idx_rules   = ALERT_RULES.get("traffic", {}).get("congestion_index", {})
        count_rules = ALERT_RULES.get("traffic", {}).get("vehicle_count", {})

        cong_idx = reading.get("congestion_index", 0)
        count    = reading.get("vehicle_count", 0)
        speed    = reading.get("avg_speed_kmh", 999)

        if cong_idx >= idx_rules.get("critical", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=CRITICAL,
                event_type="TRAFFIC_GRIDLOCK",
                message=(
                    f"CRITICAL: Gridlock in {location}. "
                    f"Congestion index: {cong_idx:.2f}. "
                    f"{count} vehicles/min at {speed} km/h. "
                    f"Activate traffic management protocol."
                ),
                field="congestion_index", value=cong_idx,
                threshold=idx_rules["critical"]
            )
        elif cong_idx >= idx_rules.get("warning", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=WARNING,
                event_type="TRAFFIC_CONGESTION",
                message=(
                    f"WARNING: Traffic building in {location}. "
                    f"Index: {cong_idx:.2f}, Speed: {speed} km/h."
                ),
                field="congestion_index", value=cong_idx,
                threshold=idx_rules["warning"]
            )
        return None

    def _check_humidity(self, sensor_id, sensor_type,
                         location, reading) -> Optional[Event]:
        rules = ALERT_RULES.get("humidity", {}).get("value", {})
        val   = reading.get("value")
        if val is None:
            return None

        if val >= rules.get("critical", 999):
            return Event(
                sensor_id=sensor_id, sensor_type=sensor_type,
                location=location, severity=WARNING,
                event_type="HUMIDITY_CRITICAL",
                message=(
                    f"WARNING: Humidity at {val}% in {location}. "
                    f"Flood risk — check drainage systems."
                ),
                field="value", value=val,
                threshold=rules["critical"]
            )
        return None

    # ──────────────────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────────────────
    def get_recent_events(self, n: int = 20) -> list:
        return [e.to_dict() for e in list(self._event_history)[-n:]]

    def get_stats(self) -> dict:
        return {
            "total_events_fired":    self.total_events_fired,
            "total_critical":        self.total_critical_events,
            "total_warnings":        self.total_warning_events,
            "total_suppressed":      self.total_suppressed,
            "recent_events":         self.get_recent_events(10),
        }
