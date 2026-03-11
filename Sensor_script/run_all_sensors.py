#!/usr/bin/env python3
# =============================================================
#  SMART CITY — RUN ALL SENSORS
#
#  This is the file you actually RUN to start Phase 1.
#  It launches ALL sensors simultaneously in background threads.
#
#  Usage:
#    python run_all_sensors.py
#
#  Interactive Commands (type in terminal while running):
#    burst air    → Trigger pollution spike on all air sensors
#    burst traffic → Trigger congestion on all traffic sensors
#    burst noise  → Trigger noise event
#    burst all    → Trigger ALL sensors simultaneously
#    status       → Print current reading count per sensor
#    stop         → Gracefully shut everything down
# =============================================================

import sys
import time
import threading
import os

# Add sensors folder to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

from temperature  import TemperatureSensor
from humidity     import HumiditySensor
from air_quality  import AirQualitySensor
from noise        import NoiseSensor
from traffic      import TrafficSensor
from config       import SENSORS, FOG_NODE_URL, USE_HTTP

# ── ANSI colours for terminal output ─────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

BANNER = f"""
{CYAN}{BOLD}
╔══════════════════════════════════════════════════════╗
║        SMART CITY IoT SENSOR LAYER — PHASE 1        ║
║              Environmental & Traffic Monitoring      ║
╚══════════════════════════════════════════════════════╝
{RESET}"""


def print_startup_info(all_sensors):
    print(BANNER)
    print(f"{BOLD}Fog Node Target:{RESET} {FOG_NODE_URL}")
    print(f"{BOLD}Transport:{RESET}      {'HTTP POST' if USE_HTTP else 'MQTT'}")
    print()
    print(f"{BOLD}Sensors Starting:{RESET}")
    print(f"  {'ID':<14} {'Type':<14} {'Zone':<12} {'Interval'}")
    print(f"  {'─'*14} {'─'*14} {'─'*12} {'─'*8}")
    for s in all_sensors:
        print(f"  {s.sensor_id:<14} {s.sensor_type:<14} {s.zone:<12} {s.interval}s")
    print()


def build_all_sensors():
    """
    Instantiates every sensor defined in config.py.
    Returns a flat list of all sensor objects.
    """
    all_sensors = []

    # ── Temperature sensors ───────────────────────────────────
    for cfg in SENSORS["temperature"]:
        all_sensors.append(
            TemperatureSensor(cfg["id"], cfg["zone"])
        )

    # ── Humidity sensors ──────────────────────────────────────
    for cfg in SENSORS["humidity"]:
        all_sensors.append(
            HumiditySensor(cfg["id"], cfg["zone"])
        )

    # ── Air quality sensors ───────────────────────────────────
    for cfg in SENSORS["air_quality"]:
        all_sensors.append(
            AirQualitySensor(cfg["id"], cfg["zone"])
        )

    # ── Noise sensors ─────────────────────────────────────────
    for cfg in SENSORS["noise"]:
        all_sensors.append(
            NoiseSensor(cfg["id"], cfg["zone"])
        )

    # ── Traffic sensors ───────────────────────────────────────
    for cfg in SENSORS["traffic"]:
        all_sensors.append(
            TrafficSensor(cfg["id"], cfg["zone"])
        )

    return all_sensors


def trigger_burst_by_type(all_sensors, sensor_type: str, duration: int = 30):
    """
    Triggers burst mode on all sensors of a given type.
    e.g. trigger_burst_by_type(sensors, "air_quality")
    """
    matched = [s for s in all_sensors if s.sensor_type == sensor_type]
    if not matched:
        print(f"{RED}No sensors found with type: {sensor_type}{RESET}")
        return
    for s in matched:
        s.trigger_burst(duration)
    print(f"{RED}🚨 BURST triggered on {len(matched)} {sensor_type} sensor(s){RESET}")


def print_status(all_sensors):
    """Prints a status table showing readings sent per sensor."""
    print(f"\n{BOLD}{'─'*50}")
    print(f"  {'SENSOR ID':<14} {'TYPE':<14} {'READINGS SENT':<14} {'BURST'}")
    print(f"{'─'*50}{RESET}")
    for s in all_sensors:
        burst_flag = f"{RED}ACTIVE{RESET}" if s.burst_active else f"{GREEN}OFF{RESET}"
        print(f"  {s.sensor_id:<14} {s.sensor_type:<14} {s.reading_count:<14} {burst_flag}")
    print()


def interactive_shell(all_sensors):
    """
    Runs a simple command loop in the terminal so you can
    trigger burst events without restarting the program.
    """
    print(f"{CYAN}Interactive mode ready. Commands:{RESET}")
    print("  burst air      → Pollution spike")
    print("  burst traffic  → Traffic congestion")
    print("  burst noise    → Noise event")
    print("  burst temp     → Heatwave")
    print("  burst humidity → Downpour")
    print("  burst all      → All sensors burst simultaneously")
    print("  status         → Show reading counts")
    print("  stop           → Shut down all sensors")
    print()

    type_map = {
        "air":      "air_quality",
        "traffic":  "traffic",
        "noise":    "noise",
        "temp":     "temperature",
        "humidity": "humidity",
    }

    while True:
        try:
            cmd = input(f"{BOLD}>{RESET} ").strip().lower()

            if cmd.startswith("burst "):
                arg = cmd.split(" ", 1)[1]
                if arg == "all":
                    for t in type_map.values():
                        trigger_burst_by_type(all_sensors, t, duration=30)
                elif arg in type_map:
                    trigger_burst_by_type(all_sensors, type_map[arg], duration=30)
                else:
                    print(f"{YELLOW}Unknown type: {arg}{RESET}")

            elif cmd == "status":
                print_status(all_sensors)

            elif cmd in ("stop", "exit", "quit"):
                print(f"\n{YELLOW}Stopping all sensors...{RESET}")
                for s in all_sensors:
                    s.stop()
                print(f"{GREEN}All sensors stopped.{RESET}")
                sys.exit(0)

            elif cmd == "":
                continue

            else:
                print(f"{YELLOW}Unknown command: '{cmd}'{RESET}")

        except (EOFError, KeyboardInterrupt):
            print(f"\n{YELLOW}Interrupted. Stopping all sensors...{RESET}")
            for s in all_sensors:
                s.stop()
            sys.exit(0)


# ── ENTRY POINT ───────────────────────────────────────────────
if __name__ == "__main__":

    # 1. Build all sensor instances
    all_sensors = build_all_sensors()

    # 2. Print startup information
    print_startup_info(all_sensors)

    # 3. Start every sensor in its own background thread
    threads = []
    for sensor in all_sensors:
        t = sensor.run_in_thread()
        threads.append(t)

    total = len(all_sensors)
    print(f"{GREEN}✓ {total} sensors running in background threads{RESET}\n")

    # 4. Brief pause then show first status
    time.sleep(3)
    print_status(all_sensors)

    # 5. Enter interactive command loop
    interactive_shell(all_sensors)
