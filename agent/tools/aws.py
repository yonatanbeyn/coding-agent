"""AWS tools — uses boto3 SDK with CLI fallback.

Requires: boto3 installed, AWS credentials configured (~/.aws/credentials or env vars).
"""

import json
import subprocess
from datetime import date, timedelta


def _aws_cli(args: list[str]) -> dict:
    """Execute an AWS CLI command and return parsed JSON output."""
    result = subprocess.run(
        ["aws"] + args + ["--output", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"output": result.stdout.strip()}


def list_s3_buckets() -> dict:
    """List all S3 buckets in the AWS account."""
    try:
        import boto3
        s3 = boto3.client("s3")
        response = s3.list_buckets()
        buckets = [
            {"name": b["Name"], "created": b["CreationDate"].isoformat()}
            for b in response.get("Buckets", [])
        ]
        return {"buckets": buckets, "count": len(buckets)}
    except ImportError:
        # Fallback to CLI
        data = _aws_cli(["s3api", "list-buckets"])
        if "error" in data:
            return data
        buckets = [b["Name"] for b in data.get("Buckets", [])]
        return {"buckets": buckets, "count": len(buckets)}
    except Exception as e:
        return {"error": str(e)}


def get_aws_billing(service: str | None = None, days: int = 7) -> dict:
    """Get current AWS billing/cost info using Cost Explorer."""
    end = date.today()
    start = end - timedelta(days=days)

    try:
        import boto3
        ce = boto3.client("ce", region_name="us-east-1")

        kwargs: dict = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "DAILY",
            "Metrics": ["BlendedCost", "UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        if service:
            kwargs["Filter"] = {
                "Dimensions": {"Key": "SERVICE", "Values": [service]}
            }

        response = ce.get_cost_and_usage(**kwargs)
        results = []
        for result in response.get("ResultsByTime", []):
            period = result["TimePeriod"]
            groups = result.get("Groups", [])
            for group in groups:
                svc = group["Keys"][0]
                amount = group["Metrics"]["BlendedCost"]["Amount"]
                unit = group["Metrics"]["BlendedCost"]["Unit"]
                results.append({
                    "date": period["Start"],
                    "service": svc,
                    "cost": float(amount),
                    "unit": unit,
                })

        total = sum(r["cost"] for r in results)
        return {
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "service_filter": service,
            "results": results,
            "total_cost": round(total, 4),
            "currency": "USD",
        }
    except ImportError:
        # Fallback to CLI
        args = [
            "ce", "get-cost-and-usage",
            "--time-period", json.dumps({"Start": start.isoformat(), "End": end.isoformat()}),
            "--granularity", "DAILY",
            "--metrics", "BlendedCost",
        ]
        if service:
            args += ["--filter", json.dumps({"Dimensions": {"Key": "SERVICE", "Values": [service]}})]
        return _aws_cli(args)
    except Exception as e:
        return {"error": str(e)}


def list_ec2_instances(region: str | None = None) -> dict:
    """List EC2 instances with their state and type."""
    try:
        import boto3
        kwargs = {}
        if region:
            kwargs["region_name"] = region
        ec2 = boto3.client("ec2", **kwargs)
        response = ec2.describe_instances()
        instances = []
        for reservation in response.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                name = next(
                    (tag["Value"] for tag in inst.get("Tags", []) if tag["Key"] == "Name"),
                    "unnamed",
                )
                instances.append({
                    "id": inst["InstanceId"],
                    "name": name,
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "az": inst["Placement"]["AvailabilityZone"],
                })
        return {"instances": instances, "count": len(instances)}
    except Exception as e:
        return {"error": str(e)}


def get_s3_bucket_size(bucket_name: str) -> dict:
    """Get the total size and object count of an S3 bucket."""
    try:
        import boto3
        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        total_size = 0
        total_count = 0
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get("Contents", []):
                total_size += obj["Size"]
                total_count += 1
        size_mb = round(total_size / 1_048_576, 2)
        return {
            "bucket": bucket_name,
            "objects": total_count,
            "size_bytes": total_size,
            "size_mb": size_mb,
        }
    except Exception as e:
        return {"error": str(e)}


# Schemas

LIST_S3_SCHEMA = {
    "type": "object",
    "properties": {},
}

GET_BILLING_SCHEMA = {
    "type": "object",
    "properties": {
        "service": {
            "type": "string",
            "description": "Optional AWS service name to filter by (e.g. 'Amazon S3', 'Amazon EC2')",
        },
        "days": {
            "type": "integer",
            "description": "Number of past days to query. Default 7.",
            "default": 7,
        },
    },
}

LIST_EC2_SCHEMA = {
    "type": "object",
    "properties": {
        "region": {
            "type": "string",
            "description": "AWS region (e.g. us-east-1). Uses default if omitted.",
        },
    },
}

GET_S3_SIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "bucket_name": {
            "type": "string",
            "description": "Name of the S3 bucket",
        },
    },
    "required": ["bucket_name"],
}