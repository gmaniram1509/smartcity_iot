#!/usr/bin/env python3
# =============================================================
#  SMART CITY — FOG NODE (MAIN SERVER)
#
#  This is the file you RUN to start the fog layer.
#  Run this BEFORE run_all_sensors.py.
#
#  Usage:
#    python fog_node.py
#
#  This starts an HTTP server that:
#    1. Receives sensor data on POST /data
#    2. Filters corrupt and outlier readings
#    3. Detects emergency events (fires alerts immediately)
#    4. Aggregates clean readings into statistical batches
#    5. Forwards aggregations + alerts to the cloud
#    6. Exposes GET /stats for the dashboard
#    7. Exposes GET /events for recent alerts
#    8. Exposes GET /health for system status
#
#  PROCESSING PIPELINE (what happens to every reading):
#
#  Sensor POST /data
#       │
#       ▼
#  [1] Validate JSON structure
#       │
#       ▼
#  [2] Filter Engine → Corrupt? → DISCARD (log it)
#       │                              │
#       │ Clean reading               DONE
#       ▼
#  [3] Event Detector → Alert? → CloudForwarder.send_alert() → Cloud IMMEDIATELY
#       │
#       ▼
#  [4] Aggregator → Buffer not full? → Wait for more readings
#       │                                       │
#       │ Buffer full                         DONE (for now)
#       ▼
#  [5] CloudForwarder.send_aggregation() → Cloud (batch)
# =============================================================

import json
import logging
import sys
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify

# ── Import fog layer components ───────────────────────────────
from fog_config    import FOG_HOST, FOG_PORT
from filter_engine import FilterEngine
from aggregator    import Aggregator
from event_detector import EventDetector
from cloud_forwarder import CloudForwarder

# ── Logging setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-18s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("fog_node.log", mode="a"),
    ]
)
logger = logging.getLogger("FogNode")

# ── Flask app ─────────────────────────────────────────────────
app = Flask(__name__)
log = logging.getLogger("werkzeug")
log.setLevel(logging.WARNING)   # Suppress Flask's verbose request logs

# ── Fog layer components (instantiated once, shared globally) ─
filter_engine    = FilterEngine()
aggregator       = Aggregator()
event_detector   = EventDetector()
cloud_forwarder  = CloudForwarder()

# ── Request counter ───────────────────────────────────────────
total_requests   = 0
start_time       = datetime.now(timezone.utc)

# ── ANSI colours ──────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

