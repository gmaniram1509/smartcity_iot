#!/usr/bin/env python3
# =============================================================
#  SMART CITY — PHASE 3 DEPLOYMENT SCRIPT
#
#  Run this ONCE to create all AWS resources automatically.
#  Usage:  python deploy.py
#
#  What it creates (in order):
#    1. DynamoDB tables  (smartcity-readings, smartcity-alerts)
#    2. SQS queues       (smartcity-readings-queue, smartcity-alerts-queue)
#    3. Lambda functions (smartcity-ingestor, smartcity-query)
#    4. API Gateway      (POST /ingest, GET /readings, GET /events, GET /summary)
#    5. SQS → Lambda trigger (so Lambda fires when SQS receives messages)
#    6. Updates config.py with your live API Gateway URL
# =============================================================

import boto3
import json
import os
import sys
import time
import zipfile
import io
from config import (
    REGION, ACCOUNT_ID, LAB_ROLE_ARN,
    TABLE_READINGS, TABLE_ALERTS,
    QUEUE_READINGS, QUEUE_ALERTS,
    LAMBDA_INGESTOR, LAMBDA_QUERY,
    API_NAME, API_STAGE,
)

# ── ANSI colours ──────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── AWS clients ───────────────────────────────────────────────
session  = boto3.Session(region_name=REGION)
dynamo   = session.client("dynamodb")
sqs      = session.client("sqs")
lamb     = session.client("lambda")
apigw    = session.client("apigateway")

# ── Track created resources ───────────────────────────────────
created = {}


def log(msg, colour=GREEN):
    print(f"{colour}{msg}{RESET}")


def step(n, msg):
    print(f"\n{CYAN}{BOLD}[Step {n}]{RESET} {msg}")


def success(msg):
    print(f"  {GREEN}✓ {msg}{RESET}")


def info(msg):
    print(f"  {YELLOW}→ {msg}{RESET}")


def error(msg):
    print(f"  {RED}✗ {msg}{RESET}")


