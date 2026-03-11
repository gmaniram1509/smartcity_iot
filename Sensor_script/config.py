# =============================================================
#  SMART CITY — SENSOR LAYER CONFIGURATION
#  All thresholds, intervals, and zone settings in one place.
#  Change values here — no need to touch individual sensors.
# =============================================================

# ── Fog Node destination ──────────────────────────────────────
FOG_NODE_URL = "http://localhost:5001/data"   # Where sensors POST data
USE_HTTP      = True                           # True = HTTP, False = MQTT

# ── MQTT settings (only used if USE_HTTP = False) ─────────────
MQTT_BROKER   = "localhost"
MQTT_PORT     = 1883
MQTT_TOPIC    = "smartcity/sensors"

# ── City Zones ────────────────────────────────────────────────
ZONES = {
    "Zone_A": "Residential",
    "Zone_B": "Industrial",
    "Zone_C": "Commercial",
    "Zone_D": "Transport Hub",
}

# ── Send Intervals (seconds) ──────────────────────────────────
#    How often each sensor sends a reading to the fog node
INTERVALS = {
    "temperature":  5,    # Temp changes slowly → every 5s is fine
    "humidity":     5,
    "air_quality":  3,    # Air quality needs faster updates
    "noise":        2,    # Noise changes quickly
    "traffic":      1,    # Traffic needs near real-time → every 1s
}

# ── Realistic Value Ranges ────────────────────────────────────
RANGES = {
    "temperature": {
        "min": 10.0,      # Coldest possible (°C)
        "max": 40.0,      # Hottest possible (°C)
        "base": 22.0,     # Starting value
        "drift": 0.4,     # Max change per reading (°C)
        "night_base": 14.0,
        "day_base": 26.0,
    },
    "humidity": {
        "min": 20.0,      # Very dry (%)
        "max": 95.0,      # Near rain (%)
        "base": 55.0,
        "drift": 0.8,
    },
    "air_quality": {
        "pm25_min": 5.0,
        "pm25_max": 150.0,  # Dangerous spike max
        "pm25_base": 30.0,
        "pm25_drift": 1.5,
        "co2_min": 380.0,
        "co2_max": 1200.0,
        "co2_base": 420.0,
        "co2_drift": 5.0,
    },
    "noise": {
        "min": 28.0,      # Very quiet night (dB)
        "max": 105.0,     # Jackhammer / loud event (dB)
        "base": 52.0,
        "drift": 1.5,
    },
    "traffic": {
        "count_min": 0,
        "count_max": 150,   # Max vehicles per minute
        "count_base": 20,
        "count_drift": 3,
        "speed_min": 5,     # Near standstill km/h
        "speed_max": 120,
        "speed_base": 60,
        "speed_drift": 2,
    },
}

# ── Alert Thresholds (used by fog layer, defined here too) ────
THRESHOLDS = {
    "pm25_warning":    55.0,   # μg/m³
    "pm25_critical":   80.0,   # μg/m³  ← Fog triggers alert above this
    "co2_warning":     700.0,  # ppm
    "co2_critical":    1000.0, # ppm
    "noise_warning":   75.0,   # dB
    "noise_critical":  85.0,   # dB
    "temp_warning":    35.0,   # °C
    "traffic_warning": 80,     # vehicles/min
    "traffic_critical":100,    # vehicles/min ← Fog triggers congestion alert
    "speed_low":       20,     # km/h ← if traffic high AND speed low = congestion
}

# ── Rush Hour Windows ─────────────────────────────────────────
#    During these simulated hours, traffic + pollution are higher
#    Hour is simulated: 1 real second = 1 simulated minute
RUSH_HOURS = [
    (8, 9),    # Morning rush:   8:00 – 9:00
    (12, 13),  # Lunch rush:    12:00 – 13:00
    (17, 19),  # Evening rush:  17:00 – 19:00
]

# ── Burst Mode Settings ───────────────────────────────────────
BURST = {
    "duration_seconds": 30,   # How long a burst lasts
    "pm25_spike":       95.0, # PM2.5 during pollution burst
    "co2_spike":        950.0,
    "noise_spike":      92.0,
    "traffic_spike":    130,  # Vehicles/min during traffic burst
    "speed_drop":       8,    # km/h during congestion burst
    "temp_spike":       38.5,
}

# ── Sensor IDs & Locations ────────────────────────────────────
SENSORS = {
    "temperature": [
        {"id": "temp_01", "zone": "Zone_A"},
        {"id": "temp_02", "zone": "Zone_C"},
    ],
    "humidity": [
        {"id": "hum_01", "zone": "Zone_A"},
    ],
    "air_quality": [
        {"id": "air_01", "zone": "Zone_A"},
        {"id": "air_02", "zone": "Zone_B"},  # Industrial zone — higher pollution
        {"id": "air_03", "zone": "Zone_D"},
    ],
    "noise": [
        {"id": "noise_01", "zone": "Zone_C"},
        {"id": "noise_02", "zone": "Zone_D"},
    ],
    "traffic": [
        {"id": "traffic_01", "zone": "Zone_D"},
        {"id": "traffic_02", "zone": "Zone_C"},
    ],
}
