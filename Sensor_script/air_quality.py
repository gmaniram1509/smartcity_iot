# =============================================================
#  SMART CITY — AIR QUALITY SENSOR (PM2.5 + CO2)
#
#  This is the MOST IMPORTANT sensor in the project because
#  it's the one that triggers emergency alerts in the fog layer.
#
#  Tracks two values:
#    PM2.5  — Tiny particles from cars/factories (μg/m³)
#             > 80 triggers a CRITICAL alert in the fog layer
#    CO2    — Carbon dioxide (ppm)
#             > 1000 triggers a CRITICAL alert
#
#  Behaviour:
#    - Industrial zones (Zone_B) have a higher base pollution
#    - Rush hours (8–9am, 5–7pm) cause spikes
#    - Burst mode simulates a factory fire / accident
# =============================================================

from base_sensor import BaseSensor, drift, simulate_hour, is_rush_hour
from config import RANGES, BURST, INTERVALS, SENSORS, THRESHOLDS
import random


class AirQualitySensor(BaseSensor):

    def __init__(self, sensor_id: str, zone: str):
        super().__init__(
            sensor_id=sensor_id,
            zone=zone,
            interval=INTERVALS["air_quality"]
        )
        self.sensor_type = "air_quality"

        cfg = RANGES["air_quality"]
        self._pm25 = cfg["pm25_base"]
        self._co2  = cfg["co2_base"]

        # Industrial zones start with higher baseline pollution
        if zone == "Zone_B":
            self._pm25 += random.uniform(10, 20)
            self._co2  += random.uniform(50, 100)

    def _zone_multiplier(self) -> float:
        """
        Industrial zone has permanently higher pollution.
        Returns a multiplier applied to base values.
        """
        multipliers = {
            "Zone_A": 0.8,   # Residential — cleaner
            "Zone_B": 1.4,   # Industrial  — more polluted
            "Zone_C": 1.0,   # Commercial  — average
            "Zone_D": 1.2,   # Transport   — vehicles
        }
        return multipliers.get(self.zone, 1.0)

    def generate_reading(self) -> dict:
        cfg  = RANGES["air_quality"]
        hour = simulate_hour()
        rush = is_rush_hour(hour)
        mult = self._zone_multiplier()

        # Target PM2.5 depends on time of day and zone
        if rush:
            pm25_target = random.uniform(50, 75) * mult
            co2_target  = random.uniform(600, 750) * mult
        else:
            pm25_target = random.uniform(15, 40) * mult
            co2_target  = random.uniform(400, 520) * mult

        # Drift toward target
        self._pm25 += (pm25_target - self._pm25) * 0.12
        self._co2  += (co2_target  - self._co2)  * 0.10

        # Add small random noise on top of drift
        self._pm25 = drift(self._pm25, cfg["pm25_drift"],
                           cfg["pm25_min"], cfg["pm25_max"])
        self._co2  = drift(self._co2,  cfg["co2_drift"],
                           cfg["co2_min"], cfg["co2_max"])

        # Determine air quality category
        pm25 = round(self._pm25, 1)
        co2  = round(self._co2,  0)
        category = self._categorise_pm25(pm25)

        return {
            "pm25":     pm25,
            "co2":      int(co2),
            "unit_pm25": "ugm3",
            "unit_co2":  "ppm",
            "category": category,
            "rush_hour": rush,
        }

    def apply_burst(self) -> dict:
        """
        Burst = factory fire, accident, or severe pollution event.
        PM2.5 and CO2 spike well above alert thresholds.
        This is what triggers the fog layer's CRITICAL alert.
        """
        # Rapidly push toward spike values
        self._pm25 += (BURST["pm25_spike"] - self._pm25) * 0.25
        self._co2  += (BURST["co2_spike"]  - self._co2)  * 0.20

        # Add extra noise during burst
        self._pm25 += random.uniform(-3, 8)
        self._co2  += random.uniform(-10, 20)

        # Hard cap at max
        self._pm25 = min(self._pm25, RANGES["air_quality"]["pm25_max"])
        self._co2  = min(self._co2,  RANGES["air_quality"]["co2_max"])

        pm25 = round(self._pm25, 1)
        co2  = round(self._co2, 0)

        return {
            "pm25":      pm25,
            "co2":       int(co2),
            "unit_pm25": "ugm3",
            "unit_co2":  "ppm",
            "category":  self._categorise_pm25(pm25),
            "burst":     True,
        }

    @staticmethod
    def _categorise_pm25(pm25: float) -> str:
        """Human-readable air quality label."""
        if pm25 < 35:
            return "GOOD"
        elif pm25 < 55:
            return "MODERATE"
        elif pm25 < 80:
            return "UNHEALTHY"
        else:
            return "HAZARDOUS"   # ← Fog layer triggers alert here


# ── Run standalone for testing ────────────────────────────────
if __name__ == "__main__":
    import time
    print("Running Air Quality Sensor standalone (Ctrl+C to stop)")
    print(f"Alert threshold: PM2.5 > {THRESHOLDS['pm25_critical']} μg/m³\n")

    sensors = []
    for cfg in SENSORS["air_quality"]:
        s = AirQualitySensor(cfg["id"], cfg["zone"])
        s.run_in_thread()
        sensors.append(s)

    try:
        time.sleep(12)
        print("\n>>> Triggering POLLUTION BURST on air_02 (industrial zone)\n")
        sensors[1].trigger_burst(duration=20)
        time.sleep(40)
    except KeyboardInterrupt:
        print("\nStopped.")
