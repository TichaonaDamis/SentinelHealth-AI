"""Kimball star-schema data warehouse (``warehouse`` schema).

Dimensions: dim_date, dim_location (SCD2), dim_disease, dim_facility (SCD2), dim_population.
Facts:      fact_cases, fact_hospitalizations, fact_vaccinations, fact_lab_results, fact_alerts.

Fact tables are TimescaleDB hypertables on ``event_date`` when TimescaleDB is
available (BRIN-indexed otherwise); ``event_date`` is kept alongside the
``date_key`` surrogate so chunk/partition pruning works on date predicates.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from alembic import op

from app.db.migration_utils import execute_script

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = r"""
CREATE SCHEMA IF NOT EXISTS warehouse;

-- ---------------------------------------------------------------- dimensions
CREATE TABLE warehouse.dim_date (
    date_key        integer PRIMARY KEY,              -- YYYYMMDD
    full_date       date NOT NULL UNIQUE,
    day_of_week     smallint NOT NULL,                -- 1 = Monday
    day_name        varchar(9) NOT NULL,
    day_of_month    smallint NOT NULL,
    day_of_year     smallint NOT NULL,
    iso_week        smallint NOT NULL,
    mmwr_week       smallint NOT NULL,                -- CDC epidemiological week
    mmwr_year       smallint NOT NULL,
    month           smallint NOT NULL,
    month_name      varchar(9) NOT NULL,
    quarter         smallint NOT NULL,
    year            smallint NOT NULL,
    is_weekend      boolean NOT NULL,
    respiratory_season varchar(9)                     -- e.g. 2025-2026 (Oct-May), NULL off-season
);

CREATE TABLE warehouse.dim_location (
    location_key    serial PRIMARY KEY,
    fips_code       varchar(5) NOT NULL,
    county_name     varchar(120) NOT NULL,
    state_code      char(2) NOT NULL,
    state_name      varchar(60),
    hhs_region      smallint,
    census_region   varchar(20),
    urbanicity      varchar(20),                      -- NCHS urban-rural classification
    latitude        double precision,
    longitude       double precision,
    geom            geography(Point, 4326),
    boundary        geography(MultiPolygon, 4326),
    effective_from  date NOT NULL DEFAULT DATE '1900-01-01',
    effective_to    date NOT NULL DEFAULT DATE '9999-12-31',
    is_current      boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX ux_dim_location_current ON warehouse.dim_location (fips_code) WHERE is_current;
CREATE INDEX ix_dim_location_state ON warehouse.dim_location (state_code);
CREATE INDEX ix_dim_location_geom ON warehouse.dim_location USING gist (geom);

CREATE TABLE warehouse.dim_disease (
    disease_key           serial PRIMARY KEY,
    disease_code          varchar(32) NOT NULL UNIQUE,
    disease_name          varchar(120) NOT NULL,
    category              varchar(60) NOT NULL,
    icd10_code            varchar(16),
    transmission_mode     varchar(40),                -- respiratory, vector, foodborne, contact
    vaccine_preventable   boolean NOT NULL DEFAULT false,
    nationally_notifiable boolean NOT NULL DEFAULT true,
    severity_weight       double precision NOT NULL DEFAULT 1.0
);

CREATE TABLE warehouse.dim_facility (
    facility_key    serial PRIMARY KEY,
    facility_id     varchar(40) NOT NULL,             -- CMS Certification Number / CLIA id
    facility_name   varchar(200) NOT NULL,
    facility_type   varchar(40) NOT NULL,             -- hospital, lab, pharmacy, clinic, wastewater_plant
    location_key    integer REFERENCES warehouse.dim_location(location_key),
    health_system   varchar(200),
    licensed_beds   integer,
    icu_beds        integer,
    effective_from  date NOT NULL DEFAULT DATE '1900-01-01',
    effective_to    date NOT NULL DEFAULT DATE '9999-12-31',
    is_current      boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX ux_dim_facility_current ON warehouse.dim_facility (facility_id) WHERE is_current;

CREATE TABLE warehouse.dim_population (
    population_key   serial PRIMARY KEY,
    location_key     integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    year             smallint NOT NULL,
    age_group        varchar(10) NOT NULL,           -- 0-4, 5-17, 18-49, 50-64, 65+, ALL
    sex              varchar(10) NOT NULL,           -- female, male, ALL
    population_count integer NOT NULL,
    source           varchar(60) NOT NULL DEFAULT 'census_pep',
    UNIQUE (location_key, year, age_group, sex)
);

-- --------------------------------------------------------------------- facts
CREATE TABLE warehouse.fact_cases (
    event_date        date NOT NULL,
    date_key          integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key      integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    disease_key       integer NOT NULL REFERENCES warehouse.dim_disease(disease_key),
    population_key    integer REFERENCES warehouse.dim_population(population_key),
    case_count        integer NOT NULL DEFAULT 0,
    confirmed_count   integer NOT NULL DEFAULT 0,
    probable_count    integer NOT NULL DEFAULT 0,
    ed_visit_count    integer NOT NULL DEFAULT 0,
    hospitalized_count integer NOT NULL DEFAULT 0,
    death_count       integer NOT NULL DEFAULT 0,
    source_batch_id   uuid,
    loaded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, location_key, disease_key, date_key)
);
SELECT sentinel_time_partition('warehouse.fact_cases', 'event_date', INTERVAL '180 days');

CREATE TABLE warehouse.fact_hospitalizations (
    event_date         date NOT NULL,
    date_key           integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key       integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    facility_key       integer NOT NULL REFERENCES warehouse.dim_facility(facility_key),
    disease_key        integer NOT NULL REFERENCES warehouse.dim_disease(disease_key),
    new_admissions     integer NOT NULL DEFAULT 0,
    icu_admissions     integer NOT NULL DEFAULT 0,
    ventilated_count   integer NOT NULL DEFAULT 0,
    inpatient_occupied integer,
    icu_occupied       integer,
    source_batch_id    uuid,
    loaded_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, facility_key, disease_key)
);
SELECT sentinel_time_partition('warehouse.fact_hospitalizations', 'event_date', INTERVAL '180 days');

