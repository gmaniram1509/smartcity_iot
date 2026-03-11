# =============================================================
#  SMART CITY — BASE SENSOR CLASS
#
#  Every sensor (temp, noise, traffic, etc.) inherits from this.
#  It handles the shared logic so each sensor script only needs
#  to focus on generating its OWN specific values.
#
#  Think of this as the "body" of a sensor. The individual
#  sensor scripts are just the "brain" that decides what number
#  to produce. The body (this file) handles everything else:
#    - Connecting to the fog node
#    - Formatting the JSON payload
#    - Sending the data
#    - Running the loop every N seconds
#    - Handling burst mode
# =============================================================

import json
import time
import random
import threading
import requests
import logging
from datetime import datetime, timezone
from abc import ABC, abstractmethod

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

from config import FOG_NODE_URL, USE_HTTP, MQTT_BROKER, MQTT_PORT, MQTT_TOPIC

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)


class BaseSensor(ABC):
    """
    Base class for all city sensors.

    To create a new sensor type, you:
      1. Inherit from BaseSensor
      2. Set self.sensor_type in __init__
      3. Implement generate_reading() → returns a dict of values
      4. Implement apply_burst() → returns burst values
      That's it. This class handles everything else.
    """

    def __init__(self, sensor_id: str, zone: str, interval: float):
        """
        sensor_id : unique ID e.g. "temp_01"
        zone      : city zone e.g. "Zone_A"
        interval  : seconds between each reading
        """
        self.sensor_id   = sensor_id
        self.zone        = zone
        self.interval    = interval
        self.sensor_type = "base"          # Overridden by each subclass
        self.is_running  = False
        self.burst_active = False
        self.burst_end_time = 0
        self.reading_count  = 0            # How many readings sent so far
        self.logger = logging.getLogger(sensor_id)

        # MQTT client (only set up if needed)
        self._mqtt_client = None
        if not USE_HTTP and MQTT_AVAILABLE:
            self._setup_mqtt()

    # ── MQTT setup ────────────────────────────────────────────
    def _setup_mqtt(self):
        self._mqtt_client = mqtt.Client(client_id=self.sensor_id)
        try:
            self._mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self._mqtt_client.loop_start()
            self.logger.info(f"MQTT connected to {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            self.logger.warning(f"MQTT connection failed: {e}. Falling back to HTTP.")
            self._mqtt_client = None

    # ── Abstract methods (every sensor MUST implement these) ──
    @abstractmethod
    def generate_reading(self) -> dict:
        """
        Produce a dict of sensor-specific values.
        Example for temperature: {"value": 23.4, "unit": "celsius"}
        """
        pass

    @abstractmethod
    def apply_burst(self) -> dict:
        """
        Produce burst/spike values when burst mode is active.
        Example: {"value": 38.5, "unit": "celsius"}
        """
        pass

    # ── Burst mode control ────────────────────────────────────
    def trigger_burst(self, duration: int = 30):
        """
        Call this from outside (e.g. run_all_sensors.py) to
        simulate an emergency spike in readings.
        """
        self.burst_active   = True
        self.burst_end_time = time.time() + duration
        self.logger.warning(
            f"🚨 BURST MODE ACTIVATED for {duration}s on {self.sensor_id}"
        )

    def _check_burst_expired(self):
        """Automatically deactivates burst when duration is over."""
        if self.burst_active and time.time() > self.burst_end_time:
            self.burst_active = False
            self.logger.info(f"✅ Burst mode ended on {self.sensor_id}")

    # ── Payload builder ───────────────────────────────────────
    def _build_payload(self, reading: dict) -> dict:
        """
        Wraps the sensor reading in a standard envelope.
        Every sensor, regardless of type, sends this same structure.
        The fog node knows what to expect.
        """
        return {
            "sensor_id":  self.sensor_id,
            "type":       self.sensor_type,
            "location":   self.zone,
            "data":       reading,
            "burst_mode": self.burst_active,
            "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seq":        self.reading_count,   # Sequence number — useful for detecting gaps
        }

    # ── Sending data ──────────────────────────────────────────
    def _send_http(self, payload: dict):
        """POST the JSON payload to the fog node's HTTP endpoint."""
        try:
            response = requests.post(
                FOG_NODE_URL,
                json=payload,
                timeout=3,
                headers={"Content-Type": "application/json"}
            )
            if response.status_code == 200:
                self.logger.info(
                    f"✓ Sent reading #{self.reading_count} | "
                    f"{json.dumps(payload['data'])}"
                )
            else:
                self.logger.warning(
                    f"⚠ Fog node returned {response.status_code}"
                )
        except requests.exceptions.ConnectionError:
            # Fog node not running yet — just print locally
            self.logger.info(
                f"[NO FOG NODE] Reading #{self.reading_count}: "
                f"{json.dumps(payload['data'])}"
            )
        except requests.exceptions.Timeout:
            self.logger.warning("⚠ Fog node timed out")

    def _send_mqtt(self, payload: dict):
        """Publish the JSON payload to the MQTT broker."""
        if self._mqtt_client:
            topic = f"{MQTT_TOPIC}/{self.sensor_type}/{self.sensor_id}"
            self._mqtt_client.publish(topic, json.dumps(payload), qos=1)
            self.logger.info(
                f"✓ MQTT published to {topic} | {json.dumps(payload['data'])}"
            )
        else:
            self._send_http(payload)  # Fallback

    def send(self, payload: dict):
        """Route to HTTP or MQTT based on config."""
        if USE_HTTP:
            self._send_http(payload)
        else:
            self._send_mqtt(payload)

    # ── Main run loop ─────────────────────────────────────────
    def run(self):
        """
        The main loop. Runs forever until stop() is called.
        Every N seconds:
          1. Check if burst mode has expired
          2. Generate a reading (normal or burst)
          3. Wrap it in a payload
          4. Send it to the fog node
          5. Sleep for interval seconds
        """
        self.is_running = True
        self.logger.info(
            f"🟢 Started | Zone: {self.zone} | Interval: {self.interval}s"
        )

        while self.is_running:
            try:
                self._check_burst_expired()

                # Choose normal or burst reading
                if self.burst_active:
                    reading = self.apply_burst()
                else:
                    reading = self.generate_reading()

                self.reading_count += 1
                payload = self._build_payload(reading)
                self.send(payload)

            except Exception as e:
                self.logger.error(f"Error generating reading: {e}")

            time.sleep(self.interval)

    def stop(self):
        """Gracefully stop the sensor loop."""
        self.is_running = False
        self.logger.info(f"🔴 Stopped after {self.reading_count} readings")
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()

    def run_in_thread(self) -> threading.Thread:
        """
        Convenience method: starts this sensor in a background thread.
        Called by run_all_sensors.py so all sensors run simultaneously.
        """
        thread = threading.Thread(
            target=self.run,
            name=self.sensor_id,
            daemon=True   # Thread dies automatically when main program exits
        )
        thread.start()
        return thread


# ── Helper: Realistic drift function ─────────────────────────
def drift(current: float, drift_amount: float,
          min_val: float, max_val: float) -> float:
    """
    Moves a value slightly up or down each tick.
    Stays within min/max bounds.

    This is what makes sensor data look realistic instead of
    random jumps. Temperature doesn't go 22 → 35 → 14 → 29.
    It goes 22 → 22.3 → 22.1 → 22.6 → 23.0 ...

    current      : current value
    drift_amount : max change per tick (e.g. 0.4 for temperature)
    min_val      : never go below this
    max_val      : never go above this
    """
    change = random.uniform(-drift_amount, drift_amount)
    new_val = current + change
    return round(max(min_val, min(max_val, new_val)), 2)


def simulate_hour() -> int:
    """
    Returns a simulated hour of day (0–23).
    Since we're running a simulation, we speed up time:
    1 real second = 1 simulated minute.
    So a full simulated day takes 24 minutes of real time.
    """
    seconds_in_day = 24 * 60  # 1440 simulated minutes = 1440 real seconds
    current_second = int(time.time()) % seconds_in_day
    return current_second // 60  # Returns 0–23


def is_rush_hour(hour: int = None) -> bool:
    """Returns True if the simulated time is during rush hour."""
    from config import RUSH_HOURS
    if hour is None:
        hour = simulate_hour()
    for start, end in RUSH_HOURS:
        if start <= hour < end:
            return True
    return False
