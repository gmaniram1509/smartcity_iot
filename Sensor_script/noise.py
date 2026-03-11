# =============================================================
#  SMART CITY — NOISE LEVEL SENSOR
#
#  Simulates a sound level meter on a building wall.
#  Values measured in decibels (dB).
#
#  Real-world reference points baked into the simulation:
#    28 dB  → Dead quiet (3am in a residential area)
#    50 dB  → Normal conversation / light traffic
#    70 dB  → Busy street during the day
#    85 dB  → Threshold for hearing damage — triggers alert
#    90 dB  → Heavy truck / construction
#    100 dB → Jackhammer / live music event
#
#  Behaviour:
#    - Quiet at night (28–45 dB)
#    - Loud during rush hours (68–82 dB)
#    - Commercial zone (Zone_C) has event spikes (concerts, etc.)
#    - Burst mode = large outdoor event or construction work
# =============================================================

from base_sensor import BaseSensor, drift, simulate_hour, is_rush_hour
from config import RANGES, BURST, INTERVALS, SENSORS, THRESHOLDS
import random
import time


class NoiseSensor(BaseSensor):

    def __init__(self, sensor_id: str, zone: str):
        super().__init__(
            sensor_id=sensor_id,
            zone=zone,
            interval=INTERVALS["noise"]
        )
        self.sensor_type = "noise"
        self._current    = RANGES["noise"]["base"]
        self._event_active = False   # Simulates a loud event (concert, roadwork)
        self._event_end    = 0

    def _maybe_start_event(self, hour: int):
        """
        Small chance each tick of a noise event starting.
        Events are more likely in Zone_C (commercial) and during daytime.
        """
        is_daytime = 8 <= hour <= 22
        zone_factor = 0.003 if self.zone == "Zone_C" else 0.001

        if not self._event_active and is_daytime and random.random() < zone_factor:
            duration = random.randint(60, 180)   # 1–3 minute event
            self._event_active = True
            self._event_end    = time.time() + duration
            self.logger.info(f"🎵 Noise event started in {self.zone} for {duration}s")

        if self._event_active and time.time() > self._event_end:
            self._event_active = False
            self.logger.info(f"🔇 Noise event ended in {self.zone}")

    def _target_noise_level(self, hour: int) -> float:
        """
        Returns expected noise level based on time of day and zone.
        """
        rush = is_rush_hour(hour)

        # Base target by time of day
        if 0 <= hour < 6:
            base = random.uniform(28, 42)   # Very quiet at night
        elif rush:
            base = random.uniform(65, 80)   # Loud during rush hour
        elif 9 <= hour < 12 or 14 <= hour < 17:
            base = random.uniform(55, 70)   # Busy daytime
        elif 12 <= hour < 14:
            base = random.uniform(60, 72)   # Lunch time
        else:
            base = random.uniform(45, 60)   # Quiet evening

        # Zone adjustment
        zone_adj = {
            "Zone_A": -5,    # Residential is quieter
            "Zone_B": +3,    # Industrial has machinery hum
            "Zone_C": +5,    # Commercial is busier
            "Zone_D": +8,    # Transport hub is loudest
        }
        base += zone_adj.get(self.zone, 0)

        # Event spike
        if self._event_active:
            base += random.uniform(12, 20)

        return base

    def generate_reading(self) -> dict:
        cfg  = RANGES["noise"]
        hour = simulate_hour()

        self._maybe_start_event(hour)
        target = self._target_noise_level(hour)

        # Noise changes faster than temperature so use larger drift factor
        self._current += (target - self._current) * 0.15
        self._current  = drift(
            self._current,
            cfg["drift"],
            cfg["min"],
            cfg["max"]
        )

        db       = round(self._current, 1)
        category = self._categorise_noise(db)

        return {
            "value":    db,
            "unit":     "decibels",
            "category": category,
            "event":    self._event_active,
        }

    def apply_burst(self) -> dict:
        """
        Burst = construction work, festival, emergency vehicle sirens,
        or any sudden loud event.
        """
        self._event_active = True
        self._current += (BURST["noise_spike"] - self._current) * 0.3
        self._current  = min(self._current + random.uniform(0, 4), 105)

        db = round(self._current, 1)
        return {
            "value":    db,
            "unit":     "decibels",
            "category": self._categorise_noise(db),
            "event":    True,
            "burst":    True,
        }

    @staticmethod
    def _categorise_noise(db: float) -> str:
        if db < 50:
            return "QUIET"
        elif db < 70:
            return "MODERATE"
        elif db < 85:
            return "LOUD"
        else:
            return "DANGEROUS"   # ← Fog layer triggers alert here


# ── Run standalone for testing ────────────────────────────────
if __name__ == "__main__":
    print("Running Noise Sensor standalone (Ctrl+C to stop)")
    print(f"Alert threshold: Noise > {THRESHOLDS['noise_critical']} dB\n")

    sensors = []
    for cfg in SENSORS["noise"]:
        s = NoiseSensor(cfg["id"], cfg["zone"])
        s.run_in_thread()
        sensors.append(s)

    try:
        time.sleep(10)
        print("\n>>> Triggering NOISE BURST on noise_01\n")
        sensors[0].trigger_burst(duration=15)
        time.sleep(30)
    except KeyboardInterrupt:
        print("\nStopped.")