CREATE TABLE warehouse.fact_vaccinations (
    event_date        date NOT NULL,
    date_key          integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key      integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    disease_key       integer NOT NULL REFERENCES warehouse.dim_disease(disease_key),
    population_key    integer REFERENCES warehouse.dim_population(population_key),
    doses_administered integer NOT NULL DEFAULT 0,
    series_completed  integer NOT NULL DEFAULT 0,
    coverage_pct      numeric(5, 2),
    source_batch_id   uuid,
    loaded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, location_key, disease_key, date_key)
);
SELECT sentinel_time_partition('warehouse.fact_vaccinations', 'event_date', INTERVAL '365 days');

CREATE TABLE warehouse.fact_lab_results (
    event_date        date NOT NULL,
    date_key          integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key      integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    facility_key      integer REFERENCES warehouse.dim_facility(facility_key),
    disease_key       integer NOT NULL REFERENCES warehouse.dim_disease(disease_key),
    test_type         varchar(40) NOT NULL DEFAULT 'all',
    tests_performed   integer NOT NULL DEFAULT 0,
    positive_tests    integer NOT NULL DEFAULT 0,
    positivity_rate   numeric(6, 4) GENERATED ALWAYS AS (
                        CASE WHEN tests_performed > 0 THEN positive_tests::numeric / tests_performed END) STORED,
    sequenced_count   integer NOT NULL DEFAULT 0,
    source_batch_id   uuid,
    loaded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_date, location_key, disease_key, test_type, date_key)
);
SELECT sentinel_time_partition('warehouse.fact_lab_results', 'event_date', INTERVAL '180 days');

