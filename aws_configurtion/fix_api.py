#!/usr/bin/env python3
"""
Fixes API Gateway routing — deletes the broken API and creates a new one
with GET routes correctly wired to smartcity-query Lambda.
"""
import boto3
import time

REGION      = "us-east-1"
ACCOUNT_ID  = "259440944181"
API_NAME    = "smartcity-api"
API_STAGE   = "prod"
LAMBDA_INGESTOR = "smartcity-ingestor"
LAMBDA_QUERY    = "smartcity-query"

session = boto3.Session(region_name=REGION)
apigw   = session.client("apigateway")
lamb    = session.client("lambda")

GREEN = "\033[92m"; YELLOW = "\033[93m"; CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"

def log(msg): print(f"  {GREEN}✓ {msg}{RESET}")
def info(msg): print(f"  {YELLOW}→ {msg}{RESET}")

# ── Step 1: Delete existing API ───────────────────────────────
print(f"\n{BOLD}[1] Removing old API Gateway...{RESET}")
apis = apigw.get_rest_apis()["items"]
for api in apis:
    if api["name"] == API_NAME:
        apigw.delete_rest_api(restApiId=api["id"])
        log(f"Deleted old API: {api['id']}")
        info("Waiting 10s for deletion to propagate...")
        time.sleep(10)
        break

# ── Step 2: Get Lambda ARNs ───────────────────────────────────
print(f"\n{BOLD}[2] Getting Lambda ARNs...{RESET}")
ingestor_arn = lamb.get_function(FunctionName=LAMBDA_INGESTOR)["Configuration"]["FunctionArn"]
query_arn    = lamb.get_function(FunctionName=LAMBDA_QUERY)["Configuration"]["FunctionArn"]
log(f"Ingestor: {ingestor_arn}")
log(f"Query:    {query_arn}")

# ── Step 3: Create new API ────────────────────────────────────
print(f"\n{BOLD}[3] Creating new API Gateway...{RESET}")
api    = apigw.create_rest_api(
    name=API_NAME,
    description="Smart City IoT API",
    endpointConfiguration={"types": ["REGIONAL"]},
)
api_id = api["id"]
log(f"Created API: {api_id}")

# Get root resource
root_id = next(
    r["id"] for r in apigw.get_resources(restApiId=api_id)["items"]
    if r["path"] == "/"
)

# ── Step 4: Create routes with CORRECT Lambda mapping ─────────
print(f"\n{BOLD}[4] Creating routes...{RESET}")

routes = [
    ("ingest",   "POST", ingestor_arn),  # POST → ingestor (writes to DynamoDB)
    ("readings", "GET",  query_arn),     # GET  → query    (reads from DynamoDB)
    ("events",   "GET",  query_arn),     # GET  → query
    ("summary",  "GET",  query_arn),     # GET  → query
]

for path, method, lambda_arn in routes:
    # Create resource
    resource    = apigw.create_resource(restApiId=api_id, parentId=root_id, pathPart=path)
    resource_id = resource["id"]

    # Create method
    apigw.put_method(
        restApiId=api_id, resourceId=resource_id,
        httpMethod=method, authorizationType="NONE",
    )

    # Wire to correct Lambda
    uri = (
        f"arn:aws:apigateway:{REGION}:lambda:path"
        f"/2015-03-31/functions/{lambda_arn}/invocations"
    )
    apigw.put_integration(
        restApiId=api_id, resourceId=resource_id,
        httpMethod=method, type="AWS_PROXY",
        integrationHttpMethod="POST", uri=uri,
    )

    # Add method response
    apigw.put_method_response(
        restApiId=api_id, resourceId=resource_id,
        httpMethod=method, statusCode="200",
        responseParameters={
            "method.response.header.Access-Control-Allow-Origin": False,
        },
    )

    # Grant API Gateway permission to invoke this Lambda
    try:
        lamb.add_permission(
            FunctionName=lambda_arn,
            StatementId=f"apigw-{path}-{method}-{int(time.time())}",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/{method}/{path}",
        )
    except lamb.exceptions.ResourceConflictException:
        pass

    # Add OPTIONS for CORS
    try:
        apigw.put_method(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", authorizationType="NONE",
        )
        apigw.put_integration(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", type="MOCK",
            requestTemplates={"application/json": '{"statusCode":200}'},
        )
        apigw.put_method_response(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", statusCode="200",
            responseParameters={
                "method.response.header.Access-Control-Allow-Headers": False,
                "method.response.header.Access-Control-Allow-Methods": False,
                "method.response.header.Access-Control-Allow-Origin":  False,
            },
        )
        apigw.put_integration_response(
            restApiId=api_id, resourceId=resource_id,
            httpMethod="OPTIONS", statusCode="200",
            responseParameters={
                "method.response.header.Access-Control-Allow-Headers": "'Content-Type'",
                "method.response.header.Access-Control-Allow-Methods": "'GET,POST,OPTIONS'",
                "method.response.header.Access-Control-Allow-Origin":  "'*'",
            },
        )
    except Exception:
        pass

    log(f"{method} /{path} → {LAMBDA_QUERY if method == 'GET' else LAMBDA_INGESTOR}")

# ── Step 5: Deploy ────────────────────────────────────────────
print(f"\n{BOLD}[5] Deploying API...{RESET}")
apigw.create_deployment(restApiId=api_id, stageName=API_STAGE)

new_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com/{API_STAGE}"
log(f"Deployed: {new_url}")

# ── Step 6: Update .env ───────────────────────────────────────
print(f"\n{BOLD}[6] Updating dashboard .env...{RESET}")
import os
env_path = os.path.join(os.path.dirname(__file__), "dashboard", ".env")
with open(env_path, "w") as f:
    f.write(f"REACT_APP_API_URL={new_url}\n")
log(f"dashboard/.env updated")

print(f"""
{GREEN}{BOLD}
╔══════════════════════════════════════════════════════╗
║           API GATEWAY FIXED ✓                       ║
╚══════════════════════════════════════════════════════╝
{RESET}
{BOLD}New API URL:{RESET}  {CYAN}{new_url}{RESET}

{BOLD}Update fog_config.py:{RESET}
  CLOUD_URL = "{new_url}/ingest"

{BOLD}Restart dashboard:{RESET}
  cd dashboard && npm start
""")
