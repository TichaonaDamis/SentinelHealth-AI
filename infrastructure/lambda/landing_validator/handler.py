"""Landing-zone validator Lambda.

Triggered by S3 ``ObjectCreated`` on ``<feed>/uploads/``. Performs cheap,
synchronous checks before data enters the pipeline:

* allowed feed and file type, size limit
* header contains the feed's required columns
* rejects files that look like they contain direct identifiers (SSN / MRN /
  name columns) — partners must send de-identified aggregates or line lists

Valid files are moved to ``<feed>/incoming/`` (picked up by the
``ingest_partner_feeds`` DAG); invalid ones to ``<feed>/rejected/`` with a
JSON reason file, and a metric is emitted.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from urllib.parse import unquote_plus

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)
s3 = boto3.client("s3")
cw = boto3.client("cloudwatch")

REQUIRED = {
    "syndromic": {"date", "fips", "syndrome", "visits"},
    "hospital": {"date", "fips", "condition", "admissions"},
    "pharmacy": {"date", "fips", "category", "units_index"},
    "environment": {"date", "fips", "target", "concentration_idx"},
}
FORBIDDEN_COLUMNS = {"ssn", "social_security", "mrn", "medical_record_number", "first_name", "last_name",
                     "patient_name", "dob", "date_of_birth", "address", "street", "phone", "email"}
MAX_BYTES = int(os.environ.get("MAX_BYTES", 200 * 1024 * 1024))


def _move(bucket: str, key: str, dest_prefix: str) -> str:
    feed, _, name = key.split("/", 2)
    new_key = f"{feed}/{dest_prefix}/{name.split('/')[-1]}"
    s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": key},
                   ServerSideEncryption="aws:kms")
    s3.delete_object(Bucket=bucket, Key=key)
    return new_key


def validate(feed: str, head: bytes, size: int, key: str) -> list[str]:
    errors = []
    if feed not in REQUIRED:
        return [f"unknown feed '{feed}'"]
    if size > MAX_BYTES:
        errors.append(f"file larger than {MAX_BYTES} bytes")
    if key.endswith(".csv"):
        header = next(csv.reader(io.StringIO(head.decode("utf-8", errors="replace"))), [])
        cols = {c.strip().lower() for c in header}
    elif key.endswith(".json"):
        try:
            first = json.loads(head)[0] if head.strip().startswith(b"[") else json.loads(head.splitlines()[0])
            cols = {c.lower() for c in first}
        except Exception:
            return ["unparseable JSON header (send a JSON array of records or NDJSON)"]
    else:
        return ["unsupported file type (csv or json only)"]
    missing = REQUIRED[feed] - cols
    if missing:
        errors.append(f"missing columns: {sorted(missing)}")
    pii = cols & FORBIDDEN_COLUMNS
    if pii:
        errors.append(f"direct identifiers are not accepted: {sorted(pii)}")
    return errors


def handler(event, context):
    results = []
    for rec in event["Records"]:
        bucket = rec["s3"]["bucket"]["name"]
        key = unquote_plus(rec["s3"]["object"]["key"])
        size = rec["s3"]["object"].get("size", 0)
        feed = key.split("/", 1)[0]
        head = s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")["Body"].read()
        if key.endswith(".json") and head.strip().startswith(b"["):
            head = s3.get_object(Bucket=bucket, Key=key)["Body"].read() if size < 5_000_000 else head
        errors = validate(feed, head, size, key)
        if errors:
            new_key = _move(bucket, key, "rejected")
            s3.put_object(Bucket=bucket, Key=new_key + ".reason.json", Body=json.dumps({"errors": errors}).encode(),
                          ServerSideEncryption="aws:kms")
        else:
            new_key = _move(bucket, key, "incoming")
        cw.put_metric_data(Namespace="SentinelHealth/Landing", MetricData=[{
            "MetricName": "FilesRejected" if errors else "FilesAccepted", "Value": 1, "Unit": "Count",
            "Dimensions": [{"Name": "Feed", "Value": feed}]}])
        log.info(json.dumps({"key": key, "result": new_key, "errors": errors}))
        results.append({"key": key, "accepted": not errors})
    return results
