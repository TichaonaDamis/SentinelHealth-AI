"""Alert fan-out Lambda.

Subscribed to the SentinelHealth alerts SNS topic. Delivers RED/ORANGE alerts to
external partner endpoints (health-network webhooks, Teams/Slack incident
channels) with an HMAC-SHA256 signature so receivers can verify authenticity.
Payloads never contain PHI — only alert metadata and a deep link.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.request
from datetime import UTC, datetime

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

_secrets = boto3.client("secretsmanager")
_cache: dict[str, dict] = {}


def _endpoints() -> dict:
    """{"endpoints": [{"url": ..., "min_level": "orange", "states": ["TX"]}], "signing_key": "..."}"""
    arn = os.environ["ENDPOINTS_SECRET_ARN"]
    if arn not in _cache:
        _cache[arn] = json.loads(_secrets.get_secret_value(SecretId=arn)["SecretString"])
    return _cache[arn]


LEVELS = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _post(url: str, body: bytes, key: bytes) -> int:
    sig = hmac.new(key, body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "content-type": "application/json", "x-sentinel-signature": f"sha256={sig}"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - URLs come from a trusted secret
        return resp.status


def handler(event, context):
    cfg = _endpoints()
    key = cfg["signing_key"].encode()
    delivered, failed = 0, 0
    for record in event.get("Records", []):
        attrs = record["Sns"].get("MessageAttributes", {})
        level = attrs.get("level", {}).get("Value", "yellow")
        state = attrs.get("state", {}).get("Value")
        payload = {
            "subject": record["Sns"].get("Subject"),
            "level": level,
            "state": state,
            "message": record["Sns"]["Message"][:1000],
            "link": os.environ.get("APP_URL", ""),
            "sent_at": datetime.now(UTC).isoformat(),
        }
        body = json.dumps(payload).encode()
        for ep in cfg.get("endpoints", []):
            if LEVELS.get(level, 0) < LEVELS.get(ep.get("min_level", "orange"), 2):
                continue
            if ep.get("states") and state not in ep["states"]:
                continue
            try:
                _post(ep["url"], body, key)
                delivered += 1
            except Exception:
                log.exception("delivery failed to %s", ep["url"].split("?")[0])
                failed += 1
    log.info(json.dumps({"delivered": delivered, "failed": failed}))
    if failed and not delivered:
        raise RuntimeError("all deliveries failed")  # SNS retries, then the DLQ captures the message
    return {"delivered": delivered, "failed": failed}
