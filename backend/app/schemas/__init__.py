"""Pydantic request/response models (the public API contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

RiskLevel = Literal["green", "yellow", "orange", "red"]
OutbreakTier = Literal["High", "Medium", "Low"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth --------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    jurisdiction: str | None
    organization: str | None
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)
    role: Literal["admin", "epidemiologist", "cdc_analyst", "state_health_officer", "healthcare_partner", "viewer"]
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=2)
    organization: str | None = None

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        classes = sum([any(c.islower() for c in v), any(c.isupper() for c in v), any(c.isdigit() for c in v),
                       any(not c.isalnum() for c in v)])
        if classes < 3:
            raise ValueError("password must mix at least 3 of: lowercase, uppercase, digits, symbols")
        return v


# --- reference ---------------------------------------------------------------
class DiseaseOut(ORM):
    code: str
    name: str
    category: str
    icd10: str | None
    severity_weight: float


class RegionOut(ORM):
    id: str
    name: str
    state: str
    lat: float
    lon: float
    population: int


# --- surveillance ------------------------------------------------------------
class SignalIn(BaseModel):
    observed_on: date
    region_id: str
    disease_code: str
    cases: float | None = Field(default=None, ge=0)
    ed_visits: float | None = Field(default=None, ge=0)
    admissions: float | None = Field(default=None, ge=0)
    deaths: float | None = Field(default=None, ge=0)
    positivity: float | None = Field(default=None, ge=0, le=1)
    otc_sales: float | None = Field(default=None, ge=0)
    wastewater: float | None = Field(default=None, ge=0)


class IngestRequest(BaseModel):
    source: str = Field(examples=["hospital_feed", "syndromic", "pharmacy", "wastewater", "cdc_open_data"])
    source_uri: str | None = None
    pipeline_run_id: str | None = None
    records: list[SignalIn] = Field(min_length=1, max_length=50_000)


class IngestResult(BaseModel):
    batch_id: uuid.UUID
    accepted: int
    rejected: int
    errors: list[str] = []


class SignalOut(ORM):
    observed_on: date
    region_id: str
    disease_code: str
    cases: float | None
    ed_visits: float | None
    admissions: float | None
    deaths: float | None
    positivity: float | None
    otc_sales: float | None
    wastewater: float | None


class CaseReportIn(BaseModel):
    disease_code: str
    region_id: str
    onset_date: date
    report_date: date | None = None
    age_group: str | None = None
    sex: Literal["female", "male", "other", "unknown"] | None = None
    symptoms: list[str] | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    hospitalized: bool | None = None
    died: bool | None = None
    case_status: Literal["suspected", "probable", "confirmed"] = "probable"
    patient_ref: str | None = Field(default=None, description="Pseudonymous identifier; encrypted at rest")


class LineageOut(ORM):
    id: uuid.UUID
    source: str
    source_uri: str | None
    pipeline: str
    pipeline_run_id: str | None
    transform_version: str
    checksum_sha256: str | None
    record_count: int
    rejected_count: int
    submitted_by: str | None
    status: str
    received_at: datetime


# --- analytics ---------------------------------------------------------------
class Contribution(BaseModel):
    feature: str
    value: float


class RiskAssessmentOut(BaseModel):
    disease_code: str
    region_id: str
    region_name: str
    state: str
    as_of: date
    risk_level: RiskLevel
    risk_score: float
    outbreak_probability: float
    outbreak_tier: OutbreakTier
    anomaly_score: float
    anomaly_flag: bool
    ears_c2: float
    incidence_7d_per_100k: float
    growth_7d: float
    drivers: list[Contribution]
    reasons: list[str]


class ScanRequest(BaseModel):
    diseases: list[str] | None = None
    as_of: date | None = None
    notify: bool = True


class ScanResult(BaseModel):
    as_of: date
    evaluated: int
    signals: int
    alerts_created: int
    assessments: list[RiskAssessmentOut]


class OutbreakEventOut(ORM):
    id: uuid.UUID
    disease_code: str
    region_id: str
    detected_on: date
    status: str
    risk_level: str
    risk_score: float
    outbreak_probability: float
    anomaly_score: float
    method: str
    explanation: dict | None
    created_at: datetime


class HotspotOut(BaseModel):
    cluster_id: int
    disease: str | None
    case_count: int
    centroid_lat: float
    centroid_lon: float
    radius_km: float
    relative_risk: float | None
    method: str


# --- forecasts ---------------------------------------------------------------
class ForecastPoint(BaseModel):
    date: date
    mean: float
    lower: float
    upper: float


class HorizonRisk(BaseModel):
    horizon_days: int
    forecast_cases: float
    forecast_cases_lower: float
    forecast_cases_upper: float
    expected_admissions: float
    expected_deaths: float
    admissions_per_100k: float
    deaths_per_100k: float
    hospitalization_risk: str
    mortality_risk: str
    trend: str


class ForecastOut(BaseModel):
    disease_code: str
    region_id: str
    origin_date: date
    model: str
    outbreak_probability: float
    outbreak_tier: OutbreakTier
    horizons: list[HorizonRisk]
    history: list[ForecastPoint]
    path: list[ForecastPoint]


# --- alerts ------------------------------------------------------------------
class AlertOut(ORM):
    id: uuid.UUID
    outbreak_event_id: uuid.UUID | None
    disease_code: str
    region_id: str
    risk_level: str
    title: str
    message: str
    status: str
    audiences: list | None
    deliveries: list | None
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    resolution_note: str | None
    created_at: datetime


class AlertUpdate(BaseModel):
    status: Literal["acknowledged", "resolved", "dismissed"]
    note: str | None = Field(default=None, max_length=4000)


# --- dashboard ---------------------------------------------------------------
class KPI(BaseModel):
    active_cases: int
    active_cases_change_pct: float
    outbreaks_detected: int
    forecasted_cases_14d: int
    open_alerts: int
    alerts_by_level: dict[str, int]
    hotspots: int


class TrendPoint(BaseModel):
    date: date
    values: dict[str, float]


class RegionRisk(BaseModel):
    region_id: str
    name: str
    state: str
    lat: float
    lon: float
    incidence_7d_per_100k: float
    risk_level: RiskLevel
    top_disease: str | None


class DashboardSummary(BaseModel):
    as_of: date
    kpis: KPI
    trend: list[TrendPoint]
    regions: list[RegionRisk]
    recent_alerts: list[AlertOut]


# --- copilot -----------------------------------------------------------------
class CopilotQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    disease_code: str | None = None
    region_id: str | None = None


class Citation(BaseModel):
    ref: str
    title: str
    source: str | None
    snippet: str
    score: float


class CopilotAnswer(BaseModel):
    answer: str
    provider: str
    model: str | None
    citations: list[Citation]
    context_facts: list[str]


class SitrepRequest(BaseModel):
    disease_code: str | None = None
    state: str | None = Field(default=None, min_length=2, max_length=2)
    period_days: int = Field(default=14, ge=7, le=90)


class KnowledgeDocIn(BaseModel):
    title: str = Field(max_length=300)
    doc_type: Literal["guideline", "case_definition", "sitrep", "alert", "bulletin", "protocol"]
    content: str = Field(min_length=20, max_length=500_000)
    source: str | None = None
    disease_code: str | None = None
    published_on: date | None = None


class KnowledgeDocOut(ORM):
    id: uuid.UUID
    title: str
    doc_type: str
    source: str | None
    disease_code: str | None
    published_on: date | None
    created_at: datetime


class AuditLogOut(ORM):
    id: int
    occurred_at: datetime
    request_id: str | None
    user_id: str | None
    user_email: str | None
    role: str | None
    action: str
    resource: str | None
    method: str | None
    path: str | None
    status_code: int | None
    ip_address: str | None
    details: dict | None
