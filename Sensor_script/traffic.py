# =============================================================
#  SMART CITY — TRAFFIC SENSOR
#
#  Simulates a road-embedded loop sensor or camera system.
#  Tracks three values per reading:
#
#  1. vehicle_count  — Cars passing per minute
#     Night: 3–15 vehicles   Rush: 90–130 vehicles
#
#  2. avg_speed_kmh  — Average speed of vehicles
#     Free flow: 60–100 km/h   Congestion: 5–20 km/h
#     KEY INSIGHT: high count + low speed = CONGESTION
#
#  3. congestion_index — Calculated score 0.0–1.0
#     0.0 = completely free   1.0 = gridlock
#     Formula: high vehicles + low speed = high index
#     > 0.7 triggers fog layer CONGESTION alert
#
#  Behaviour:
#    - Rush hours see massive spikes in count & drops in speed
#    - Zone_D (transport hub) always has more traffic
#    - Burst mode = accident / road closure causing gridlock
# =============================================================

from base_sensor import BaseSensor, drift, simulate_hour, is_rush_hour
from config import RANGES, BURST, INTERVALS, SENSORS, THRESHOLDS
import random
import math


class TrafficSensor(BaseSensor):

    def __init__(self, sensor_id: str, zone: str):
        super().__init__(
            sensor_id=sensor_id,
            zone=zone,
            interval=INTERVALS["traffic"]
        )
        self.sensor_type     = "traffic"
        cfg                  = RANGES["traffic"]
        self._count          = float(cfg["count_base"])
        self._speed          = float(cfg["speed_base"])
        self._incident_active = False  # Simulates an accident on the road

    def _zone_traffic_multiplier(self) -> float:
        """
        Transport hub (Zone_D) has higher baseline traffic.
        """
        return {
            "Zone_A": 0.5,   # Residential — low traffic
            "Zone_B": 0.7,   # Industrial  — medium (delivery trucks)
            "Zone_C": 1.0,   # Commercial  — average
            "Zone_D": 1.5,   # Transport   — busiest
        }.get(self.zone, 1.0)

    def _target_values(self, hour: int):
        """
        Returns (target_count, target_speed) for the given simulated hour.
        These represent what the values should be drifting toward.
        """
        rush = is_rush_hour(hour)
        mult = self._zone_traffic_multiplier()

        if 0 <= hour < 6:
            # Late night: almost no traffic, fast speeds
            count = random.uniform(2, 12) * mult
            speed = random.uniform(70, 100)

        elif rush:
            # Rush hour: heavy traffic, slow speeds
            count = random.uniform(75, 125) * mult
            speed = random.uniform(8, 25)

        elif 6 <= hour < 8 or 19 <= hour < 22:
            # Pre/post rush: moderate traffic
            count = random.uniform(35, 65) * mult
            speed = random.uniform(35, 55)

        elif 9 <= hour < 12 or 14 <= hour < 17:
            # Normal daytime
            count = random.uniform(20, 50) * mult
            speed = random.uniform(45, 70)

        elif 12 <= hour < 14:
            # Lunch: slight increase
            count = random.uniform(45, 70) * mult
            speed = random.uniform(30, 50)

        else:
            # Evening
            count = random.uniform(15, 40) * mult
            speed = random.uniform(50, 75)

        # Incident on road = gridlock
        if self._incident_active:
            count *= 0.4    # Fewer cars getting through
            speed  = random.uniform(3, 12)  # Near standstill

        return count, speed

    def _calc_congestion_index(self, count: float, speed: float) -> float:
        """
        Calculates a congestion score from 0.0 to 1.0.

        Formula logic:
          - Normalise vehicle count: 0 = empty road, 1 = max capacity
          - Normalise speed inversely: 0 = fast (good), 1 = slow (bad)
          - Weighted average: speed matters more than count

        A road with 100 vehicles at 80km/h is NOT congested.
        A road with 100 vehicles at 10km/h IS congested.
        """
        max_count = RANGES["traffic"]["count_max"]
        max_speed = RANGES["traffic"]["speed_max"]

        # Normalise count: 0.0 (empty) → 1.0 (max capacity)
        norm_count = min(count / max_count, 1.0)

        # Normalise speed INVERSELY: 0.0 (fast/good) → 1.0 (slow/bad)
        norm_speed_bad = 1.0 - min(speed / max_speed, 1.0)

        # Weighted: speed is 60% of the index, count is 40%
        index = (0.6 * norm_speed_bad) + (0.4 * norm_count)

        return round(min(max(index, 0.0), 1.0), 2)

    def generate_reading(self) -> dict:
        cfg  = RANGES["traffic"]
        hour = simulate_hour()

        target_count, target_speed = self._target_values(hour)

        # Drift current values toward targets
        self._count += (target_count - self._count) * 0.12
        self._speed += (target_speed - self._speed) * 0.12

        # Add small tick-to-tick noise
        self._count = drift(self._count, cfg["count_drift"],
                            cfg["count_min"], cfg["count_max"])
        self._speed = drift(self._speed, cfg["speed_drift"],
                            cfg["speed_min"], cfg["speed_max"])

        count = max(0, int(round(self._count)))
        speed = max(0, round(self._speed, 1))
        cong  = self._calc_congestion_index(count, speed)

        return {
            "vehicle_count":   count,
            "avg_speed_kmh":   speed,
            "congestion_index": cong,
            "congestion_level": self._categorise_congestion(cong),
            "rush_hour":        is_rush_hour(hour),
        }

    def apply_burst(self) -> dict:
        """
        Burst = road accident or emergency causing gridlock.
        Vehicle count drops (blocked), speed near zero.
        Congestion index shoots up to 0.9+.
        """
        self._incident_active = True

        # Gridlock: few cars getting through, all very slow
        self._count = drift(self._count, 2, 0, 30)
        self._speed = drift(self._speed, 1, 3, 15)
        self._speed = min(self._speed, BURST["speed_drop"] + random.uniform(0, 5))

        count = max(0, int(round(self._count)))
        speed = max(3, round(self._speed, 1))
        cong  = self._calc_congestion_index(
            BURST["traffic_spike"], speed  # High theoretical demand, low throughput
        )

        return {
            "vehicle_count":    count,
            "avg_speed_kmh":    speed,
            "congestion_index": max(cong, 0.85),  # Force high congestion in burst
            "congestion_level": "GRIDLOCK",
            "incident":         True,
            "burst":            True,
        }

    @staticmethod
    def _categorise_congestion(index: float) -> str:
        if index < 0.25:
            return "FREE_FLOW"
        elif index < 0.50:
            return "LIGHT"
        elif index < 0.70:
            return "MODERATE"
        elif index < 0.85:
            return "HEAVY"       # ← Fog layer warning
        else:
            return "GRIDLOCK"    # ← Fog layer critical alert


# ── Run standalone for testing ────────────────────────────────
if __name__ == "__main__":
    import time
    print("Running Traffic Sensor standalone (Ctrl+C to stop)")
    print(f"Congestion alert threshold: index > 0.7\n")

    sensors = []
    for cfg in SENSORS["traffic"]:
        s = TrafficSensor(cfg["id"], cfg["zone"])
        s.run_in_thread()
        sensors.append(s)

    try:
        time.sleep(10)
        print("\n>>> Triggering TRAFFIC BURST (simulating accident) on traffic_01\n")
        sensors[0].trigger_burst(duration=20)
        time.sleep(40)
    except KeyboardInterrupt:
        print("\nStopped.")
