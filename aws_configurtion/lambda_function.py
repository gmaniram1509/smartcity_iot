# =============================================================
#  SMART CITY — LAMBDA: INGESTOR
#
#  WHAT THIS DOES:
#  ─────────────────────────────────────────────────────────────
#  This Lambda function is triggered automatically by SQS.
#  Every time the fog node sends data to the API Gateway,
#  it lands in SQS, and this function wakes up to process it.
#
#  It handles TWO types of incoming messages:
#
#  TYPE 1 — "aggregation"
#    Fog node's 30-second compressed batch of sensor readings.
#    Written to: smartcity-readings DynamoDB table.
#
#  TYPE 2 — "alert"
#    Immediate event (PM2.5 spike, congestion, etc.)
#    Written to: smartcity-alerts DynamoDB table.
#
#  SQS can send multiple messages in one batch (up to 10).
#  This function loops through each one.
#
#  Lambda scales automatically — if 100 fog nodes are sending
#  simultaneously, AWS spins up 100 instances of this function.
# =============================================================

import json
import boto3
import logging
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# DynamoDB client — connects automatically using Lambda's role
dynamodb   = boto3.resource("dynamodb", region_name="us-east-1")
table_readings = dynamodb.Table("smartcity-readings")
table_alerts   = dynamodb.Table("smartcity-alerts")


def lambda_handler(event, context):
    """
    Entry point. AWS calls this automatically when SQS has messages.

    event["Records"] is a list of SQS messages.
    Each message body is a JSON string we need to parse.
    """
    processed = 0
    failed    = 0

    for record in event.get("Records", []):
        try:
            # ── Parse the SQS message body ─────────────────────
            body     = json.loads(record["body"])
            msg_type = body.get("type", "unknown")
            payload  = body.get("payload", {})
            source   = body.get("source", "unknown")

            logger.info(
                f"Processing {msg_type} from {source} | "
                f"sensor: {payload.get('sensor_id', '?')}"
            )

            # ── Route to correct handler ───────────────────────
            if msg_type == "aggregation":
                _write_aggregation(payload, body.get("sent_at", ""))
            elif msg_type == "alert":
                _write_alert(payload, body.get("sent_at", ""))
            else:
                logger.warning(f"Unknown message type: {msg_type}")

            processed += 1

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in SQS message: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"Failed to process record: {e}")
            failed += 1

    logger.info(f"Batch complete: {processed} processed, {failed} failed")
    return {
        "statusCode": 200,
        "processed":  processed,
        "failed":     failed,
    }


def _write_aggregation(payload: dict, sent_at: str):
    """
    Writes an aggregated sensor reading to smartcity-readings table.

    DynamoDB doesn't support Python floats directly — we convert
    everything to Decimal first. This is a DynamoDB quirk.

    Table schema:
      sensor_id  (partition key) — e.g. "air_02"
      timestamp  (sort key)      — e.g. "2026-03-09T14:32:01Z"
    """
    sensor_id  = payload.get("sensor_id", "unknown")
    timestamp  = payload.get("window_end_ts") or sent_at or _now()
    stats      = payload.get("stats", {})

    # Flatten stats for easier querying from dashboard
    # Instead of nested {"pm25": {"mean": 45.2}}, store as flat fields
    flat_stats = {}
    for field, stat_dict in stats.items():
        if isinstance(stat_dict, dict):
            for stat_name, stat_val in stat_dict.items():
                if isinstance(stat_val, (int, float)):
                    flat_stats[f"{field}_{stat_name}"] = _to_decimal(stat_val)
        elif isinstance(stat_dict, (int, float)):
            flat_stats[field] = _to_decimal(stat_dict)

    item = {
        "sensor_id":    sensor_id,
        "timestamp":    timestamp,
        "sensor_type":  payload.get("sensor_type", "unknown"),
        "window_size":  payload.get("window_size", 0),
        "fog_batch_num": payload.get("fog_aggregation_count", 0),
        "ingested_at":  _now(),
        **flat_stats,
    }

    table_readings.put_item(Item=item)
    logger.info(
        f"✓ Written to smartcity-readings: {sensor_id} @ {timestamp}"
    )


def _write_alert(payload: dict, sent_at: str):
    """
    Writes an alert event to smartcity-alerts table.

    Table schema:
      event_type  (partition key) — e.g. "POLLUTION_SPIKE"
      timestamp   (sort key)      — ISO timestamp
    """
    event_type = payload.get("event_type", "UNKNOWN_EVENT")
    timestamp  = payload.get("timestamp") or sent_at or _now()

    item = {
        "event_type":   event_type,
        "timestamp":    timestamp,
        "severity":     payload.get("severity", "UNKNOWN"),
        "sensor_id":    payload.get("sensor_id", "unknown"),
        "sensor_type":  payload.get("sensor_type", "unknown"),
        "location":     payload.get("location", "unknown"),
        "field":        payload.get("field", ""),
        "value":        _to_decimal(payload.get("value", 0)),
        "threshold":    _to_decimal(payload.get("threshold", 0)),
        "message":      payload.get("message", ""),
        "ingested_at":  _now(),
    }

    table_alerts.put_item(Item=item)
    logger.info(
        f"🚨 Alert written: {event_type} | {payload.get('sensor_id')} | "
        f"value={payload.get('value')}"
    )


def _to_decimal(val):
    """Convert float to Decimal for DynamoDB compatibility."""
    if isinstance(val, float):
        return Decimal(str(round(val, 4)))
    return val


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