# ══════════════════════════════════════════════════════════════
#  STEP 1 — DynamoDB Tables
# ══════════════════════════════════════════════════════════════
def create_dynamodb_tables():
    step(1, "Creating DynamoDB Tables")

    tables = [
        {
            "name": TABLE_READINGS,
            "pk":   "sensor_id",
            "sk":   "timestamp",
        },
        {
            "name": TABLE_ALERTS,
            "pk":   "event_type",
            "sk":   "timestamp",
        },
    ]

    for t in tables:
        try:
            dynamo.create_table(
                TableName=t["name"],
                KeySchema=[
                    {"AttributeName": t["pk"], "KeyType": "HASH"},
                    {"AttributeName": t["sk"], "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": t["pk"], "AttributeType": "S"},
                    {"AttributeName": t["sk"], "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",  # On-demand — free tier friendly
            )
            success(f"Created table: {t['name']}")
            created[t["name"]] = "dynamodb_table"

        except dynamo.exceptions.ResourceInUseException:
            info(f"Table already exists: {t['name']} (skipping)")
            created[t["name"]] = "dynamodb_table"

    # Wait for tables to be active
    info("Waiting for tables to become ACTIVE...")
    for t in tables:
        waiter = dynamo.get_waiter("table_exists")
        waiter.wait(TableName=t["name"])
        success(f"Table ACTIVE: {t['name']}")


# ══════════════════════════════════════════════════════════════
#  STEP 2 — SQS Queues
# ══════════════════════════════════════════════════════════════
def create_sqs_queues():
    step(2, "Creating SQS Queues")

    queues = [
        {"name": QUEUE_READINGS, "purpose": "aggregated sensor data"},
        {"name": QUEUE_ALERTS,   "purpose": "immediate alert events"},
    ]

    for q in queues:
        try:
            response = sqs.create_queue(
                QueueName=q["name"],
                Attributes={
                    "VisibilityTimeout":      "60",
                    "MessageRetentionPeriod": "86400",  # 24 hours
                    "ReceiveMessageWaitTimeSeconds": "20",  # Long polling
                }
            )
            url = response["QueueUrl"]
            created[q["name"]] = url
            success(f"Created queue: {q['name']}")
            info(f"URL: {url}")

        except sqs.exceptions.QueueNameExists:
            response = sqs.get_queue_url(QueueName=q["name"])
            url = response["QueueUrl"]
            created[q["name"]] = url
            info(f"Queue already exists: {q['name']} (skipping)")

    # Get queue ARNs for Lambda trigger setup
    for q in queues:
        url  = created[q["name"]]
        attrs = sqs.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=["QueueArn"]
        )
        created[f"{q['name']}_arn"] = attrs["Attributes"]["QueueArn"]


# ══════════════════════════════════════════════════════════════
#  STEP 3 — Lambda Functions
# ══════════════════════════════════════════════════════════════
def _zip_lambda(folder_path: str) -> bytes:
    """
    Zips the lambda_function.py file into a bytes buffer.
    AWS Lambda requires code to be uploaded as a zip file.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(
            os.path.join(folder_path, "lambda_function.py"),
            "lambda_function.py"
        )
    return buf.getvalue()


def create_lambda_functions():
    step(3, "Deploying Lambda Functions")

    functions = [
        {
            "name":        LAMBDA_INGESTOR,
            "folder":      "lambda/ingestor",
            "description": "Receives from SQS, writes to DynamoDB",
            "timeout":     30,
            "memory":      256,
        },
        {
            "name":        LAMBDA_QUERY,
            "folder":      "lambda/query",
            "description": "Reads DynamoDB for dashboard queries",
            "timeout":     15,
            "memory":      128,
        },
    ]

    for fn in functions:
        zip_bytes = _zip_lambda(fn["folder"])

        try:
            response = lamb.create_function(
                FunctionName=fn["name"],
                Runtime="python3.12",
                Role=LAB_ROLE_ARN,
                Handler="lambda_function.lambda_handler",
                Code={"ZipFile": zip_bytes},
                Description=fn["description"],
                Timeout=fn["timeout"],
                MemorySize=fn["memory"],
                Environment={
                    "Variables": {
                        "REGION":          REGION,
                        "TABLE_READINGS":  TABLE_READINGS,
                        "TABLE_ALERTS":    TABLE_ALERTS,
                    }
                },
            )
            arn = response["FunctionArn"]
            created[fn["name"]] = arn
            success(f"Created Lambda: {fn['name']}")
            info(f"ARN: {arn}")

        except lamb.exceptions.ResourceConflictException:
            # Function exists — update the code instead
            info(f"Lambda exists: {fn['name']} — updating code...")
            response = lamb.update_function_code(
                FunctionName=fn["name"],
                ZipFile=zip_bytes,
            )
            arn = response["FunctionArn"]
            created[fn["name"]] = arn
            success(f"Updated Lambda: {fn['name']}")

    # Wait for functions to be active
    info("Waiting for Lambda functions to be ready...")
    time.sleep(5)


# ══════════════════════════════════════════════════════════════
#  STEP 4 — SQS → Lambda Event Source Mapping
# ══════════════════════════════════════════════════════════════
def create_sqs_lambda_trigger():
    step(4, "Connecting SQS → Lambda trigger")

    readings_queue_arn = created.get(f"{QUEUE_READINGS}_arn")
    alerts_queue_arn   = created.get(f"{QUEUE_ALERTS}_arn")
    ingestor_arn       = created.get(LAMBDA_INGESTOR)

    if not all([readings_queue_arn, alerts_queue_arn, ingestor_arn]):
        error("Missing ARNs — cannot create trigger")
        return

    for queue_arn, label in [
        (readings_queue_arn, "readings"),
        (alerts_queue_arn,   "alerts"),
    ]:
        try:
            lamb.create_event_source_mapping(
                EventSourceArn=queue_arn,
                FunctionName=LAMBDA_INGESTOR,
                BatchSize=10,              # Process up to 10 messages at once
                Enabled=True,
            )
            success(f"SQS ({label}) → Lambda trigger created")
        except lamb.exceptions.ResourceConflictException:
            info(f"Trigger already exists for {label} queue (skipping)")


# ══════════════════════════════════════════════════════════════
#  STEP 5 — API Gateway
# ══════════════════════════════════════════════════════════════
def create_api_gateway():
    step(5, "Creating API Gateway")

    query_arn    = created.get(LAMBDA_QUERY)
    ingestor_arn = created.get(LAMBDA_INGESTOR)

    # ── Create REST API ────────────────────────────────────────
    api = apigw.create_rest_api(
        name=API_NAME,
        description="Smart City IoT Monitoring API",
        endpointConfiguration={"types": ["REGIONAL"]},
    )
    api_id = api["id"]
    created["api_id"] = api_id
    success(f"Created API: {API_NAME} (id={api_id})")

    # ── Get root resource ID ───────────────────────────────────
    resources = apigw.get_resources(restApiId=api_id)
    root_id   = next(
        r["id"] for r in resources["items"] if r["path"] == "/"
    )

    # ── Helper: create resource + method ──────────────────────
    def add_route(path: str, method: str, lambda_arn: str,
                  use_sqs: bool = False):
        """Create a resource path and attach a Lambda integration."""
        # Create resource (e.g. /ingest)
        resource = apigw.create_resource(
            restApiId=api_id,
            parentId=root_id,
            pathPart=path,
        )
        resource_id = resource["id"]

        # Create method (e.g. POST)
        apigw.put_method(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod=method,
            authorizationType="NONE",
        )

        # Lambda integration URI
        uri = (
            f"arn:aws:apigateway:{REGION}:lambda:path"
            f"/2015-03-31/functions/{lambda_arn}/invocations"
        )

        apigw.put_integration(
            restApiId=api_id,
            resourceId=resource_id,
            httpMethod=method,
            type="AWS_PROXY",
            integrationHttpMethod="POST",
            uri=uri,
        )

        # Grant API Gateway permission to invoke Lambda
        lamb.add_permission(
            FunctionName=lambda_arn,
            StatementId=f"apigw-{path}-{method}-{int(time.time())}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=(
                f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}"
                f":{api_id}/*/{method}/{path}"
            ),
        )

        success(f"Route created: {method} /{path}")
        return resource_id

    # ── Create all routes ──────────────────────────────────────
    add_route("ingest",   "POST", ingestor_arn)
    add_route("readings", "GET",  query_arn)
    add_route("events",   "GET",  query_arn)
    add_route("summary",  "GET",  query_arn)

    # ── Enable CORS on each resource ───────────────────────────
    # (needed so React dashboard can call API from browser)
    _enable_cors(api_id, root_id)

    # ── Deploy API ─────────────────────────────────────────────
    apigw.create_deployment(
        restApiId=api_id,
        stageName=API_STAGE,
        stageDescription="Production stage",
    )

    api_url = (
        f"https://{api_id}.execute-api.{REGION}.amazonaws.com/{API_STAGE}"
    )
    created["api_url"] = api_url
    success(f"API deployed to: {api_url}")

    return api_url


def _enable_cors(api_id: str, root_id: str):
    """Add OPTIONS method to all resources for CORS preflight."""
    try:
        resources = apigw.get_resources(restApiId=api_id)
        for resource in resources["items"]:
            if resource["path"] == "/":
                continue
            try:
                apigw.put_method(
                    restApiId=api_id,
                    resourceId=resource["id"],
                    httpMethod="OPTIONS",
                    authorizationType="NONE",
                )
                apigw.put_integration(
                    restApiId=api_id,
                    resourceId=resource["id"],
                    httpMethod="OPTIONS",
                    type="MOCK",
                    requestTemplates={"application/json": '{"statusCode": 200}'},
                )
                apigw.put_method_response(
                    restApiId=api_id,
                    resourceId=resource["id"],
                    httpMethod="OPTIONS",
                    statusCode="200",
                    responseParameters={
                        "method.response.header.Access-Control-Allow-Headers": False,
                        "method.response.header.Access-Control-Allow-Methods": False,
                        "method.response.header.Access-Control-Allow-Origin":  False,
                    },
                )
                apigw.put_integration_response(
                    restApiId=api_id,
                    resourceId=resource["id"],
                    httpMethod="OPTIONS",
                    statusCode="200",
                    responseParameters={
                        "method.response.header.Access-Control-Allow-Headers":
                            "'Content-Type,X-Amz-Date,Authorization'",
                        "method.response.header.Access-Control-Allow-Methods":
                            "'GET,POST,OPTIONS'",
                        "method.response.header.Access-Control-Allow-Origin":
                            "'*'",
                    },
                )
            except Exception:
                pass  # CORS already set or not needed
    except Exception as e:
        info(f"CORS setup partial: {e}")


# ══════════════════════════════════════════════════════════════
#  STEP 6 — Update config.py with API URL
# ══════════════════════════════════════════════════════════════
def update_config(api_url: str):
    step(6, "Updating config.py with API Gateway URL")

    config_path = "config.py"
    with open(config_path, "r") as f:
        content = f.read()

    content = content.replace(
        'API_GATEWAY_URL = ""',
        f'API_GATEWAY_URL = "{api_url}"'
    )

    with open(config_path, "w") as f:
        f.write(content)

    success(f"config.py updated with: {api_url}")

    # Also write a .env file for the React dashboard
    with open("dashboard/.env", "w") as f:
        f.write(f"REACT_APP_API_URL={api_url}\n")
    success("dashboard/.env written")


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════
def main():
    print(f"""
{CYAN}{BOLD}
╔══════════════════════════════════════════════════════╗
║      SMART CITY — PHASE 3 AWS DEPLOYMENT           ║
║      Creating all cloud resources automatically    ║
╚══════════════════════════════════════════════════════╝
{RESET}""")

    start = time.time()

    try:
        create_dynamodb_tables()
        create_sqs_queues()
        create_lambda_functions()
        create_sqs_lambda_trigger()
        api_url = create_api_gateway()
        update_config(api_url)

        elapsed = round(time.time() - start, 1)

        print(f"""
{GREEN}{BOLD}
╔══════════════════════════════════════════════════════╗
║              DEPLOYMENT COMPLETE ✓                  ║
╚══════════════════════════════════════════════════════╝
{RESET}
{BOLD}Your API Gateway URL:{RESET}
  {CYAN}{api_url}{RESET}

{BOLD}Endpoints:{RESET}
  POST  {api_url}/ingest    ← Paste in fog_config.py
  GET   {api_url}/readings  ← Dashboard reads from here
  GET   {api_url}/events    ← Alerts feed
  GET   {api_url}/summary   ← Zone status map

{BOLD}Next steps:{RESET}
  1. Update fog/fog_config.py:
     CLOUD_URL = "{api_url}/ingest"

  2. Start the dashboard:
     cd dashboard && npm install && npm start

  3. Start the fog node:
     python fog_node.py

  4. Start the sensors:
     python run_all_sensors.py

Deployed in {elapsed}s
""")

    except Exception as e:
        print(f"\n{RED}Deployment failed: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
