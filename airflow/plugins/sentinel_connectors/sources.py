"""Public and partner data source clients.

Every fetcher returns ``(records, source_uri)`` where ``records`` is a list of
raw dicts exactly as received; normalisation happens in ``normalize.py`` so the
raw (bronze) copy in the data lake is always the unmodified payload.

Dataset identifiers are configurable through Airflow Variables because public
portals occasionally retire or re-issue datasets.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import time
from datetime import date

import httpx

log = logging.getLogger(__name__)

SOCRATA_PAGE = 50_000
DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


def _client() -> httpx.Client:
    return httpx.Client(timeout=DEFAULT_TIMEOUT, headers={"user-agent": "SentinelHealth-AI/0.1 (+public-health)"},
                        follow_redirects=True)


def _get_with_retry(client: httpx.Client, url: str, params: dict | None = None, headers: dict | None = None,
                    attempts: int = 5) -> httpx.Response:
    for i in range(attempts):
        try:
            r = client.get(url, params=params, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if i == attempts - 1:
                raise
            wait = 2 ** i
            log.warning("GET %s failed (%s); retrying in %ss", url, exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_socrata(domain: str, dataset_id: str, where: str | None = None, order: str | None = None,
                  max_rows: int = 2_000_000) -> tuple[list[dict], str]:
    """Page through a Socrata (SODA 2.1) dataset, e.g. data.cdc.gov or healthdata.gov."""
    url = f"https://{domain}/resource/{dataset_id}.json"
    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    rows: list[dict] = []
    with _client() as client:
        offset = 0
        while offset < max_rows:
            params = {"$limit": SOCRATA_PAGE, "$offset": offset}
            if where:
                params["$where"] = where
            if order:
                params["$order"] = order
            page = _get_with_retry(client, url, params=params, headers=headers).json()
            rows.extend(page)
            if len(page) < SOCRATA_PAGE:
                break
            offset += SOCRATA_PAGE
    log.info("fetched %d rows from %s", len(rows), url)
    return rows, url


def fetch_cdc_nndss(since: date, dataset_id: str = "x9gk-5huc") -> tuple[list[dict], str]:
    """CDC NNDSS weekly tables of notifiable conditions (data.cdc.gov)."""
    return fetch_socrata("data.cdc.gov", dataset_id, where=f"year >= '{since.year}'")


def fetch_cdc_nwss_wastewater(since: date, dataset_id: str = "2ew6-ywp6") -> tuple[list[dict], str]:
    """CDC National Wastewater Surveillance System metrics (data.cdc.gov)."""
    return fetch_socrata("data.cdc.gov", dataset_id, where=f"date_end >= '{since.isoformat()}'")


def fetch_healthdata_hospital(since: date, dataset_id: str = "g62h-syeh") -> tuple[list[dict], str]:
    """HealthData.gov hospital capacity / respiratory admissions by state."""
    return fetch_socrata("healthdata.gov", dataset_id, where=f"date >= '{since.isoformat()}'")


def fetch_who_flunet(since: date,
                     url: str = "https://xmart-api-public.who.int/FLUMART/VIW_FNT") -> tuple[list[dict], str]:
    """WHO FluNet virological surveillance (global influenza), via the xMart OData API."""
    params = {"$format": "csv", "$filter": f"ISO_YEAR ge {since.year}"}
    with _client() as client:
        text = _get_with_retry(client, url, params=params).text
    return list(csv.DictReader(io.StringIO(text))), url


def fetch_who_gho(indicator: str) -> tuple[list[dict], str]:
    """WHO Global Health Observatory OData API (annual indicators, e.g. measles cases ``WHS3_62``)."""
    url = f"https://ghoapi.azureedge.net/api/{indicator}"
    with _client() as client:
        data = _get_with_retry(client, url).json()
    return data.get("value", []), url


class FHIRBulkExportClient:
    """FHIR Bulk Data ($export) client for hospital EHR feeds (SMART Backend Services auth).

    Flow: kick-off -> poll Content-Location until 200 -> download NDJSON outputs.
    """

    def __init__(self, base_url: str, access_token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"authorization": f"Bearer {access_token}", "accept": "application/fhir+json",
                        "prefer": "respond-async"}

    def export(self, since: date, types: str = "Encounter,Condition,Observation", poll_seconds: int = 30,
               max_wait_seconds: int = 3600) -> list[dict]:
        with _client() as client:
            kick = client.get(f"{self.base_url}/Group/surveillance/$export",
                              params={"_since": since.isoformat(), "_type": types}, headers=self.headers)
            kick.raise_for_status()
            status_url = kick.headers["content-location"]
            waited = 0
            while True:
                st = client.get(status_url, headers={"authorization": self.headers["authorization"]})
                if st.status_code == 200:
                    manifest = st.json()
                    break
                if st.status_code != 202 or waited > max_wait_seconds:
                    raise RuntimeError(f"bulk export failed: HTTP {st.status_code}")
                time.sleep(poll_seconds)
                waited += poll_seconds
            resources: list[dict] = []
            for out in manifest.get("output", []):
                nd = client.get(out["url"], headers={"authorization": self.headers["authorization"],
                                                     "accept": "application/fhir+ndjson"})
                nd.raise_for_status()
                import json

                resources += [json.loads(line) for line in nd.text.splitlines() if line.strip()]
        return resources
