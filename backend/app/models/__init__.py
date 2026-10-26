"""Operational (OLTP) data model.

PostGIS geography columns and TimescaleDB hypertables are added by the Alembic
migrations; the ORM keeps plain latitude/longitude so the same models run on
SQLite in unit tests. Analytical reporting uses the Kimball warehouse
(``warehouse`` schema, see ``alembic/versions/0002_kimball_warehouse.py``).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.security import EncryptedString
from app.db.base import Base, BigIntPK, JSONType, Vector, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(40))
    jurisdiction: Mapped[str | None] = mapped_column(String(2))  # state code; NULL = national
    organization: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Disease(Base):
    __tablename__ = "diseases"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    icd10: Mapped[str | None] = mapped_column(String(16))
    severity_weight: Mapped[float] = mapped_column(Float, default=1.0)
    nationally_notifiable: Mapped[bool] = mapped_column(Boolean, default=True)


class Region(Base):
    __tablename__ = "regions"
    id: Mapped[str] = mapped_column(String(5), primary_key=True)  # county FIPS
    name: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(2), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    population: Mapped[int] = mapped_column(Integer)


class IngestionBatch(Base):
    """Data lineage: one row per file / API pull / message batch received."""

    __tablename__ = "ingestion_batches"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(60), index=True)  # cdc_open_data, who_gho, hospital_feed, ...
    source_uri: Mapped[str | None] = mapped_column(Text)
    pipeline: Mapped[str] = mapped_column(String(120), default="api")  # Airflow DAG id or "api"
    pipeline_run_id: Mapped[str | None] = mapped_column(String(200))
    transform_version: Mapped[str] = mapped_column(String(40), default="1")
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    submitted_by: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="completed")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict | None] = mapped_column(JSONType)


class DailySignal(Base):
    """Daily aggregated multi-source signal per region and disease (TimescaleDB hypertable)."""

    __tablename__ = "daily_signals"
    __table_args__ = (
        UniqueConstraint("observed_on", "region_id", "disease_code", name="uq_daily_signal"),
        Index("ix_daily_signal_disease_date", "disease_code", "observed_on"),
    )
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    observed_on: Mapped[date] = mapped_column(Date)
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    cases: Mapped[float | None] = mapped_column(Float)
    ed_visits: Mapped[float | None] = mapped_column(Float)
    admissions: Mapped[float | None] = mapped_column(Float)
    deaths: Mapped[float | None] = mapped_column(Float)
    positivity: Mapped[float | None] = mapped_column(Float)
    otc_sales: Mapped[float | None] = mapped_column(Float)
    wastewater: Mapped[float | None] = mapped_column(Float)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_batches.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CaseReport(Base):
    """De-identified case line list. Coordinates are census-tract centroids, never addresses."""

    __tablename__ = "case_reports"
    __table_args__ = (Index("ix_case_disease_onset", "disease_code", "onset_date"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    onset_date: Mapped[date] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    age_group: Mapped[str | None] = mapped_column(String(10))
    sex: Mapped[str | None] = mapped_column(String(10))
    symptoms: Mapped[list | None] = mapped_column(JSONType)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    hospitalized: Mapped[bool | None] = mapped_column(Boolean)
    died: Mapped[bool | None] = mapped_column(Boolean)
    case_status: Mapped[str] = mapped_column(String(20), default="probable")  # suspected|probable|confirmed
    patient_ref: Mapped[str | None] = mapped_column(EncryptedString(500))  # pseudonymous, encrypted
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_batches.id"))


class LabReport(Base):
    __tablename__ = "lab_reports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    facility_id: Mapped[str | None] = mapped_column(String(40))
    specimen_date: Mapped[date] = mapped_column(Date, index=True)
    loinc_code: Mapped[str | None] = mapped_column(String(20))
    test_type: Mapped[str | None] = mapped_column(String(40))  # PCR, antigen, serology, sequencing
    result: Mapped[str] = mapped_column(String(20))  # positive | negative | indeterminate
    lineage: Mapped[str | None] = mapped_column(String(40))  # genomic lineage when sequenced
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_batches.id"))


class HospitalAdmission(Base):
    __tablename__ = "hospital_admissions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    facility_id: Mapped[str] = mapped_column(String(40))
    admit_date: Mapped[date] = mapped_column(Date, index=True)
    icu: Mapped[bool] = mapped_column(Boolean, default=False)
    ventilated: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_batches.id"))


class OutbreakEvent(Base):
    __tablename__ = "outbreak_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"), index=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"), index=True)
    detected_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="signal")  # signal|investigating|confirmed|closed
    risk_level: Mapped[str] = mapped_column(String(10))
    risk_score: Mapped[float] = mapped_column(Float)
    outbreak_probability: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(60))
    explanation: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    alerts: Mapped[list[Alert]] = relationship(back_populates="outbreak_event")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_status_created", "status", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    outbreak_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("outbreak_events.id"))
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    risk_level: Mapped[str] = mapped_column(String(10), index=True)  # green|yellow|orange|red
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|acknowledged|resolved|dismissed
    audiences: Mapped[list | None] = mapped_column(JSONType)
    deliveries: Mapped[list | None] = mapped_column(JSONType)
    acknowledged_by: Mapped[str | None] = mapped_column(String(320))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outbreak_event: Mapped[OutbreakEvent | None] = relationship(back_populates="alerts")


class ForecastRecord(Base):
    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecast_lookup", "disease_code", "region_id", "origin_date"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    disease_code: Mapped[str] = mapped_column(ForeignKey("diseases.code"))
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.id"))
    origin_date: Mapped[date] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(60))
    model_version: Mapped[str | None] = mapped_column(String(80))
    cases_total: Mapped[float] = mapped_column(Float)
    cases_lower: Mapped[float] = mapped_column(Float)
    cases_upper: Mapped[float] = mapped_column(Float)
    outbreak_probability: Mapped[float | None] = mapped_column(Float)
    hospitalization_risk: Mapped[str | None] = mapped_column(String(12))
    mortality_risk: Mapped[str | None] = mapped_column(String(12))
    details: Mapped[dict | None] = mapped_column(JSONType)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only access log (HIPAA §164.312(b)). The DB role used by the API has INSERT only."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    user_email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80))
    resource: Mapped[str | None] = mapped_column(String(300))
    method: Mapped[str | None] = mapped_column(String(10))
    path: Mapped[str | None] = mapped_column(String(500))
    status_code: Mapped[int | None] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict | None] = mapped_column(JSONType)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(40))  # guideline|case_definition|sitrep|alert|bulletin
    source: Mapped[str | None] = mapped_column(String(300))
    disease_code: Mapped[str | None] = mapped_column(String(32))
    published_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    chunks: Mapped[list[KnowledgeChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")
