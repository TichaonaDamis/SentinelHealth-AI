"""Client for the SentinelHealth API used by pipelines (service-account authentication)."""

from __future__ import annotations

import os

import httpx
import pandas as pd


class SentinelAPI:
    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None):
        self.base_url = (base_url or os.environ["SENTINEL_API_URL"]).rstrip("/")
        self.username = username or os.environ["SENTINEL_API_USER"]
        self.password = password or os.environ["SENTINEL_API_PASSWORD"]
        self._token: str | None = None

    def _headers(self) -> dict:
        if self._token is None:
            r = httpx.post(f"{self.base_url}/api/v1/auth/token",
                           data={"username": self.username, "password": self.password}, timeout=30)
            r.raise_for_status()
            self._token = r.json()["access_token"]
        return {"authorization": f"Bearer {self._token}"}

    def ingest_signals(self, df: pd.DataFrame, source: str, source_uri: str | None, run_id: str,
                       chunk: int = 20_000) -> list[dict]:
        results = []
        records = df.assign(observed_on=df["observed_on"].astype(str)).to_dict(orient="records")
        records = [{k: v for k, v in r.items() if v is not None and v == v} for r in records]  # drop NaN
        for i in range(0, len(records), chunk):
            r = httpx.post(f"{self.base_url}/api/v1/surveillance/signals", headers=self._headers(), timeout=300,
                           json={"source": source, "source_uri": source_uri, "pipeline_run_id": run_id,
                                 "records": records[i:i + chunk]})
            r.raise_for_status()
            results.append(r.json())
        return results

    def scan(self, as_of: str | None = None) -> dict:
        r = httpx.post(f"{self.base_url}/api/v1/analytics/scan", headers=self._headers(), timeout=600,
                       json={"as_of": as_of, "notify": True})
        r.raise_for_status()
        return r.json()

    def forecast(self, disease: str, region_id: str) -> dict:
        r = httpx.get(f"{self.base_url}/api/v1/forecasts/{disease}/{region_id}", headers=self._headers(), timeout=120)
        r.raise_for_status()
        return r.json()

    def regions(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/api/v1/regions", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def diseases(self) -> list[dict]:
        r = httpx.get(f"{self.base_url}/api/v1/diseases", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()
