#!/usr/bin/env python3
# =============================================================
#  SMART CITY — SESSION REFRESH SCRIPT
#
#  AWS Academy lab sessions expire every 3-4 hours.
#  Run this at the START of each new lab session:
#
#    python redeploy.py
#
#  It will:
#    1. Verify your new credentials work
#    2. Check which resources still exist
#    3. Recreate anything that was deleted when lab reset
#    4. Update Lambda code if changed
#    5. Print your API URL (may be the same or new)
# =============================================================

import boto3
import json
import sys
import time
from config import (
    REGION, ACCOUNT_ID, LAB_ROLE_ARN,
    TABLE_READINGS, TABLE_ALERTS,
    QUEUE_READINGS, QUEUE_ALERTS,
    LAMBDA_INGESTOR, LAMBDA_QUERY,
    API_NAME, API_STAGE,
)

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

session = boto3.Session(region_name=REGION)
dynamo  = session.client("dynamodb")
sqs     = session.client("sqs")
lamb    = session.client("lambda")
apigw   = session.client("apigateway")
sts     = session.client("sts")


def check(label, fn):
    try:
        result = fn()
        print(f"  {GREEN}✓ {label}{RESET}")
        return result
    except Exception as e:
        print(f"  {RED}✗ {label}: {e}{RESET}")
        return None


def main():
    print(f"\n{CYAN}{BOLD}Smart City — Session Refresh{RESET}\n")

    # ── Step 1: Verify credentials ────────────────────────────
    print(f"{BOLD}[1] Checking AWS credentials...{RESET}")
    identity = check(
        "Credentials valid",
        lambda: sts.get_caller_identity()
    )
    if not identity:
        print(f"\n{RED}Credentials invalid. Please:{RESET}")
        print("  1. Go to AWS Academy → AWS Details → Show")
        print("  2. Copy the three credential values")
        print("  3. Run: aws configure")
        print("  4. Run: aws configure set aws_session_token YOUR_TOKEN")
        sys.exit(1)

    print(f"  Account: {identity['Account']}")
    print(f"  Role:    {identity['Arn'].split('/')[-1]}")

    # ── Step 2: Check DynamoDB ────────────────────────────────
    print(f"\n{BOLD}[2] Checking DynamoDB tables...{RESET}")
    tables = check(
        "DynamoDB accessible",
        lambda: dynamo.list_tables()["TableNames"]
    ) or []

    for tname in [TABLE_READINGS, TABLE_ALERTS]:
        if tname in tables:
            print(f"  {GREEN}✓ Table exists: {tname}{RESET}")
        else:
            print(f"  {YELLOW}→ Table missing: {tname} — recreating...{RESET}")
            from deploy import create_dynamodb_tables
            create_dynamodb_tables()
            break

    # ── Step 3: Check SQS ─────────────────────────────────────
    print(f"\n{BOLD}[3] Checking SQS queues...{RESET}")
    queues = check(
        "SQS accessible",
        lambda: sqs.list_queues().get("QueueUrls", [])
    ) or []

    queue_names = [q.split("/")[-1] for q in queues]
    for qname in [QUEUE_READINGS, QUEUE_ALERTS]:
        if qname in queue_names:
            print(f"  {GREEN}✓ Queue exists: {qname}{RESET}")
        else:
            print(f"  {YELLOW}→ Queue missing: {qname} — recreating...{RESET}")
            from deploy import create_sqs_queues
            create_sqs_queues()
            break

    # ── Step 4: Check + Update Lambda ─────────────────────────
    print(f"\n{BOLD}[4] Checking Lambda functions...{RESET}")
    existing_fns = check(
        "Lambda accessible",
        lambda: [f["FunctionName"] for f in
                 lamb.list_functions()["Functions"]]
    ) or []

    import zipfile, io, os

    def update_fn(name, folder):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.write(
                os.path.join(folder, "lambda_function.py"),
                "lambda_function.py"
            )
        code = buf.getvalue()
        if name in existing_fns:
            lamb.update_function_code(FunctionName=name, ZipFile=code)
            print(f"  {GREEN}✓ Updated Lambda: {name}{RESET}")
        else:
            print(f"  {YELLOW}→ Lambda missing: {name} — recreating...{RESET}")
            from deploy import create_lambda_functions
            create_lambda_functions()

    update_fn(LAMBDA_INGESTOR, "lambda/ingestor")
    update_fn(LAMBDA_QUERY,    "lambda/query")

    # ── Step 5: Find API Gateway URL ──────────────────────────
    print(f"\n{BOLD}[5] Finding API Gateway URL...{RESET}")
    apis = check(
        "API Gateway accessible",
        lambda: apigw.get_rest_apis()["items"]
    ) or []

    api_url = None
    for api in apis:
        if api["name"] == API_NAME:
            api_id  = api["id"]
            api_url = (
                f"https://{api_id}.execute-api"
                f".{REGION}.amazonaws.com/{API_STAGE}"
            )
            print(f"  {GREEN}✓ API found: {api_url}{RESET}")
            break

    if not api_url:
        print(f"  {YELLOW}→ API Gateway not found — recreating...{RESET}")
        from deploy import create_api_gateway, update_config
        api_url = create_api_gateway()

    # ── Update config and .env ─────────────────────────────────
    if api_url:
        with open("config.py", "r") as f:
            content = f.read()
        if api_url not in content:
            import re
            content = re.sub(
                r'API_GATEWAY_URL = ".*"',
                f'API_GATEWAY_URL = "{api_url}"',
                content
            )
            with open("config.py", "w") as f:
                f.write(content)

        os.makedirs("dashboard", exist_ok=True)
        with open("dashboard/.env", "w") as f:
            f.write(f"REACT_APP_API_URL={api_url}\n")

    # ── Summary ────────────────────────────────────────────────
    print(f"""
{GREEN}{BOLD}Session ready ✓{RESET}

{BOLD}Your API URL:{RESET}
  {CYAN}{api_url}{RESET}

{BOLD}Update fog/fog_config.py:{RESET}
  CLOUD_URL = "{api_url}/ingest"

{BOLD}Then run (in separate terminals):{RESET}
  python fog_node.py
  python run_all_sensors.py
  cd dashboard && npm start
""")


if __name__ == "__main__":
    main()