BANNER = f"""
{CYAN}{BOLD}
╔══════════════════════════════════════════════════════╗
║         SMART CITY — FOG NODE  (Phase 2)            ║
║         Edge Intelligence Processing Layer          ║
╚══════════════════════════════════════════════════════╝
{RESET}"""


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 1: POST /data  ←  Sensors send here
# ══════════════════════════════════════════════════════════════
@app.route("/data", methods=["POST"])
def receive_sensor_data():
    """
    Main ingestion endpoint. Every sensor POSTs here.

    Expected payload format:
    {
        "sensor_id":  "air_02",
        "type":       "air_quality",
        "location":   "Zone_B",
        "data":       { "pm25": 67.3, "co2": 520, ... },
        "burst_mode": false,
        "timestamp":  "2026-03-09T14:32:01Z",
        "seq":        42
    }
    """
    global total_requests
    total_requests += 1

    # ── Parse request ─────────────────────────────────────────
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    try:
        payload = request.get_json()
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # ── Extract fields ────────────────────────────────────────
    sensor_id   = payload.get("sensor_id")
    sensor_type = payload.get("type")
    location    = payload.get("location", "Unknown")
    data        = payload.get("data", {})
    is_burst    = payload.get("burst_mode", False)
    timestamp   = payload.get("timestamp", "")
    seq         = payload.get("seq", 0)

    # Basic validation
    if not sensor_id or not sensor_type or not data:
        return jsonify({
            "error": "Missing required fields: sensor_id, type, data"
        }), 400

    # Add timestamp to data for aggregation window tracking
    data["timestamp"] = timestamp

    # ──────────────────────────────────────────────────────────
    # STEP 1: FILTER ENGINE
    # Check for corrupt/impossible values + statistical outliers
    # ──────────────────────────────────────────────────────────
    filter_result = filter_engine.check(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        reading=data,
        is_burst=is_burst
    )

    if not filter_result.passed:
        logger.warning(
            f"{YELLOW}FILTERED{RESET} | {sensor_id} | "
            f"{filter_result.reason} | "
            f"{filter_result.field}={filter_result.value}"
        )
        return jsonify({
            "status":  "filtered",
            "reason":  filter_result.reason,
            "field":   filter_result.field,
            "message": "Reading discarded by fog filter engine",
        }), 200   # 200 not 400 — sensor did nothing wrong, this is expected

    # ──────────────────────────────────────────────────────────
    # STEP 2: EVENT DETECTOR
    # Check thresholds — fire immediate alerts if breached
    # ──────────────────────────────────────────────────────────
    event = event_detector.check(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        location=location,
        reading=data
    )

    if event:
        severity_color = RED if event.severity == "CRITICAL" else YELLOW
        logger.warning(
            f"{severity_color}🚨 EVENT{RESET} | "
            f"{event.severity} | {event.event_type} | "
            f"{sensor_id} | {event.field}={event.value} "
            f"(threshold={event.threshold})"
        )
        # Send alert immediately — bypasses aggregation
        cloud_forwarder.send_alert(event.to_dict())

    # ──────────────────────────────────────────────────────────
    # STEP 3: AGGREGATOR
    # Add clean reading to buffer. If window complete → send batch
    # ──────────────────────────────────────────────────────────
    aggregated = aggregator.process(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        reading=data
    )

    if aggregated:
        buf_info = next(
            (b for b in aggregator.get_buffer_status()
             if b["sensor_id"] == sensor_id), {}
        )
        logger.info(
            f"{GREEN}AGGREGATED{RESET} | {sensor_id} | "
            f"window={aggregated['window_size']} readings | "
            f"→ Cloud | "
            f"bandwidth ratio: {buf_info.get('bandwidth_ratio', '?')}"
        )
        cloud_forwarder.send_aggregation(aggregated)
        response_status = "aggregated_and_forwarded"
    else:
        # Just buffering — show progress
        buf = next(
            (b for b in aggregator.get_buffer_status()
             if b["sensor_id"] == sensor_id), {}
        )
        fill = buf.get("buffer_fill", "?")
        logger.debug(
            f"BUFFERING | {sensor_id} | seq={seq} | buffer={fill}"
        )
        response_status = "buffered"

    # ──────────────────────────────────────────────────────────
    # Return acknowledgement to sensor
    # ──────────────────────────────────────────────────────────
    return jsonify({
        "status":     response_status,
        "sensor_id":  sensor_id,
        "filtered":   False,
        "event_fired": event is not None,
        "event_type":  event.event_type if event else None,
    }), 200


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 2: GET /stats  ←  Dashboard polls this
# ══════════════════════════════════════════════════════════════
@app.route("/stats", methods=["GET"])
def get_stats():
    """
    Returns a comprehensive statistics snapshot of the fog node.
    The dashboard polls this every few seconds to display live metrics.
    """
    uptime_secs = int(
        (datetime.now(timezone.utc) - start_time).total_seconds()
    )

    filter_stats    = filter_engine.get_stats()
    event_stats     = event_detector.get_stats()
    cloud_stats     = cloud_forwarder.get_stats()
    buffer_statuses = aggregator.get_buffer_status()

    # ── Bandwidth analysis ─────────────────────────────────────
    raw_total  = aggregator.total_raw_received
    sent_total = aggregator.total_aggregated_sent
    savings    = aggregator.get_bandwidth_savings_pct()

    return jsonify({
        "fog_node": {
            "status":          "running",
            "uptime_seconds":  uptime_secs,
            "uptime_human":    _format_uptime(uptime_secs),
            "total_requests":  total_requests,
            "started_at":      start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "filter_engine": {
            "total_checked":     filter_stats["total_checked"],
            "total_passed":      filter_stats["total_passed"],
            "total_rejected":    filter_stats["total_rejected"],
            "corrupt_count":     filter_stats["corrupt_rejected"],
            "outlier_count":     filter_stats["outlier_rejected"],
            "rejection_rate":    f"{filter_stats['rejection_rate_pct']}%",
            "recent_rejections": filter_stats["recent_rejections"],
        },
        "aggregation": {
            "raw_readings_received":  raw_total,
            "aggregated_batches_sent": sent_total,
            "bandwidth_savings_pct":  f"{savings}%",
            "reduction_ratio":        (
                f"{round(raw_total / sent_total, 1)}:1"
                if sent_total > 0 else "N/A"
            ),
            "buffer_status":          buffer_statuses,
            "recent_aggregations":    aggregator.get_recent_aggregations(5),
        },
        "event_detection": {
            "total_events":    event_stats["total_events_fired"],
            "critical_events": event_stats["total_critical"],
            "warning_events":  event_stats["total_warnings"],
            "suppressed":      event_stats["total_suppressed"],
            "recent_events":   event_stats["recent_events"],
        },
        "cloud_forwarding": {
            "cloud_url":         cloud_stats["cloud_url"],
            "cloud_reachable":   cloud_stats["cloud_reachable"],
            "total_sent":        cloud_stats["total_sent"],
            "total_failed":      cloud_stats["total_failed"],
            "alerts_sent":       cloud_stats["total_alerts_sent"],
            "retry_queue_size":  cloud_stats["retry_queue_size"],
            "last_success":      cloud_stats["last_success"],
        },
    })


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 3: GET /events  ←  Recent alerts feed
# ══════════════════════════════════════════════════════════════
@app.route("/events", methods=["GET"])
def get_events():
    """Returns the most recent events/alerts fired by the fog node."""
    n = request.args.get("n", 20, type=int)
    return jsonify({
        "events": event_detector.get_recent_events(n),
        "total":  event_detector.total_events_fired,
    })


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 4: GET /health  ←  Quick health check
# ══════════════════════════════════════════════════════════════
@app.route("/health", methods=["GET"])
def health():
    """Simple health check. Returns 200 if fog node is alive."""
    return jsonify({
        "status":    "healthy",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }), 200


# ══════════════════════════════════════════════════════════════
#  ENDPOINT 5: GET /  ←  Human-readable status page
# ══════════════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
def index():
    """Returns a simple HTML status page you can open in a browser."""
    stats = get_stats().get_json()
    fog   = stats["fog_node"]
    agg   = stats["aggregation"]
    fil   = stats["filter_engine"]
    evt   = stats["event_detection"]

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Fog Node Status</title>
      <meta http-equiv="refresh" content="3">
      <style>
        body {{ font-family: monospace; background: #0a0f1a; color: #c8dde8;
               padding: 30px; }}
        h1   {{ color: #00d4ff; letter-spacing: 4px; }}
        h2   {{ color: #ff6b2b; font-size: 13px; letter-spacing: 3px;
               text-transform: uppercase; }}
        .card {{ background: #0f1e2e; border: 1px solid #1a3040;
                padding: 16px; margin: 10px 0; border-radius: 4px; }}
        .good {{ color: #00ff9d; }}
        .warn {{ color: #ffd600; }}
        .bad  {{ color: #ff3b5c; }}
        table {{ border-collapse: collapse; width: 100%; }}
        td, th {{ padding: 6px 12px; text-align: left;
                  border-bottom: 1px solid #1a3040; font-size: 12px; }}
        th {{ color: #4a6a7a; }}
      </style>
    </head>
    <body>
      <h1>🌫️ FOG NODE — LIVE STATUS</h1>
      <p style="color:#4a6a7a">Auto-refreshes every 3 seconds</p>

      <div class="card">
        <h2>System</h2>
        <table>
          <tr><th>Status</th><td class="good">● RUNNING</td></tr>
          <tr><th>Uptime</th><td>{fog['uptime_human']}</td></tr>
          <tr><th>Total Requests</th><td>{fog['total_requests']}</td></tr>
        </table>
      </div>

      <div class="card">
        <h2>Aggregation (Bandwidth Saving)</h2>
        <table>
          <tr><th>Raw Readings Received</th><td>{agg['raw_readings_received']}</td></tr>
          <tr><th>Aggregated Batches Sent</th><td>{agg['aggregated_batches_sent']}</td></tr>
          <tr><th>Bandwidth Saved</th>
              <td class="good">{agg['bandwidth_savings_pct']}</td></tr>
          <tr><th>Reduction Ratio</th>
              <td class="good">{agg['reduction_ratio']}</td></tr>
        </table>
      </div>

      <div class="card">
        <h2>Filter Engine</h2>
        <table>
          <tr><th>Checked</th><td>{fil['total_checked']}</td></tr>
          <tr><th>Passed</th><td class="good">{fil['total_passed']}</td></tr>
          <tr><th>Rejected</th><td class="warn">{fil['total_rejected']}</td></tr>
          <tr><th>Rejection Rate</th><td>{fil['rejection_rate']}</td></tr>
        </table>
      </div>

      <div class="card">
        <h2>Event Detection</h2>
        <table>
          <tr><th>Total Events</th><td>{evt['total_events']}</td></tr>
          <tr><th>Critical</th>
              <td class="bad">{evt['critical_events']}</td></tr>
          <tr><th>Warnings</th>
              <td class="warn">{evt['warning_events']}</td></tr>
        </table>
      </div>

      <div class="card">
        <h2>Sensor Buffer Status</h2>
        <table>
          <tr>
            <th>Sensor ID</th><th>Type</th>
            <th>Buffer</th><th>Received</th><th>Aggregated</th><th>Ratio</th>
          </tr>
          {''.join(
            f"<tr><td>{b['sensor_id']}</td><td>{b['sensor_type']}</td>"
            f"<td>{b['buffer_fill']}</td><td>{b['total_received']}</td>"
            f"<td>{b['total_aggregated']}</td>"
            f"<td class='good'>{b['bandwidth_ratio']}</td></tr>"
            for b in agg['buffer_status']
          )}
        </table>
      </div>

    </body>
    </html>
    """
    return html


# ──────────────────────────────────────────────────────────────
# HELPER
# ──────────────────────────────────────────────────────────────
def _format_uptime(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}h {m:02d}m {s:02d}s"


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(BANNER)
    print(f"{BOLD}Fog Node Endpoints:{RESET}")
    print(f"  POST http://localhost:{FOG_PORT}/data    ← Sensors send here")
    print(f"  GET  http://localhost:{FOG_PORT}/stats   ← Dashboard JSON")
    print(f"  GET  http://localhost:{FOG_PORT}/events  ← Recent alerts")
    print(f"  GET  http://localhost:{FOG_PORT}/health  ← Health check")
    print(f"  GET  http://localhost:{FOG_PORT}/        ← Status page (browser)")
    print()
    print(f"{BOLD}Next step:{RESET} Update sensors/config.py:")
    print(f"  FOG_NODE_URL = \"http://localhost:{FOG_PORT}/data\"")
    print()

    app.run(
        host=FOG_HOST,
        port=FOG_PORT,
        debug=False,   # Keep False — debug mode causes double-init of threads
        threaded=True, # Handle multiple sensors sending simultaneously
    )
