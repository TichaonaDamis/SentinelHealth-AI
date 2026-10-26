"""Download the champion model artifacts from S3 before the API starts.

    python -m app.core.model_sync   (run by docker-entrypoint.sh when SENTINEL_MODEL_S3_URI is set)

Artifacts are verified against their manifest checksum when loaded
(``sentinel_ml.registry.load_model``), so a tampered object is rejected.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from app.core.config import get_settings

log = logging.getLogger("sentinel.model_sync")


def sync(uri: str, dest: Path) -> int:
    import boto3

    if not uri.startswith("s3://"):
        raise ValueError("SENTINEL_MODEL_S3_URI must be an s3:// URI")
    bucket, _, prefix = uri[5:].partition("/")
    dest.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client("s3")
    count = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"][len(prefix):].lstrip("/")
            if not name or "/" in name or not name.endswith((".joblib", ".json")):
                continue
            s3.download_file(bucket, obj["Key"], str(dest / name))
            count += 1
    return count


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    uri = os.environ.get("SENTINEL_MODEL_S3_URI")
    if not uri:
        log.info("SENTINEL_MODEL_S3_URI not set; using bundled artifacts")
        return 0
    n = sync(uri, get_settings().model_dir)
    log.info("synced %d model files from %s", n, uri)
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
