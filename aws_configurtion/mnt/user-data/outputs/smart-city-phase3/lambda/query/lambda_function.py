# =============================================================
#  SMART CITY — LAMBDA: QUERY
#
#  WHAT THIS DOES:
#  ─────────────────────────────────────────────────────────────
#  This Lambda is triggered by API Gateway GET requests.
#  The React dashboard calls it every 5 seconds to fetch
#  the latest sensor data and alerts for display.
#
#  Handles 3 routes (API Gateway passes route via querystring):
#
#  GET /readings  → Last N readings per sensor from DynamoDB
#  GET /events    → Last N alerts from DynamoDB
#  GET /summary   → Aggregated current state of all zones
# =============================================================

import json
import boto3
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb       = boto3.resource("dynamodb", region_name="us-east-1")
table_readings = dynamodb.Table("smartcity-readings")
table_alerts   = dynamodb.Table("smartcity-alerts")

# CORS headers — needed so React dashboard (different port) can call this
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Content-Type":                 "application/json",
}


def lambda_handler(event, context):
    """
    Routes GET requests to the correct query handler.
    API Gateway passes the path as event["path"] or
    event["queryStringParameters"]["route"].
    """
    # Handle CORS preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    path   = event.get("path", "/readings")
    params = event.get("queryStringParameters") or {}

    logger.info(f"Query request: path={path} params={params}")

    try:
        if path.endswith("/readings"):
            body = _get_readings(params)
        elif path.endswith("/events"):
            body = _get_events(params)
        elif path.endswith("/summary"):
            body = _get_summary(params)
        else:
            body = {"error": f"Unknown path: {path}"}

        return {
            "statusCode": 200,
            "headers":    CORS_HEADERS,
            "body":       json.dumps(body, default=_decimal_serialiser),
        }

    except Exception as e:
        logger.error(f"Query error: {e}")
        return {
            "statusCode": 500,
            "headers":    CORS_HEADERS,
            "body":       json.dumps({"error": str(e)}),
        }


# ──────────────────────────────────────────────────────────────
def _get_readings(params: dict) -> dict:
    """
    Returns the latest readings for each sensor.
    Dashboard uses this to update the sensor value cards.

    params:
      sensor_id : filter by specific sensor (optional)
      limit     : max readings per sensor (default 20)
      minutes   : only readings from last N minutes (default 30)
    """
    limit   = int(params.get("limit", 20))
    minutes = int(params.get("minutes", 30))
    sensor  = params.get("sensor_id")

    # Time filter — only return recent readings
    since = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Known sensor IDs to query
    sensor_ids = [sensor] if sensor else [
        "temp_01", "temp_02",
        "hum_01",
        "air_01", "air_02", "air_03",
        "noise_01", "noise_02",
        "traffic_01", "traffic_02",
    ]

    results = {}
    for sid in sensor_ids:
        try:
            response = table_readings.query(
                KeyConditionExpression=(
                    Key("sensor_id").eq(sid) &
                    Key("timestamp").gte(since)
                ),
                ScanIndexForward=False,   # Most recent first
                Limit=limit,
            )
            items = response.get("Items", [])
            if items:
                results[sid] = items
        except Exception as e:
            logger.warning(f"Query failed for {sid}: {e}")

    return {
        "readings":   results,
        "since":      since,
        "sensor_count": len(results),
        "queried_at": _now(),
    }


# ──────────────────────────────────────────────────────────────
def _get_events(params: dict) -> dict:
    """
    Returns recent alert events.
    Dashboard uses this to populate the alerts feed.

    params:
      limit    : max events to return (default 20)
      severity : filter by CRITICAL or WARNING (optional)
    """
    limit    = int(params.get("limit", 20))
    severity = params.get("severity")

    # Scan alerts table for recent events
    # In production you'd use a GSI — for this project scan is fine
    scan_kwargs = {
        "Limit": min(limit * 3, 100),  # Overscan to allow for filtering
    }

    if severity:
        scan_kwargs["FilterExpression"] = Attr("severity").eq(severity)

    response = table_alerts.scan(**scan_kwargs)
    items    = response.get("Items", [])

    # Sort by timestamp descending (most recent first)
    items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    items = items[:limit]

    return {
        "events":     items,
        "count":      len(items),
        "queried_at": _now(),
    }


# ──────────────────────────────────────────────────────────────
def _get_summary(params: dict) -> dict:
    """
    Returns a summary of current conditions per zone.
    Dashboard uses this for the zone status map.

    Finds the most recent reading for each sensor,
    then groups by zone and picks the worst condition.
    """
    minutes = int(params.get("minutes", 10))
    since   = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    sensor_ids = [
        "temp_01", "temp_02", "hum_01",
        "air_01", "air_02", "air_03",
        "noise_01", "noise_02",
        "traffic_01", "traffic_02",
    ]

    zone_data = {
        "Zone_A": {"sensors": [], "status": "GOOD"},
        "Zone_B": {"sensors": [], "status": "GOOD"},
        "Zone_C": {"sensors": [], "status": "GOOD"},
        "Zone_D": {"sensors": [], "status": "GOOD"},
    }

    zone_map = {
        "temp_01": "Zone_A", "temp_02": "Zone_C",
        "hum_01":  "Zone_A",
        "air_01":  "Zone_A", "air_02": "Zone_B", "air_03": "Zone_D",
        "noise_01": "Zone_C", "noise_02": "Zone_D",
        "traffic_01": "Zone_D", "traffic_02": "Zone_C",
    }

    for sid in sensor_ids:
        try:
            response = table_readings.query(
                KeyConditionExpression=(
                    Key("sensor_id").eq(sid) &
                    Key("timestamp").gte(since)
                ),
                ScanIndexForward=False,
                Limit=1,
            )
            items = response.get("Items", [])
            if items and sid in zone_map:
                zone = zone_map[sid]
                zone_data[zone]["sensors"].append({
                    "sensor_id":   sid,
                    "sensor_type": items[0].get("sensor_type"),
                    "latest":      items[0],
                })
        except Exception as e:
            logger.warning(f"Summary query failed for {sid}: {e}")

    # Determine zone status from latest alert events
    try:
        recent_alerts = table_alerts.scan(
            FilterExpression=Attr("timestamp").gte(since),
            Limit=50,
        ).get("Items", [])

        for alert in recent_alerts:
            location = alert.get("location", "")
            severity = alert.get("severity", "")
            if location in zone_data:
                if severity == "CRITICAL":
                    zone_data[location]["status"] = "CRITICAL"
                elif severity == "WARNING" and zone_data[location]["status"] != "CRITICAL":
                    zone_data[location]["status"] = "WARNING"
    except Exception as e:
        logger.warning(f"Alert scan failed: {e}")

    return {
        "zones":      zone_data,
        "since":      since,
        "queried_at": _now(),
    }


# ──────────────────────────────────────────────────────────────
def _decimal_serialiser(obj):
    """JSON serialiser that handles DynamoDB Decimal types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
