---
name: aws-inventory
description: Inspect an AWS account — list S3 buckets and their sizes, list EC2 instances, and report recent costs by service. Use when the user asks about AWS resources, usage or billing.
compatibility: Requires AWS credentials (env vars or ~/.aws/credentials) and boto3 or the aws CLI. Disabled when the agent runs with --no-aws.
allowed-tools: list_s3_buckets get_s3_bucket_size list_ec2_instances get_aws_billing
---

# AWS inventory

Activating this skill unlocks the read-only AWS tools in `allowed-tools`.

## Workflow
1. Clarify scope first if needed: which region(s)? which time window for costs?
2. Inventory:
   - Buckets: `list_s3_buckets`, then `get_s3_bucket_size` only for the
     buckets the user cares about (it is slow on large buckets).
   - Instances: `list_ec2_instances(region=...)`.
3. Costs: `get_aws_billing(days=N, service=...)`. Cost Explorer data lags by
   up to 24h, so say so when reporting.
4. Report as a short table: resource, region, size/state, and cost when known.

## Rules
- These tools are read-only. Never create, modify or delete AWS resources from
  this skill; if the user asks for that, explain and ask before using `run_shell`
  with the aws CLI.
- If credentials are missing, tell the user how to configure them
  (`aws configure` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) instead of retrying.
