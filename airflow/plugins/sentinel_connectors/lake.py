"""Medallion data lake on S3 (bronze = raw, silver = normalised, gold = curated).

Layout: s3://<bucket>/<zone>/<source>/ingest_date=YYYY-MM-DD/<run_id>.<ext>
Objects are written with SSE-KMS; the bucket enforces TLS and Object Lock for
the bronze zone so raw evidence is immutable (data lineage / reproducibility).
Falls back to a local directory when ``SENTINEL_LAKE_BUCKET`` is unset (dev).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass
class LakeObject:
    uri: str
    sha256: str
    records: int


def _key(zone: str, source: str, ingest_date: date, run_id: str, ext: str) -> str:
    safe_run = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)
    return f"{zone}/{source}/ingest_date={ingest_date.isoformat()}/{safe_run}.{ext}"


def _put(key: str, body: bytes, content_type: str) -> str:
    bucket = os.environ.get("SENTINEL_LAKE_BUCKET")
    if bucket:
        import boto3

        extra = {"ServerSideEncryption": "aws:kms"}
        kms = os.environ.get("SENTINEL_LAKE_KMS_KEY_ID")
        if kms:
            extra["SSEKMSKeyId"] = kms
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type, **extra)
        return f"s3://{bucket}/{key}"
    root = Path(os.environ.get("SENTINEL_LAKE_DIR", "/tmp/sentinel-lake"))
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return f"file://{path}"


def write_bronze(source: str, records: list[dict], ingest_date: date, run_id: str) -> LakeObject:
    body = "\n".join(json.dumps(r, sort_keys=True, default=str) for r in records).encode()
    uri = _put(_key("bronze", source, ingest_date, run_id, "jsonl"), body, "application/x-ndjson")
    return LakeObject(uri, hashlib.sha256(body).hexdigest(), len(records))


def write_silver(source: str, df: pd.DataFrame, ingest_date: date, run_id: str) -> LakeObject:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    body = buf.getvalue()
    uri = _put(_key("silver", source, ingest_date, run_id, "parquet"), body, "application/vnd.apache.parquet")
    return LakeObject(uri, hashlib.sha256(body).hexdigest(), len(df))


def read_bronze(uri: str) -> list[dict]:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = uri[5:].split("/", 1)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    else:
        body = Path(uri.removeprefix("file://")).read_bytes()
    return [json.loads(line) for line in body.decode().splitlines() if line.strip()]
