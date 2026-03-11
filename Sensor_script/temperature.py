# =============================================================
#  SMART CITY — TEMPERATURE SENSOR
#
#  Simulates a temperature sensor on a lamp post.
#  Values drift slowly and follow a day/night cycle:
#    - Night (0–6):   cooler, around 14–18°C
#    - Morning (6–12): warming up
#    - Afternoon (12–17): peak heat
#    - Evening (17–23): cooling down
# =============================================================

from base_sensor import BaseSensor, drift, simulate_hour, is_rush_hour
from config import RANGES, BURST, INTERVALS, SENSORS
import random


class TemperatureSensor(BaseSensor):

    def __init__(self, sensor_id: str, zone: str):
        super().__init__(
            sensor_id=sensor_id,
            zone=zone,
            interval=INTERVALS["temperature"]
        )
        self.sensor_type = "temperature"

        # Start at base temperature
        cfg = RANGES["temperature"]
        self._current = cfg["base"]

    def _target_for_hour(self, hour: int) -> float:
        """
        Returns the 'target' temperature for a given hour.
        The actual value drifts toward this target slowly.
        This creates the day/night cycle.
        """
        # Simple sinusoidal-like mapping:
        # hour 3  → coldest (~14°C)
        # hour 14 → hottest (~32°C)
        cfg = RANGES["temperature"]
        night = cfg["night_base"]
        day   = cfg["day_base"]

        # Map hour to 0.0–1.0 where 1.0 = hottest
        if 0 <= hour < 6:
            factor = 0.0             # Night: cold
        elif 6 <= hour < 12:
            factor = (hour - 6) / 6  # Morning: warming up 0→1
        elif 12 <= hour < 17:
            factor = 1.0             # Afternoon: peak heat
        elif 17 <= hour < 21:
            factor = (21 - hour) / 4 # Evening: cooling 1→0
        else:
            factor = 0.0             # Late night: cold again

        return night + factor * (day - night)

    def generate_reading(self) -> dict:
        cfg  = RANGES["temperature"]
        hour = simulate_hour()

        # Nudge current value toward the hour's target
        target = self._target_for_hour(hour)
        # Move 10% toward target each tick, plus small random drift
        self._current += (target - self._current) * 0.1
        self._current  = drift(
            self._current,
            cfg["drift"],
            cfg["min"],
            cfg["max"]
        )

        return {
            "value": round(self._current, 1),
            "unit":  "celsius",
            "hour_simulated": hour,
        }

    def apply_burst(self) -> dict:
        """Simulate a heatwave or industrial heat event."""
        self._current = drift(
            self._current,
            0.8,                      # Faster drift during burst
            RANGES["temperature"]["min"],
            RANGES["temperature"]["max"]
        )
        # Push toward spike temperature
        self._current += (BURST["temp_spike"] - self._current) * 0.15

        return {
            "value": round(self._current, 1),
            "unit":  "celsius",
            "burst": True,
        }


# ── Run standalone for testing ────────────────────────────────
if __name__ == "__main__":
    print("Running Temperature Sensor standalone test (Ctrl+C to stop)\n")
    for cfg in SENSORS["temperature"]:
        sensor = TemperatureSensor(cfg["id"], cfg["zone"])
        sensor.run_in_thread()

    try:
        import time
        # After 10 seconds, trigger burst to test it
        time.sleep(10)
        print("\n>>> Triggering BURST mode on temp_01\n")
        sensor.trigger_burst(duration=15)
        time.sleep(30)
    except KeyboardInterrupt:
        print("\nStopped.")