CREATE TABLE warehouse.fact_alerts (
    alert_id             uuid NOT NULL,              -- degenerate dimension (operational alerts.id)
    event_date           date NOT NULL,
    date_key             integer NOT NULL REFERENCES warehouse.dim_date(date_key),
    location_key         integer NOT NULL REFERENCES warehouse.dim_location(location_key),
    disease_key          integer NOT NULL REFERENCES warehouse.dim_disease(disease_key),
    risk_level           varchar(10) NOT NULL,
    risk_level_rank      smallint NOT NULL,          -- 0 green .. 3 red (additive-friendly)
    risk_score           double precision,
    outbreak_probability double precision,
    anomaly_score        double precision,
    status               varchar(20) NOT NULL,
    minutes_to_acknowledge integer,
    alert_count          smallint NOT NULL DEFAULT 1,
    loaded_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (alert_id, event_date)
);
SELECT sentinel_time_partition('warehouse.fact_alerts', 'event_date', INTERVAL '365 days');

-- ------------------------------------------------------------ helper views
CREATE VIEW warehouse.v_weekly_incidence AS
SELECT d.mmwr_year, d.mmwr_week, l.state_code, l.fips_code, l.county_name, dz.disease_code,
       sum(f.case_count) AS cases,
       sum(f.case_count)::numeric * 100000 / NULLIF(max(p.population_count), 0) AS incidence_per_100k
FROM warehouse.fact_cases f
JOIN warehouse.dim_date d       ON d.date_key = f.date_key
JOIN warehouse.dim_location l   ON l.location_key = f.location_key
JOIN warehouse.dim_disease dz   ON dz.disease_key = f.disease_key
LEFT JOIN warehouse.dim_population p
       ON p.location_key = f.location_key AND p.year = d.year AND p.age_group = 'ALL' AND p.sex = 'ALL'
GROUP BY 1, 2, 3, 4, 5, 6;

-- Populate dim_date 2000-2040 using CDC MMWR week rules (week 1 = first week with >= 4 days in the year,
-- weeks start on Sunday).
INSERT INTO warehouse.dim_date
SELECT to_char(d, 'YYYYMMDD')::int, d, extract(isodow FROM d), to_char(d, 'FMDay'), extract(day FROM d),
       extract(doy FROM d), extract(week FROM d),
       mmwr.week, mmwr.year,
       extract(month FROM d), to_char(d, 'FMMonth'), extract(quarter FROM d), extract(year FROM d),
       extract(isodow FROM d) IN (6, 7),
       CASE WHEN extract(month FROM d) >= 10 THEN extract(year FROM d)::int || '-' || (extract(year FROM d)::int + 1)
            WHEN extract(month FROM d) <= 5  THEN (extract(year FROM d)::int - 1) || '-' || extract(year FROM d)::int
       END
FROM generate_series(DATE '2000-01-01', DATE '2040-12-31', INTERVAL '1 day') AS g(ts)
CROSS JOIN LATERAL (SELECT g.ts::date AS d) x
CROSS JOIN LATERAL (
    SELECT CASE WHEN d >= start_next THEN 1 WHEN d >= start_this THEN ((d - start_this) / 7) + 1
                ELSE ((d - start_prev) / 7) + 1 END AS week,
           CASE WHEN d >= start_next THEN extract(year FROM d)::int + 1
                WHEN d >= start_this THEN extract(year FROM d)::int
                ELSE extract(year FROM d)::int - 1 END AS year
    FROM (
        SELECT
          (make_date(y, 1, 4) - extract(dow FROM make_date(y, 1, 4))::int)       AS start_this,
          (make_date(y + 1, 1, 4) - extract(dow FROM make_date(y + 1, 1, 4))::int) AS start_next,
          (make_date(y - 1, 1, 4) - extract(dow FROM make_date(y - 1, 1, 4))::int) AS start_prev
        FROM (SELECT extract(year FROM d)::int AS y) yy
    ) s
) mmwr;
"""

DOWNGRADE = "DROP SCHEMA IF EXISTS warehouse CASCADE;"


def upgrade() -> None:
    execute_script(op, UPGRADE)


def downgrade() -> None:
    execute_script(op, DOWNGRADE)
