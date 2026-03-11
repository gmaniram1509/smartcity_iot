import json
import boto3
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb       = boto3.resource("dynamodb", region_name="us-east-1")
table_readings = dynamodb.Table("smartcity-readings")
table_alerts   = dynamodb.Table("smartcity-alerts")

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Content-Type":                 "application/json",
}

def lambda_handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}
    path   = event.get("path", "/readings")
    params = event.get("queryStringParameters") or {}
    try:
        if "/readings" in path:
            body = get_readings(params)
        elif "/events" in path:
            body = get_events(params)
        elif "/summary" in path:
            body = get_summary(params)
        else:
            body = {"error": f"Unknown path: {path}"}
        return {"statusCode": 200, "headers": CORS, "body": json.dumps(body, default=serial)}
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return {"statusCode": 500, "headers": CORS, "body": json.dumps({"error": str(e)})}

def get_readings(params):
    limit   = int(params.get("limit", 20))
    minutes = int(params.get("minutes", 30))
    sensor  = params.get("sensor_id")
    since   = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sensor_ids = [sensor] if sensor else [
        "temp_01","temp_02","hum_01",
        "air_01","air_02","air_03",
        "noise_01","noise_02",
        "traffic_01","traffic_02",
    ]
    from boto3.dynamodb.conditions import Key
    results = {}
    for sid in sensor_ids:
        try:
            resp  = table_readings.query(
                KeyConditionExpression=Key("sensor_id").eq(sid) & Key("timestamp").gte(since),
                ScanIndexForward=False, Limit=limit)
            items = resp.get("Items", [])
            if items:
                results[sid] = items
        except Exception as e:
            logger.warning(f"Query failed {sid}: {e}")
    return {"readings": results, "since": since, "sensor_count": len(results), "queried_at": now()}

def get_events(params):
    limit = int(params.get("limit", 20))
    try:
        resp  = table_alerts.scan(Limit=100)
        items = sorted(resp.get("Items", []), key=lambda x: x.get("timestamp",""), reverse=True)
        return {"events": items[:limit], "count": len(items[:limit]), "queried_at": now()}
    except Exception as e:
        logger.error(f"Events error: {e}")
        return {"events": [], "count": 0, "queried_at": now()}

def get_summary(params):
    return {"zones": {"Zone_A":{"status":"GOOD"},"Zone_B":{"status":"GOOD"},"Zone_C":{"status":"GOOD"},"Zone_D":{"status":"GOOD"}}, "queried_at": now()}

def serial(obj):
    if isinstance(obj, Decimal): return float(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
