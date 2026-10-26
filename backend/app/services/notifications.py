"""Alert routing and delivery.

Routing policy (who hears about what):

=========  ==============================================================
Level      Audiences
=========  ==============================================================
yellow     jurisdiction epidemiologists (in-app + email digest)
orange     + state health department (email + SMS via SNS)
red        + CDC analysts + healthcare networks (webhook / HAN-style feed)
=========  ==============================================================

Dispatchers are pluggable; production uses SES, SNS and signed webhooks,
local/test environments use in-app records and structured logs only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger("sentinel.notifications")

AUDIENCES_BY_LEVEL = {
    "green": [],
    "yellow": ["epidemiologists"],
    "orange": ["epidemiologists", "state_health_department"],
    "red": ["epidemiologists", "state_health_department", "cdc_analysts", "healthcare_networks"],
}
CHANNELS_BY_AUDIENCE = {
    "epidemiologists": ["in_app", "email"],
    "state_health_department": ["in_app", "email", "sms"],
    "cdc_analysts": ["in_app", "email"],
    "healthcare_networks": ["webhook"],
}


@dataclass
class AlertMessage:
    alert_id: str
    level: str
    title: str
    body: str
    disease: str
    region_id: str
    state: str
    audiences: list[str]


class Dispatcher(Protocol):
    channel: str

    async def send(self, msg: AlertMessage) -> dict: ...


class InAppDispatcher:
    channel = "in_app"

    async def send(self, msg: AlertMessage) -> dict:
        return {"channel": self.channel, "status": "stored"}  # the alert row itself is the in-app notification


class LogDispatcher:
    channel = "log"

    async def send(self, msg: AlertMessage) -> dict:
        log.warning("ALERT %s [%s] %s -> %s", msg.alert_id, msg.level.upper(), msg.title, ",".join(msg.audiences))
        return {"channel": self.channel, "status": "logged"}


class SESDispatcher:
    channel = "email"

    def __init__(self, sender: str):
        self.sender = sender

    async def send(self, msg: AlertMessage) -> dict:
        import boto3  # imported lazily: optional in local environments

        # Recipients are resolved from distribution lists in SSM per audience and state.
        ses = boto3.client("sesv2")
        resp = ses.send_email(
            FromEmailAddress=self.sender,
            Destination={"ToAddresses": _distribution_list(msg)},
            Content={"Simple": {"Subject": {"Data": f"[{msg.level.upper()}] {msg.title}"},
                                "Body": {"Text": {"Data": msg.body}}}},
        )
        return {"channel": self.channel, "status": "sent", "message_id": resp.get("MessageId")}


class SNSDispatcher:
    channel = "sms"

    def __init__(self, topic_arn: str):
        self.topic_arn = topic_arn

    async def send(self, msg: AlertMessage) -> dict:
        import boto3

        resp = boto3.client("sns").publish(
            TopicArn=self.topic_arn,
            Subject=f"[{msg.level.upper()}] {msg.title}"[:100],
            Message=f"{msg.title}. Open SentinelHealth for details.",  # no PHI over SMS
            MessageAttributes={"state": {"DataType": "String", "StringValue": msg.state},
                               "level": {"DataType": "String", "StringValue": msg.level}},
        )
        return {"channel": self.channel, "status": "sent", "message_id": resp.get("MessageId")}


class WebhookDispatcher:
    channel = "webhook"

    def __init__(self, url: str, secret: str):
        self.url, self.secret = url, secret.encode()

    async def send(self, msg: AlertMessage) -> dict:
        body = json.dumps({
            "alert_id": msg.alert_id, "level": msg.level, "title": msg.title, "disease": msg.disease,
            "region_id": msg.region_id, "state": msg.state, "sent_at": datetime.now(UTC).isoformat(),
        }).encode()
        sig = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(self.url, content=body, headers={
                "content-type": "application/json", "x-sentinel-signature": f"sha256={sig}"})
        return {"channel": self.channel, "status": "sent" if r.is_success else "failed", "http_status": r.status_code}


def _distribution_list(msg: AlertMessage) -> list[str]:  # pragma: no cover - AWS only
    import boto3

    ssm = boto3.client("ssm")
    emails: list[str] = []
    for aud in msg.audiences:
        try:
            p = ssm.get_parameter(Name=f"/sentinel/distribution/{aud}/{msg.state}")
            emails += json.loads(p["Parameter"]["Value"])
        except ssm.exceptions.ParameterNotFound:
            continue
    return emails


def build_dispatchers() -> dict[str, Dispatcher]:
    s = get_settings()
    d: dict[str, Dispatcher] = {"in_app": InAppDispatcher(), "log": LogDispatcher()}
    if "email" in s.notification_channels and s.ses_sender:
        d["email"] = SESDispatcher(s.ses_sender)
    if "sms" in s.notification_channels and s.sns_topic_arn:
        d["sms"] = SNSDispatcher(s.sns_topic_arn)
    if "webhook" in s.notification_channels and s.partner_webhook_url:
        d["webhook"] = WebhookDispatcher(s.partner_webhook_url, s.jwt_secret)
    return d


async def dispatch(msg: AlertMessage, dispatchers: dict[str, Dispatcher] | None = None) -> list[dict]:
    dispatchers = dispatchers or build_dispatchers()
    wanted = {"log"} | {c for a in msg.audiences for c in CHANNELS_BY_AUDIENCE.get(a, [])}
    results = []
    for channel in sorted(wanted):
        dispatcher = dispatchers.get(channel)
        if dispatcher is None:
            results.append({"channel": channel, "status": "skipped", "reason": "channel not configured"})
            continue
        try:
            results.append(await dispatcher.send(msg))
        except Exception as exc:  # delivery failures must never lose the alert itself
            log.exception("delivery via %s failed", channel)
            results.append({"channel": channel, "status": "failed", "error": type(exc).__name__})
    return results
