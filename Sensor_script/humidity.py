# =============================================================
#  SMART CITY — HUMIDITY SENSOR
#
#  Simulates humidity (moisture in the air).
#  Key behaviour:
#    - Inversely correlated with temperature:
#      hot day → lower humidity
#      cool morning → higher humidity
#    - Can spike to 90%+ to simulate rainfall
#    - Gradual drift — doesn't jump wildly
# =============================================================

from base_sensor import BaseSensor, drift, simulate_hour
from config import RANGES, BURST, INTERVALS, SENSORS
import random


class HumiditySensor(BaseSensor):

    def __init__(self, sensor_id: str, zone: str):
        super().__init__(
            sensor_id=sensor_id,
            zone=zone,
            interval=INTERVALS["humidity"]
        )
        self.sensor_type   = "humidity"
        self._current      = RANGES["humidity"]["base"]
        self._raining      = False
        self._rain_end     = 0

    def _maybe_start_rain(self):
        """
        Small random chance each tick of it starting to rain.
        Rain raises humidity sharply to 85–95%.
        Lasts 2–5 minutes (simulated).
        """
        import time
        if not self._raining and random.random() < 0.002:  # 0.2% chance per tick
            self._raining  = True
            self._rain_end = time.time() + random.randint(120, 300)  # 2–5 mins
            self.logger.info("🌧 Rain event started")

        if self._raining and time.time() > self._rain_end:
            self._raining = False
            self.logger.info("☀️ Rain event ended")

    def generate_reading(self) -> dict:
        cfg  = RANGES["humidity"]
        hour = simulate_hour()

        self._maybe_start_rain()

        if self._raining:
            # During rain, push toward high humidity
            target = random.uniform(82, 95)
        else:
            # Normal: cooler morning = more humid, hot afternoon = less humid
            if 6 <= hour <= 10:
                target = random.uniform(60, 75)  # Humid morning
            elif 11 <= hour <= 17:
                target = random.uniform(35, 55)  # Drier afternoon
            else:
                target = random.uniform(55, 70)  # Evening

        # Drift toward target
        self._current += (target - self._current) * 0.08
        self._current  = drift(
            self._current,
            cfg["drift"],
            cfg["min"],
            cfg["max"]
        )

        return {
            "value":   round(self._current, 1),
            "unit":    "percent",
            "raining": self._raining,
        }

    def apply_burst(self) -> dict:
        """Burst = sudden downpour → humidity spikes."""
        self._raining = True
        self._current = drift(self._current, 1.5, 20, 95)
        self._current += (92 - self._current) * 0.2

        return {
            "value":   round(self._current, 1),
            "unit":    "percent",
            "raining": True,
            "burst":   True,
        }


# ── Run standalone for testing ────────────────────────────────
if __name__ == "__main__":
    print("Running Humidity Sensor standalone test (Ctrl+C to stop)\n")
    for cfg in SENSORS["humidity"]:
        sensor = HumiditySensor(cfg["id"], cfg["zone"])
        sensor.run_in_thread()

    try:
        import time
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopped.")
