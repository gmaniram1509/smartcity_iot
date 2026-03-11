# =============================================================
#  SMART CITY — PHASE 3 AWS CONFIGURATION
#  All AWS resource names and settings in one place.
#  deploy.py reads this and creates everything automatically.
# =============================================================

# ── AWS Settings ──────────────────────────────────────────────
REGION       = "us-east-1"
ACCOUNT_ID   = "259440944181"          # Your AWS Academy account ID

# ── IAM Role ──────────────────────────────────────────────────
# AWS Academy pre-creates this role — we reuse it for Lambda
LAB_ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/LabRole"

# ── DynamoDB Tables ───────────────────────────────────────────
TABLE_READINGS = "smartcity-readings"
TABLE_ALERTS   = "smartcity-alerts"

# ── SQS Queues ────────────────────────────────────────────────
QUEUE_READINGS = "smartcity-readings-queue"
QUEUE_ALERTS   = "smartcity-alerts-queue"

# ── Lambda Functions ──────────────────────────────────────────
LAMBDA_INGESTOR = "smartcity-ingestor"
LAMBDA_QUERY    = "smartcity-query"

# ── API Gateway ───────────────────────────────────────────────
API_NAME        = "smartcity-api"
API_STAGE       = "prod"

# ── Dashboard ─────────────────────────────────────────────────
DASHBOARD_PORT  = 3000    # Local React dev server port

# ── This gets filled in automatically by deploy.py ───────────
# After deploy, this file is updated with the real API URL.
# You can also set it manually after running deploy.py.
API_GATEWAY_URL = "https://p2tmvg0mfh.execute-api.us-east-1.amazonaws.com/prod"      # e.g. https://abc123.execute-api.us-east-1.amazonaws.com/prod
