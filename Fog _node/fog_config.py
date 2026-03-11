# =============================================================
#  SMART CITY — FOG LAYER CONFIGURATION
#  All fog node settings in one file.
#  Change values here — no need to touch logic files.
# =============================================================

# ── Server settings ───────────────────────────────────────────
FOG_HOST = "0.0.0.0"    # Listen on all interfaces
FOG_PORT = 5001          # Changed from 5000 to avoid Mac AirPlay conflict

# ── Cloud endpoint (Phase 3 will run here) ────────────────────
CLOUD_URL = "https://g82xknl062.execute-api.us-east-1.amazonaws.com/prod/ingest"   # Where fog sends aggregated data
SEND_TO_CLOUD = True                          # Set False to skip cloud for now

# ── Aggregation settings ──────────────────────────────────────
# How many raw readings to collect before computing an average
# and sending ONE aggregated payload to the cloud.
# e.g. AGGREGATE_WINDOW = 5 means: collect 5 readings → send 1
# This is your bandwidth reduction ratio (5:1 in this case)
AGGREGATE_WINDOW = {
    "temperature":  5,   # 5 readings → 1 aggregate  (every 25s)
    "humidity":     5,   # 5 readings → 1 aggregate  (every 25s)
    "air_quality":  5,   # 5 readings → 1 aggregate  (every 15s)
    "noise":        5,   # 5 readings → 1 aggregate  (every 10s)
    "traffic":     10,   # 10 readings → 1 aggregate (every 10s)
}

# ── Outlier detection settings ────────────────────────────────
# How many standard deviations away from mean = outlier
# 2.5 means: if value is 2.5x further than normal spread → discard
OUTLIER_STD_THRESHOLD = 2.5

# Minimum readings needed before outlier detection kicks in
# (can't compute std deviation with only 1 reading)
OUTLIER_MIN_SAMPLES = 5

# ── Alert thresholds (what triggers immediate fog alerts) ─────
ALERT_RULES = {
    "air_quality": {
        "pm25": {
            "warning":  55.0,    # μg/m³ — send warning
            "critical": 80.0,    # μg/m³ — send immediate alert to cloud
        },
        "co2": {
            "warning":  700.0,   # ppm
            "critical": 1000.0,  # ppm
        },
    },
    "noise": {
        "value": {
            "warning":  75.0,    # dB
            "critical": 85.0,    # dB
        },
    },
    "temperature": {
        "value": {
            "warning":  35.0,    # °C
            "critical": 39.0,    # °C
        },
    },
    "traffic": {
        "congestion_index": {
            "warning":  0.70,    # Congestion score 0–1
            "critical": 0.85,    # Near gridlock
        },
        "vehicle_count": {
            "warning":  80,      # vehicles/min
            "critical": 100,     # vehicles/min
        },
    },
    "humidity": {
        "value": {
            "warning":  88.0,    # % — very high humidity
            "critical": 95.0,    # % — near saturation
        },
    },
}

# ── Corrupt reading detection rules ──────────────────────────
# Any reading that fails these checks is flagged as corrupt
# and discarded immediately (before outlier check even runs)
CORRUPTION_RULES = {
    "temperature": {"min": -20,  "max": 60},    # °C  — physically impossible outside this
    "humidity":    {"min": 0,    "max": 100},   # %   — by definition 0–100
    "pm25":        {"min": 0,    "max": 500},   # μg/m³
    "co2":         {"min": 300,  "max": 5000},  # ppm — 300 is clean outdoor minimum
    "noise":       {"min": 0,    "max": 140},   # dB  — 140 is threshold of pain
    "vehicle_count": {"min": 0,  "max": 300},
    "avg_speed_kmh": {"min": 0,  "max": 200},
    "congestion_index": {"min": 0, "max": 1},
}

# ── Stats tracking ────────────────────────────────────────────
# How many readings to keep in memory for the stats endpoint
HISTORY_SIZE = 200
